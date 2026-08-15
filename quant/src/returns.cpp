#include "quant/returns.hpp"
#include <cmath>

namespace quant {

    std::vector<double> log_returns(const std::vector<PriceBar>& bars) {
        std::vector<double> out;
        if (bars.size() < 2) return out;
        out.reserve(bars.size() - 1);
        for (size_t i = 1; i < bars.size(); ++i) {
            // Guard against a zero or negative close (shouldn't happen in real data,
            // but a corrupt row should fail loudly rather than produce NaN silently
            // downstream in the likelihood).
            if (bars[i - 1].close <= 0.0 || bars[i].close <= 0.0) {
                continue; // skip bad bar rather than poison the whole series
            }
            out.push_back(std::log(bars[i].close / bars[i - 1].close));
        }
        return out;
   }

} // namespace quant