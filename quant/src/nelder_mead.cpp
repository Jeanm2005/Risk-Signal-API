#include "quant/nelder_mead.hpp"
#include <algorithm>
#include <cmath>
#include <limits>

namespace quant {

namespace {

using Vec = std::vector<double>;

Vec add(const Vec& a, const Vec& b, double scale_b) {
    Vec out(a.size());
    for (size_t i = 0; i < a.size(); ++i) out[i] = a[i] + scale_b * b[i];
    return out;
}

Vec centroid_excluding_worst(const std::vector<Vec>& simplex, size_t worst_idx) {
    Vec c(simplex[0].size(), 0.0);
    size_t n = 0;
    for (size_t i = 0; i < simplex.size(); ++i) {
        if (i == worst_idx) continue;
        for (size_t d = 0; d < c.size(); ++d) c[d] += simplex[i][d];
        ++n;
    }
    for (double& v : c) v /= static_cast<double>(n);
    return c;
}

}  // namespace

NelderMeadResult nelder_mead(
    const std::function<double(const Vec&)>& objective,
    Vec initial_guess,
    int max_iterations,
    double tolerance) {

    const size_t n = initial_guess.size();
    const double alpha = 1.0;   // reflection
    const double gamma = 2.0;   // expansion
    const double rho = 0.5;     // contraction
    const double sigma = 0.5;   // shrink

    // Build the initial simplex: n+1 points around initial_guess.
    std::vector<Vec> simplex;
    simplex.push_back(initial_guess);
    for (size_t i = 0; i < n; ++i) {
        Vec p = initial_guess;
        // Standard step size heuristic: 5% of the coordinate, or a small fixed
        // step if the coordinate is exactly zero.
        double step = (p[i] != 0.0) ? 0.05 * p[i] : 0.00025;
        p[i] += step;
        simplex.push_back(p);
    }

    std::vector<double> fvals(n + 1);
    for (size_t i = 0; i <= n; ++i) fvals[i] = objective(simplex[i]);

    int iter = 0;
    bool converged = false;
    for (; iter < max_iterations; ++iter) {
        // Sort simplex by objective value, best first.
        std::vector<size_t> order(n + 1);
        for (size_t i = 0; i <= n; ++i) order[i] = i;
        std::sort(order.begin(), order.end(),
                  [&](size_t a, size_t b) { return fvals[a] < fvals[b]; });

        std::vector<Vec> sorted_simplex(n + 1);
        std::vector<double> sorted_fvals(n + 1);
        for (size_t i = 0; i <= n; ++i) {
            sorted_simplex[i] = simplex[order[i]];
            sorted_fvals[i] = fvals[order[i]];
        }
        simplex = sorted_simplex;
        fvals = sorted_fvals;

        // Convergence: spread between best and worst objective value is tiny.
        if (std::fabs(fvals[n] - fvals[0]) < tolerance) {
            converged = true;
            break;
        }

        Vec centroid = centroid_excluding_worst(simplex, n);  // worst is last (index n)

        // Reflection
        Vec reflected = add(centroid, add(centroid, simplex[n], -1.0), alpha);
        double f_reflected = objective(reflected);

        if (f_reflected < fvals[0]) {
            // Expansion
            Vec expanded = add(centroid, add(reflected, centroid, -1.0), gamma);
            double f_expanded = objective(expanded);
            if (f_expanded < f_reflected) {
                simplex[n] = expanded;
                fvals[n] = f_expanded;
            } else {
                simplex[n] = reflected;
                fvals[n] = f_reflected;
            }
        } else if (f_reflected < fvals[n - 1]) {
            simplex[n] = reflected;
            fvals[n] = f_reflected;
        } else {
            // Contraction
            Vec contracted = add(centroid, add(simplex[n], centroid, -1.0), rho);
            double f_contracted = objective(contracted);
            if (f_contracted < fvals[n]) {
                simplex[n] = contracted;
                fvals[n] = f_contracted;
            } else {
                // Shrink toward the best point.
                for (size_t i = 1; i <= n; ++i) {
                    simplex[i] = add(simplex[0], add(simplex[i], simplex[0], -1.0), sigma);
                    fvals[i] = objective(simplex[i]);
                }
            }
        }
    }

    // Final sort to report the best point found.
    size_t best = 0;
    for (size_t i = 1; i <= n; ++i) if (fvals[i] < fvals[best]) best = i;

    return NelderMeadResult{simplex[best], fvals[best], iter, converged};
}

}  // namespace quant