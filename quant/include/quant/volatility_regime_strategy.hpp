#pragma once
#include <string>
#include "quant/backtest.hpp"
#include "quant/ms_garch.hpp"

namespace quant {

/// A strategy that reduces exposure when the calibrated MS-GARCH model's filtered
/// probability of being in the higher-variance ("turbulent") regime crosses a
/// threshold, and holds a full position otherwise.
///
/// This is the first real StrategyRule this project puts in front of the judge --
/// deliberately simple (it only uses price data, no news/sentiment features), so
/// its point-in-time correctness is easy to reason about directly: decide() uses
/// ONLY what the given View exposes, nothing cached from outside it, which is the
/// same structural discipline run_backtest's rule contract already requires.
struct VolatilityRegimeStrategy {
    MSGarchParams params;
    size_t turbulent_regime_index{};   // which regime index has the higher implied variance
    double turbulence_threshold = 0.5; // P(turbulent) above this triggers turbulent_position
    Position calm_position = 1.0;
    Position turbulent_position = 0.0;

    /// Decide a position using ONLY data visible in `view` -- re-derives the return
    /// series from view.bars(ticker) fresh on every call, so it never depends on any
    /// state computed outside the current point-in-time boundary.
    Position decide(const PriceHistory::View& view, const std::string& ticker) const;

    /// Adapts decide() to the StrategyRule signature run_backtest expects.
    StrategyRule as_rule() const;
};

/// Calibrates a VolatilityRegimeStrategy on the point-in-time-safe price history for
/// `ticker`, using only data up to and including `calibration_end_date`. This is the
/// ONE deliberate exception to "everything is recomputed fresh each day": the GARCH
/// parameters are fit ONCE here and then held fixed while the filter runs forward
/// day by day during the backtest. This is a documented design choice, not an
/// oversight -- continuously re-fitting via Nelder-Mead at every single backtest day
/// would be correct but expensive (a single fit took double-digit seconds in testing
/// on 1500 points), and fixed-parameter, rolling-filter is standard practice in a lot
/// of real quant workflows. The FILTER itself, run inside decide(), still only ever
/// consumes returns up through the current day -- only the parameters are frozen
/// early, not the information the filter uses to update its regime belief.
VolatilityRegimeStrategy build_volatility_regime_strategy(
    const PriceHistory& history, const std::string& ticker,
    const std::string& calibration_end_date,
    double turbulence_threshold = 0.5);

}  // namespace quant