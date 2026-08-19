#pragma once
#include <vector>

namespace quant {

double mean(const std::vector<double>& x);
double stddev(const std::vector<double>& x);
double sharpe_ratio(const std::vector<double>& x);
double skewness(const std::vector<double>& x);
double kurtosis(const std::vector<double>& x);
double normal_cdf(double x);
double inverse_normal_cdf(double p);
double probabilistic_sharpe_ratio(const std::vector<double>& returns, double sr_star);
double expected_max_sharpe(int n_trials, double variance_of_trial_sharpes);
double deflated_sharpe_ratio(const std::vector<double>& returns, int n_trials,
                             double variance_of_trial_sharpes);
double deflated_sharpe_ratio(const std::vector<double>& returns,
                             const std::vector<double>& trial_sharpe_ratios);

}  // namespace quant