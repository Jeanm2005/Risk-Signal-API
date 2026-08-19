#include "quant/stats.hpp"
#include <cmath>
#include <numeric>
#include <stdexcept>
#include <string>

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
    if (x.size() < 2) return 3.0;
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

double inverse_normal_cdf(double p) {
    if (p <= 0.0 || p >= 1.0) {
        throw std::invalid_argument(
            "inverse_normal_cdf: p must be strictly between 0 and 1 (got " +
            std::to_string(p) + ")");
    }

    static const double a[6] = {-3.969683028665376e+01, 2.209460984245205e+02,
                                -2.759285104469687e+02, 1.383577518672690e+02,
                                -3.066479806614716e+01, 2.506628277459239e+00};
    static const double b[5] = {-5.447609879822406e+01, 1.615858368580409e+02,
                                -1.556989798598866e+02, 6.680131188771972e+01,
                                -1.328068155288572e+01};
    static const double c[6] = {-7.784894002430293e-03, -3.223964580411365e-01,
                                -2.400758277161838e+00, -2.549732539343734e+00,
                                4.374664141464968e+00,  2.938163982698783e+00};
    static const double d[4] = {7.784695709041462e-03, 3.224671290700398e-01,
                                2.445134137142996e+00, 3.754408661907416e+00};

    const double p_low = 0.02425;
    const double p_high = 1.0 - p_low;

    double q, r, x;
    if (p < p_low) {
        q = std::sqrt(-2.0 * std::log(p));
        x = (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) /
            ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1.0);
    } else if (p <= p_high) {
        q = p - 0.5;
        r = q * q;
        x = (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q /
            (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1.0);
    } else {
        q = std::sqrt(-2.0 * std::log(1.0 - p));
        x = -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) /
             ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1.0);
    }

    double e = 0.5 * std::erfc(-x / std::sqrt(2.0)) - p;
    double u = e * 2.5066282746310002 * std::exp(x * x / 2.0);
    x = x - u / (1.0 + x * u / 2.0);

    return x;
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

double expected_max_sharpe(int n_trials, double variance_of_trial_sharpes) {
    if (n_trials <= 1) return 0.0; 
    if (variance_of_trial_sharpes < 0.0) {
        throw std::invalid_argument("expected_max_sharpe: variance cannot be negative");
    }
    if (variance_of_trial_sharpes == 0.0) return 0.0;  

    constexpr double gamma_em = 0.5772156649015329;
    double N = static_cast<double>(n_trials);

    double term1 = (1.0 - gamma_em) * inverse_normal_cdf(1.0 - 1.0 / N);
    double term2 = gamma_em * inverse_normal_cdf(1.0 - 1.0 / (N * std::exp(1.0)));

    return std::sqrt(variance_of_trial_sharpes) * (term1 + term2);
}

double deflated_sharpe_ratio(const std::vector<double>& returns, int n_trials,
                             double variance_of_trial_sharpes) {
    double sr_star = expected_max_sharpe(n_trials, variance_of_trial_sharpes);
    return probabilistic_sharpe_ratio(returns, sr_star);
}

double deflated_sharpe_ratio(const std::vector<double>& returns,
                             const std::vector<double>& trial_sharpe_ratios) {
    if (trial_sharpe_ratios.size() < 2) {
        return deflated_sharpe_ratio(returns, static_cast<int>(trial_sharpe_ratios.size()), 0.0);
    }
    double var = stddev(trial_sharpe_ratios);
    var = var * var;
    return deflated_sharpe_ratio(returns, static_cast<int>(trial_sharpe_ratios.size()), var);
}

}  // namespace quant