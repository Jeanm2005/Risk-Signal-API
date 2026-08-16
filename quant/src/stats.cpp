#include "quant/stats.hpp"
#include <cmath>
#include <numeric>
#include <stdexcept>

namespace quant {
    double mean(const std::vector<double>& x) {
        if (x.empty()) return 0.0;
        return std::accumulate(x.begin(), x.end(), 0.0) / static_cast<double>(x.size());
    }

    double stddev(const std::vector<double>& x) {
        if (x.size() < 2) return 0.0;
        double m = mean(x);
        double sum_sq = 0.0;
        for (double v : x) sum_sq += (v - m) * (v - m);
        return std::sqrt(sum_sq / static_cast<double>(x.size()));
    }

    double sharpe_ratio(const std::vector<double>& x) {
        double sd = stddev(x);
        if (sd <= 0.0) return 0.0;
        return mean(x) / sd;
    }

    double skewness(const std::vector<double>& x) {
        if (x.size() < 2) return 0.0;
        double m = mean(x);
        double sd = stddev(x);
        if (sd <= 0.0) return 0.0;
        double n = static_cast<double>(x.size());
        double sum_cubed = 0.0;
        for (double v : x) {
            double z = (v - m) / sd;
            sum_cubed += z * z * z;
        }
        return sum_cubed / n;
    }

    double kurtosis(const std::vector<double>& x) {
        if (x.size() < 2) return 3.0;  // degenerate case: report the normal-distribution value
        double m = mean(x);
        double sd = stddev(x);
        if (sd <= 0.0) return 3.0;
        double n = static_cast<double>(x.size());
        double sum_fourth = 0.0;
        for (double v : x) {
            double z = (v - m) / sd;
            sum_fourth += z * z * z * z;
        }
        return sum_fourth / n;
    }

    double normal_cdf(double x) {
        return 0.5 * (1.0 + std::erf(x / std::sqrt(2.0)));
    }
    
    double probabilistic_sharpe_ratio(const std::vector<double>& returns, double sr_star) {
        if (returns.size() < 2) {
            throw std::invalid_argument(
                "probabilistic_sharpe_ratio: need at least 2 return observations");
        }
    
        double sr_hat = sharpe_ratio(returns);
        double gamma3 = skewness(returns);
        double gamma4 = kurtosis(returns);
        double T = static_cast<double>(returns.size());
        double denom_inside = 1.0 - gamma3 * sr_hat + ((gamma4 - 1.0) / 4.0) * sr_hat * sr_hat;
        if (denom_inside <= 0.0) {
            throw std::runtime_error(
                "probabilistic_sharpe_ratio: non-normality adjustment produced a "
                "non-positive variance term; the estimate is not reliable for this "
                "input (extreme skewness/kurtosis relative to the Sharpe ratio)");
        }
    
        double z = (sr_hat - sr_star) * std::sqrt(T - 1.0) / std::sqrt(denom_inside);
        return normal_cdf(z);
    }
}