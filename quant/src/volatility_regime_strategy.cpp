#include "quant/volatility_regime_strategy.hpp"
#include "quant/returns.hpp"
#include <stdexcept>

namespace quant {

namespace {

double implied_unconditional_variance(const MSGarchParams& p, size_t k) {
    double denom = 1.0 - p.alpha[k] - p.beta[k];
    return (denom > 1e-6) ? (p.omega[k] / denom) : p.omega[k];
}

}  // namespace

Position VolatilityRegimeStrategy::decide(const PriceHistory::View& view,
                                          const std::string& ticker) const {
    auto bars = view.bars(ticker);  // point-in-time-safe by construction of View
    auto returns = log_returns(bars);

    // Not enough history yet to run the filter meaningfully -- default to flat
    // rather than guess. This matters early in a backtest, right after the
    // calibration window ends, when there may still be very few return points
    // visible to a given day's view.
    if (returns.size() < 2) return 0.0;

    auto filtered = ms_garch_filtered_probabilities(returns, params);
    const auto& latest = filtered.back();  // today's filtered belief, using data up to today only

    double p_turbulent = latest[turbulent_regime_index];
    return (p_turbulent > turbulence_threshold) ? turbulent_position : calm_position;
}

StrategyRule VolatilityRegimeStrategy::as_rule() const {
    // Captured by value: the strategy (small -- a handful of doubles and two 2x2
    // vectors) outlives any single call this way, regardless of what run_backtest
    // does with the returned std::function internally.
    VolatilityRegimeStrategy self = *this;
    return [self](const PriceHistory::View& view, const std::string& ticker) -> Position {
        return self.decide(view, ticker);
    };
}

VolatilityRegimeStrategy build_volatility_regime_strategy(
    const PriceHistory& history, const std::string& ticker,
    const std::string& calibration_end_date,
    double turbulence_threshold) {

    auto calibration_bars = history.as_of(calibration_end_date).bars(ticker);
    auto calibration_returns = log_returns(calibration_bars);

    if (calibration_returns.size() < 30) {
        throw std::invalid_argument(
            "build_volatility_regime_strategy: calibration window has fewer than 30 "
            "return observations (got " + std::to_string(calibration_returns.size()) +
            "); pick a later calibration_end_date or confirm the ticker has data");
    }

    auto fit = fit_ms_garch(calibration_returns, 2);

    double var0 = implied_unconditional_variance(fit.params, 0);
    double var1 = implied_unconditional_variance(fit.params, 1);
    size_t turbulent_idx = (var1 > var0) ? 1 : 0;

    VolatilityRegimeStrategy strategy;
    strategy.params = fit.params;
    strategy.turbulent_regime_index = turbulent_idx;
    strategy.turbulence_threshold = turbulence_threshold;
    strategy.calm_position = 1.0;
    strategy.turbulent_position = 0.0;
    return strategy;
}

}  // namespace quant