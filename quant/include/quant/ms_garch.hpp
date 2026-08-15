#pragma once
#include <vector>

namespace quant {

/// Parameters for a K-regime Markov-switching GARCH(1,1).
///
/// Within regime k: h_{k,t} = omega[k] + alpha[k]*eps_{t-1}^2 + beta[k]*h_tilde_{t-1}
/// where h_tilde_{t-1} is the REGIME-COLLAPSED variance from the previous step
/// (see ms_garch_log_likelihood for why this collapsing is necessary and what
/// it means -- this is Gray's (1996) algorithm, the standard tractable
/// approximation for MS-GARCH).
///
/// transition[i][j] = P(regime i at t-1 -> regime j at t). Each row must sum to 1.
struct MSGarchParams {
    std::vector<double> omega;   // size K, each > 0
    std::vector<double> alpha;   // size K, each >= 0
    std::vector<double> beta;    // size K, each >= 0
    std::vector<std::vector<double>> transition;  // K x K, row-stochastic
    std::vector<double> initial_prob;             // size K, sums to 1

    size_t n_regimes() const { return omega.size(); }
};

struct MSGarchFitResult {
    MSGarchParams params;
    double log_likelihood;
    int iterations;
    bool converged;
};

/// The log-likelihood of `returns` under `params`, via Gray's algorithm.
///
/// WHY THIS IS NEEDED: the regime at each time step is not observed, only returns
/// are. A model where GARCH's own path-dependent variance recursion also depends
/// on an unobserved regime path is, if done exactly, exponential in time -- at
/// step t there are K^t possible regime histories to track. Gray's algorithm makes
/// this tractable by collapsing the K possible variances at each step into a
/// single "aggregated" variance, weighted by the FILTERED regime probabilities
/// (the model's best current belief about which regime it's in, given all
/// returns observed so far). This is an approximation, not exact Bayesian
/// filtering, but it is the standard one used in the MS-GARCH literature because
/// exact filtering is computationally infeasible beyond a handful of periods.
///
/// Exposed separately from fit_ms_garch specifically so it can be unit tested on
/// its own -- against a single-regime (K=1) case, which must reduce to plain
/// GARCH(1,1) log-likelihood, and against synthetic data with known parameters --
/// before it is trusted as the objective inside an optimizer.
double ms_garch_log_likelihood(const std::vector<double>& returns, const MSGarchParams& params);

/// Filtered regime probabilities P(regime = k | returns up to and including t),
/// for every t. Row i corresponds to returns[i]. This is the actual "which regime
/// are we likely in right now" output the judge will use downstream -- distinct
/// from the log-likelihood, which is just a single scalar used for calibration.
std::vector<std::vector<double>> ms_garch_filtered_probabilities(
    const std::vector<double>& returns, const MSGarchParams& params);

/// Calibrates a K-regime MS-GARCH(1,1) to `returns` by maximizing
/// ms_garch_log_likelihood via Nelder-Mead. K=2 (calm/turbulent) is the standard,
/// tractable choice and the default.
MSGarchFitResult fit_ms_garch(const std::vector<double>& returns, size_t n_regimes = 2,
                              int max_iterations = 2000);

}  // namespace quant