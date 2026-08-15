#pragma once
#include <vector>
#include <functional>

namespace quant {

    /// Minimizes a function using the Nelder-Mead simplex method. Derivative-free,
    /// which matters here: the MS-GARCH log-likelihood surface (built from a filter
    /// recursion) has no clean closed-form gradient, so a gradient-based optimizer
    /// isn't a natural fit. Nelder-Mead only needs function evaluations.
    ///
    /// `objective` should return the value to MINIMIZE (for maximum likelihood, pass
    /// the NEGATIVE log-likelihood).
    struct NelderMeadResult {
        std::vector<double> x; // the parameter vector found
        double value;          // objective(x)
        int iterations;
        bool converged;        // true if it stopped by the tolerance, not the cap
    };

    NelderMeadResult nelder_mead(
        const std::function<double(const std::vector<double>&)>& objective,
        std::vector<double> initial_guess,
        int max_iterations = 2000,
        double tolerance = 1e-8
    );

} // namespace quant