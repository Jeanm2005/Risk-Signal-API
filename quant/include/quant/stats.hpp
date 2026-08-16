#pragma once
#include <vector>

namespace quant {

/// Sample mean.
double mean(const std::vector<double>& x);

/// Sample standard deviation (population convention, dividing by N not N-1 --
/// matches the convention used in the PSR formula below).
double stddev(const std::vector<double>& x);

/// Per-period Sharpe ratio: mean(x) / stddev(x). NOT annualized -- annualization is
/// left to the caller, since it depends on the data's frequency (daily/weekly/etc),
/// which this function has no way to know.
double sharpe_ratio(const std::vector<double>& x);

/// Sample skewness (third standardized moment). 0 for a symmetric distribution.
double skewness(const std::vector<double>& x);

/// Sample kurtosis (fourth standardized moment), NOT excess kurtosis -- a normal
/// distribution has kurtosis 3 under this convention, not 0. This matches the
/// convention used in the PSR formula below (Bailey & Lopez de Prado).
double kurtosis(const std::vector<double>& x);

/// Standard normal CDF, Phi(x). Used by probabilistic_sharpe_ratio below.
double normal_cdf(double x);

/// Probabilistic Sharpe Ratio (Bailey & Lopez de Prado, 2012): the probability
/// that the TRUE Sharpe ratio exceeds a benchmark `sr_star`, given the observed
/// Sharpe ratio, its non-normality (skewness/kurtosis inflate or deflate the
/// estimator's variance), and the number of observations.
///
/// This is the building block DSR (Deflated Sharpe Ratio) is built from: DSR is
/// PSR evaluated against a benchmark sr_star that itself accounts for how many
/// strategy variants were tried (the more you try, the higher the bar a result
/// must clear before it's credible) -- that trial-count bookkeeping is a separate,
/// not-yet-built piece. PSR alone already answers a real, useful, honest question:
/// "given the return series and a single fixed benchmark, how confident should
/// I be that the true Sharpe ratio actually exceeds that benchmark?"
///
/// Returns a probability in [0, 1]. Requires at least 2 observations.
double probabilistic_sharpe_ratio(const std::vector<double>& returns, double sr_star);

}  // namespace quant