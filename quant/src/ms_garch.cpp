#include "quant/ms_garch.hpp"
#include "quant/nelder_mead.hpp"
#include <cmath>
#include <numeric>
#include <stdexcept>
#include <limits>

namespace quant {
namespace {
constexpr double kPi = 3.14159265358979323846;

double normal_density(double x, double variance) {
    if (variance <= 0.0) return 1e-300;
    return std::exp(-0.5 * x * x / variance) / std::sqrt(2.0 * kPi * variance);
}

struct FilterStep {
    std::vector<double> filtered_prob;
    std::vector<double> variance;
    double log_lik_contribution;
};

std::vector<FilterStep> run_filter(const std::vector<double>& returns, const MSGarchParams& p) {
    const size_t K = p.n_regimes();
    const size_t T = returns.size();
    std::vector<FilterStep> steps(T);

    std::vector<double> h_prev(K);
    for (size_t k = 0; k < K; ++k) {
        double denom = 1.0 - p.alpha[k] - p.beta[k];
        h_prev[k] = (denom > 1e-6) ? (p.omega[k] / denom) : p.omega[k];
    }
    std::vector<double> xi_prev = p.initial_prob;

    for (size_t t = 0; t < T; ++t) {
        double h_tilde_prev = 0.0;
        for (size_t k = 0; k < K; ++k) h_tilde_prev += xi_prev[k] * h_prev[k];

        double eps_prev_sq = (t == 0) ? h_tilde_prev : returns[t - 1] * returns[t - 1];

        std::vector<double> xi_pred(K, 0.0);
        for (size_t k = 0; k < K; ++k)
            for (size_t i = 0; i < K; ++i)
                xi_pred[k] += p.transition[i][k] * xi_prev[i];

        std::vector<double> h_t(K);
        for (size_t k = 0; k < K; ++k)
            h_t[k] = p.omega[k] + p.alpha[k] * eps_prev_sq + p.beta[k] * h_tilde_prev;

        std::vector<double> f_k(K);
        double mixture_density = 0.0;
        for (size_t k = 0; k < K; ++k) {
            f_k[k] = normal_density(returns[t], h_t[k]);
            mixture_density += xi_pred[k] * f_k[k];
        }
        if (mixture_density <= 0.0) mixture_density = 1e-300;

        std::vector<double> xi_filtered(K);
        for (size_t k = 0; k < K; ++k) xi_filtered[k] = (xi_pred[k] * f_k[k]) / mixture_density;

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
constexpr size_t kNumRawParams = 8;
double sigmoid(double x) { return 1.0 / (1.0 + std::exp(-x)); }
double logit(double p) { return std::log(p / (1.0 - p)); }

// omega_floor is a STRUCTURAL guarantee, not a hope: omega[k] = floor + exp(x[k])
// can never fall below `floor`, no matter what value the optimizer picks for x[k]
// (exp is always > 0). This directly prevents the degenerate collapse found when
// testing this model: a regime's variance shrinking toward zero, which makes it
// "explain" essentially no real data point and forces the filter to always prefer
// the other regime regardless of the actual volatility environment. The floor is
// derived from the data itself (a small fraction of the overall sample variance)
// so it scales sensibly across very different tickers/periods rather than being a
// fixed constant that might be wrong for a specific series' scale.
MSGarchParams unpack(const std::vector<double>& x, double omega_floor) {
    MSGarchParams p;
    p.omega = {omega_floor + std::exp(x[0]), omega_floor + std::exp(x[1])};
    p.alpha = {sigmoid(x[2]) * 0.3, sigmoid(x[3]) * 0.3};
    p.beta = {sigmoid(x[4]) * (0.98 - p.alpha[0]), sigmoid(x[5]) * (0.98 - p.alpha[1])};
    double stay0 = sigmoid(x[6]);
    double stay1 = sigmoid(x[7]);
    p.transition = {{stay0, 1.0 - stay0}, {1.0 - stay1, stay1}};
    p.initial_prob = {0.5, 0.5};
    return p;
}

std::vector<double> pack(const MSGarchParams& p, double omega_floor) {
    std::vector<double> x(kNumRawParams);
    x[0] = std::log(std::max(p.omega[0] - omega_floor, 1e-12));
    x[1] = std::log(std::max(p.omega[1] - omega_floor, 1e-12));
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
        throw std::invalid_argument("fit_ms_garch: only n_regimes=2 is currently supported");
    }
    if (returns.size() < 30) {
        throw std::invalid_argument("fit_ms_garch: need at least 30 return observations");
    }

    // Data-derived variance floor: 2% of the overall sample variance. Small enough
    // to allow a genuinely low-volatility regime, large enough that omega cannot
    // collapse toward numerical zero and make a regime unable to explain any real
    // observation. This 2% figure is a heuristic, not a derived constant -- it is
    // deliberately conservative (small) so it mainly acts as a safety rail rather
    // than materially constraining well-identified fits.
    double sample_var = 0.0;
    for (double r : returns) sample_var += r * r;
    sample_var /= static_cast<double>(returns.size());
    double omega_floor = 0.02 * sample_var;

    auto negative_log_likelihood = [&](const std::vector<double>& x) -> double {
        MSGarchParams candidate = unpack(x, omega_floor);
        double ll = ms_garch_log_likelihood(returns, candidate);
        if (!std::isfinite(ll)) return 1e300;
        return -ll;
    };

    // Multiple restarts from meaningfully different starting points, as a second
    // line of defense beyond the variance floor: different starting points can
    // still converge to different local optima on a genuinely multimodal
    // likelihood surface, so trying several and keeping the best is standard
    // practice for this model class, not just insurance against the one failure
    // mode already found.
    std::vector<MSGarchParams> starts;
    {
        MSGarchParams s;
        s.alpha = {0.05, 0.08};
        s.beta = {0.85, 0.80};
        s.transition = {{0.9, 0.1}, {0.15, 0.85}};
        s.initial_prob = {0.5, 0.5};
        s.omega = {0.3 * sample_var, 1.5 * sample_var};
        starts.push_back(s);
    }
    {
        MSGarchParams s;
        s.alpha = {0.05, 0.05};
        s.beta = {0.90, 0.70};
        s.transition = {{0.95, 0.05}, {0.10, 0.90}};
        s.initial_prob = {0.5, 0.5};
        s.omega = {0.5 * sample_var, 3.0 * sample_var};
        starts.push_back(s);
    }
    {
        MSGarchParams s;
        s.alpha = {0.10, 0.10};
        s.beta = {0.80, 0.80};
        s.transition = {{0.85, 0.15}, {0.20, 0.80}};
        s.initial_prob = {0.5, 0.5};
        s.omega = {0.8 * sample_var, 5.0 * sample_var};
        starts.push_back(s);
    }

    MSGarchFitResult best;
    best.log_likelihood = -std::numeric_limits<double>::infinity();
    bool have_result = false;

    for (const auto& s : starts) {
        auto x0 = pack(s, omega_floor);
        auto opt_result = nelder_mead(negative_log_likelihood, x0, max_iterations);
        double ll = -opt_result.value;
        if (!std::isfinite(ll)) continue;

        if (!have_result || ll > best.log_likelihood) {
            MSGarchParams fitted = unpack(opt_result.x, omega_floor);
            best = MSGarchFitResult{fitted, ll, opt_result.iterations, opt_result.converged};
            have_result = true;
        }
    }

    if (!have_result) {
        throw std::runtime_error(
            "fit_ms_garch: every restart produced a non-finite likelihood; "
            "the input data may be degenerate (e.g. constant returns)");
    }

    return best;
}

}  // namespace quant