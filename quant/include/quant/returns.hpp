#pragma once
#include <vector>
#include "quant/price_history.hpp"

namespace quant {
    /// Log returns: r_t = ln(close_t / close_{t-1}). Standard choice for volatility
/// modeling since they're additive across time and better-behaved statistically
/// than simple returns.
///
/// Input bars must already be point-in-time-safe (i.e. come from a View), and are
/// assumed sorted ascending by date, which PriceHistory::View guarantees. Returns
/// a vector of size bars.size()-1 (or empty if fewer than 2 bars).
std::vector<double> log_returns(const std::vector<PriceBar>& bars);

} // namespace quant