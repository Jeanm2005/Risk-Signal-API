#include "quant/backtest.hpp"
#include <cmath>
#include <stdexcept>

namespace quant {

BacktestResult run_backtest(const PriceHistory& history, const std::string& ticker,
                            const StrategyRule& rule,
                            const std::string& start_date, const std::string& end_date,
                            const TransactionCostModel& costs) {
    // Pull the full point-in-time-safe series once, up to end_date, then walk it.
    // This single as_of(end_date) call does NOT leak information into the loop
    // below -- it only fixes the universe of bars we might ever look at across the
    // whole run; each individual day's DECISION still only consults bars up to
    // that day, enforced separately below. It's equivalent to saying "load
    // whatever data could possibly be relevant" without saying "look at all of it
    // when deciding any one day."
    auto all_bars = history.as_of(end_date).bars(ticker);

    BacktestResult result;
    if (all_bars.size() < 2) return result;  // nothing to trade

    // Find the first bar at or after start_date.
    size_t start_idx = 0;
    while (start_idx < all_bars.size() && all_bars[start_idx].date < start_date) {
        ++start_idx;
    }
    if (start_idx >= all_bars.size() - 1) return result;  // no room to hold a position

    Position current_position = 0.0;  // start flat

    for (size_t i = start_idx; i + 1 < all_bars.size(); ++i) {
        const PriceBar& today = all_bars[i];
        const PriceBar& tomorrow = all_bars[i + 1];

        // THE point-in-time enforcement: the rule is given a view as-of TODAY's
        // date, so it can see today's close and everything before it, but it
        // cannot see tomorrow's bar -- which is the bar whose return it is about
        // to be exposed to. The position decided here is what earns the return
        // realized going from today's close to tomorrow's close.
        auto decision_view = history.as_of(today.date);
        Position new_position = rule(decision_view, ticker);

        double cost = costs.cost_of_trade(current_position, new_position);
        if (new_position != current_position) result.n_position_changes++;

        double raw_return = 0.0;
        if (today.close > 0.0 && tomorrow.close > 0.0) {
            raw_return = std::log(tomorrow.close / today.close);
        }

        double net_return = raw_return * new_position - cost;

        result.days.push_back(BacktestDay{
            tomorrow.date, new_position, raw_return, cost, net_return});
        result.net_returns.push_back(net_return);
        result.total_cost += cost;

        current_position = new_position;
    }

    return result;
}

}  // namespace quant