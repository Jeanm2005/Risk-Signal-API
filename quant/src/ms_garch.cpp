#include "quant/ms_garch.hpp"
#include "quant/nelder_mead.hpp"

#include <cmath>
#include <numeric>
#include <stdexcept>

namespace quant {

namespace {

constexpr double kPi = 3.14159265358979323846;

// Gaussian density, mean 0, variance h. GARCH residuals are conventionally modeled
// as mean-zero conditional on past information.
double normal_density(double x, double variance) {
    if (variance <= 0.0) return 1e-300;  // guard: treat as ~impossible, not NaN
    return std::exp(-0.5 * x * x / variance) / std::sqrt(2.0 * kPi * variance);
}

// Core Gray's-algorithm forward pass. Returns per-step: the log-likelihood
// contribution, the filtered probabilities xi_{k,t|t}, and the per-regime
// variances h_{k,t} (needed to seed the next step's h_tilde).
struct FilterStep {
    std::vector<double> filtered_prob;  // xi_{k,t|t}, size K
    std::vector<double> variance;       // h_{k,t}, size K
    double log_lik_contribution;
};

std::vector<FilterStep> run_filter(const std::vector<double>& returns,
                                   const MSGarchParams& p) {
    const size_t K = p.n_regimes();
    const size_t T = returns.size();
    std::vector<FilterStep> steps(T);

    // t = 0: no previous residual/variance to condition on. Seed each regime's
    // variance at its unconditional GARCH variance omega/(1-alpha-beta), which is
    // the standard initialization when there's no prior history.
    std::vector<double> h_prev(K);
    for (size_t k = 0; k < K; ++k) {
        double denom = 1.0 - p.alpha[k] - p.beta[k];
        h_prev[k] = (denom > 1e-6) ? (p.omega[k] / denom) : p.omega[k];
    }
    std::vector<double> xi_prev = p.initial_prob;  // xi_{k,0|0} seeded at initial belief

    for (size_t t = 0; t < T; ++t) {
        // Collapse previous step's per-regime variances into one aggregated
        // variance, weighted by the filtered probabilities from the previous
        // step. This is the specific approximation that makes the recursion
        // tractable (Gray 1996): instead of K variances feeding into K*K next
        // variances, they collapse to 1 feeding into K.
        double h_tilde_prev = 0.0;
        for (size_t k = 0; k < K; ++k) h_tilde_prev += xi_prev[k] * h_prev[k];

        double eps_prev_sq = (t == 0) ? h_tilde_prev  // no observed residual yet;
                                                        // use the seeded variance itself
                                       : returns[t - 1] * returns[t - 1];

        // Predict step: xi_{k,t|t-1} = sum_i P(i->k) * xi_{i,t-1|t-1}
        std::vector<double> xi_pred(K, 0.0);
        for (size_t k = 0; k < K; ++k) {
            for (size_t i = 0; i < K; ++i) {
                xi_pred[k] += p.transition[i][k] * xi_prev[i];
            }
        }

        // Each regime's GARCH(1,1) variance at t, conditioning on the collapsed
        // previous variance and the actual (regime-independent) observed squared
        // residual.
        std::vector<double> h_t(K);
        for (size_t k = 0; k < K; ++k) {
            h_t[k] = p.omega[k] + p.alpha[k] * eps_prev_sq + p.beta[k] * h_tilde_prev;
        }

        // Likelihood of the current observation under each regime.
        std::vector<double> f_k(K);
        double mixture_density = 0.0;
        for (size_t k = 0; k < K; ++k) {
            f_k[k] = normal_density(returns[t], h_t[k]);
            mixture_density += xi_pred[k] * f_k[k];
        }
        if (mixture_density <= 0.0) mixture_density = 1e-300;

        // Update step: xi_{k,t|t} = xi_pred[k]*f_k[k] / mixture_density
        std::vector<double> xi_filtered(K);
        for (size_t k = 0; k < K; ++k) {
            xi_filtered[k] = (xi_pred[k] * f_k[k]) / mixture_density;
        }

        steps[t] = FilterStep{xi_filtered, h_t, std::log(mixture_density)};

        h_prev = h_t;
        xi_prev = xi_filtered;
    }

    return steps;
}

}  // namespace

double ms_garch_log_likelihood(const std::vector<double>& returns, const MSGarchParams& p) {
    if (returns.empty()) return 0.0;
    auto steps = run_filter(returns, p);
    double ll = 0.0;
    for (const auto& s : steps) ll += s.log_lik_contribution;
    return ll;
}

std::vector<std::vector<double>> ms_garch_filtered_probabilities(
    const std::vector<double>& returns, const MSGarchParams& p) {
    auto steps = run_filter(returns, p);
    std::vector<std::vector<double>> out;
    out.reserve(steps.size());
    for (const auto& s : steps) out.push_back(s.filtered_prob);
    return out;
}

namespace {

// Packs/unpacks a fixed-K=2 parameter vector for Nelder-Mead, which only knows
// about flat double vectors. K is fixed at 2 for this packing scheme (the
// standard calm/turbulent choice); a general-K version would need a different,
// more careful packing (e.g. softmax for the transition rows) and is future work.
//
// Raw optimizer parameters -> constrained model parameters:
//   omega[k]  = exp(x[k])                         -- forces omega > 0
//   alpha[k]  = sigmoid(x[2+k]) * 0.3              -- keeps alpha in a sane, stable range
//   beta[k]   = sigmoid(x[4+k]) * (0.98 - alpha_k) -- keeps alpha+beta < 1 (stationarity)
//   p_stay[k] = sigmoid(x[6+k])                    -- P(stay in regime k), diagonal of
//                                                      the transition matrix; off-diagonal
//                                                      is 1 - p_stay for the 2-regime case
constexpr size_t kNumRawParams = 8;  // K=2 fixed

double sigmoid(double x) { return 1.0 / (1.0 + std::exp(-x)); }
double logit(double p) { return std::log(p / (1.0 - p)); }

MSGarchParams unpack(const std::vector<double>& x) {
    MSGarchParams p;
    p.omega = {std::exp(x[0]), std::exp(x[1])};
    p.alpha = {sigmoid(x[2]) * 0.3, sigmoid(x[3]) * 0.3};
    p.beta = {sigmoid(x[4]) * (0.98 - p.alpha[0]), sigmoid(x[5]) * (0.98 - p.alpha[1])};

    double stay0 = sigmoid(x[6]);
    double stay1 = sigmoid(x[7]);
    p.transition = {{stay0, 1.0 - stay0}, {1.0 - stay1, stay1}};
    p.initial_prob = {0.5, 0.5};  // uninformative prior on starting regime
    return p;
}

std::vector<double> pack(const MSGarchParams& p) {
    std::vector<double> x(kNumRawParams);
    x[0] = std::log(p.omega[0]);
    x[1] = std::log(p.omega[1]);
    x[2] = logit(p.alpha[0] / 0.3);
    x[3] = logit(p.alpha[1] / 0.3);
    x[4] = logit(p.beta[0] / (0.98 - p.alpha[0]));
    x[5] = logit(p.beta[1] / (0.98 - p.alpha[1]));
    x[6] = logit(p.transition[0][0]);
    x[7] = logit(p.transition[1][1]);
    return x;
}

}  // namespace

MSGarchFitResult fit_ms_garch(const std::vector<double>& returns, size_t n_regimes,
                              int max_iterations) {
    if (n_regimes != 2) {
        throw std::invalid_argument(
            "fit_ms_garch: only n_regimes=2 is currently supported "
            "(the raw-parameter packing in ms_garch.cpp is hardcoded for K=2)");
    }
    if (returns.size() < 30) {
        throw std::invalid_argument(
            "fit_ms_garch: need a reasonable amount of data to calibrate a "
            "regime-switching model; fewer than 30 return observations is not enough");
    }

    // A reasonable starting guess: both regimes near a plausible daily-return
    // GARCH(1,1) (omega small, alpha ~0.05, beta ~0.85), regimes mildly
    // persistent (80% chance of staying).
    MSGarchParams start;
    start.omega = {1e-5, 3e-5};   // regime 1 (calm) lower baseline variance than regime 2
    start.alpha = {0.05, 0.08};
    start.beta = {0.85, 0.80};
    start.transition = {{0.9, 0.1}, {0.15, 0.85}};
    start.initial_prob = {0.5, 0.5};

    auto x0 = pack(start);

    auto negative_log_likelihood = [&](const std::vector<double>& x) -> double {
        MSGarchParams candidate = unpack(x);
        double ll = ms_garch_log_likelihood(returns, candidate);
        // Nelder-Mead minimizes; maximize likelihood by minimizing its negation.
        // Guard against NaN/inf propagating into the optimizer's comparisons.
        if (!std::isfinite(ll)) return 1e300;
        return -ll;
    };

    auto opt_result = nelder_mead(negative_log_likelihood, x0, max_iterations);

    MSGarchParams fitted = unpack(opt_result.x);
    return MSGarchFitResult{fitted, -opt_result.value, opt_result.iterations,
                            opt_result.converged};
}

}  // namespace quant