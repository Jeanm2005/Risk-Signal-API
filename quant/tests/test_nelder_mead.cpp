#include <gtest/gtest.h>
#include "quant/nelder_mead.hpp"
#include <cmath>

using quant::nelder_mead;

TEST(NelderMeadTest, MinimizesSimpleQuadratic) {
    // f(x, y) = (x-3)^2 + (y+2)^2, minimum at (3, -2), value 0.
    auto f = [](const std::vector<double>& x) {
        return (x[0] - 3.0) * (x[0] - 3.0) + (x[1] + 2.0) * (x[1] + 2.0);
    };
    auto result = nelder_mead(f, {0.0, 0.0});
    EXPECT_TRUE(result.converged);
    EXPECT_NEAR(result.x[0], 3.0, 1e-3);
    EXPECT_NEAR(result.x[1], -2.0, 1e-3);
    EXPECT_NEAR(result.value, 0.0, 1e-4);
}

TEST(NelderMeadTest, MinimizesRosenbrock) {
    // The classic hard test case: f(x,y) = (1-x)^2 + 100(y-x^2)^2, min at (1,1), value 0.
    // Curved, narrow valley -- a much harder landscape than a quadratic bowl.
    auto f = [](const std::vector<double>& x) {
        double a = 1.0 - x[0];
        double b = x[1] - x[0] * x[0];
        return a * a + 100.0 * b * b;
    };
    auto result = nelder_mead(f, {-1.2, 1.0}, 5000);
    EXPECT_NEAR(result.x[0], 1.0, 1e-2);
    EXPECT_NEAR(result.x[1], 1.0, 1e-2);
}

TEST(NelderMeadTest, StartingAtTheMinimumStaysThere) {
    auto f = [](const std::vector<double>& x) { return x[0]*x[0] + x[1]*x[1]; };
    auto result = nelder_mead(f, {0.0, 0.0});
    EXPECT_NEAR(result.value, 0.0, 1e-6);
}