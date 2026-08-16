#pragma once
#include <string>
#include <vector>
#include <functional>
#include <cmath>
#include "quant/price_history.hpp"

namespace quant {

/// A position taken on a given day. Kept as a plain double rather than an enum so a
/// rule can express partial sizing (0.5 = half position) rather than only
/// all-in/all-out, without changing the interface later.
///  1.0  = fully long
///  0.0  = flat
/// -1.0  = fully short
using Position = double;

/// A strategy rule: given a point-in-time view (as-of some date) and a ticker,
/// decide what position to hold GOING INTO the next bar. The rule receives only a
/// View, never the raw PriceHistory, so it is structurally unable to see anything
/// beyond its as-of date -- the same enforcement PriceHistory::View already
/// provides is inherited automatically here, rather than something the backtester
/// has to separately guarantee.
using StrategyRule = std::function<Position(const PriceHistory::View&, const std::string& ticker)>;

/// Per-day record of what the backtest actually did, kept for inspection/debugging
/// rather than just a final summary number -- so a run can be audited, not just
/// trusted.
struct BacktestDay {
    std::string date;
    Position position{};       // position held during this day (decided at the prior close)
    double raw_return{};       // the day's log return before costs
    double cost{};             // transaction cost paid THIS day, in return units (>= 0)
    double net_return{};       // raw_return * position - cost
};

struct BacktestResult {
    std::vector<BacktestDay> days;
    std::vector<double> net_returns;   // days[i].net_return, extracted for convenience
    double total_cost{};               // sum of all costs paid
    int n_position_changes{};          // how many times the position actually changed
};

struct TransactionCostModel {
    /// Cost, in return units, of moving from `from` to `to` (e.g. 0 -> 1 is opening a
    /// full long). A flat-bps model: cost = bps_per_unit_turnover * |to - from|.
    /// This is intentionally simple (Tier 1 scope) -- a learned cost/impact model is
    /// a documented future extension, not something this harness assumes exists yet.
    double bps_per_unit_turnover = 5.0;  // 5 bps = 0.0005, a reasonable liquid-equity default

    double cost_of_trade(Position from, Position to) const {
        return (bps_per_unit_turnover / 10000.0) * std::abs(to - from);
    }
};

/// Walks `rule` forward through `history` for `ticker`, one day at a time, starting
/// at `start_date` and ending at `end_date` (inclusive), applying `costs` whenever
/// the position changes.
///
/// POINT-IN-TIME GUARANTEE: on each day t, `rule` is called with
/// history.as_of(previous_day's date) -- NOT today's date. This is deliberate and
/// is the single most important line in this file: a rule deciding "what position
/// do I hold during day t" must not be allowed to see day t's own return, or the
/// backtest would be trivially, invisibly cheating (using today's outcome to decide
/// today's position). The position decided from yesterday's view is what earns
/// today's return.
BacktestResult run_backtest(const PriceHistory& history, const std::string& ticker,
                            const StrategyRule& rule,
                            const std::string& start_date, const std::string& end_date,
                            const TransactionCostModel& costs = TransactionCostModel{});

}  // namespace quant