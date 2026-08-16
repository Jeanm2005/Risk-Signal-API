#include <gtest/gtest.h>
#include "quant/stats.hpp"
#include <cmath>

using namespace quant;

TEST(StatsTest, MeanAndStddevOnSimpleData) {
    std::vector<double> x = {1.0, 2.0, 3.0, 4.0, 5.0};
    EXPECT_NEAR(mean(x), 3.0, 1e-12);
    // population stddev of {1,2,3,4,5}: variance = 2, stddev = sqrt(2)
    EXPECT_NEAR(stddev(x), std::sqrt(2.0), 1e-12);
}

TEST(StatsTest, SharpeRatioOfConstantSeriesIsZeroNotCrash) {
    std::vector<double> x = {0.01, 0.01, 0.01, 0.01};  // zero variance
    EXPECT_NEAR(sharpe_ratio(x), 0.0, 1e-12);
}

TEST(StatsTest, SharpeRatioMatchesHandComputation) {
    std::vector<double> x = {0.02, -0.01, 0.03, 0.01, -0.02};
    double expected = mean(x) / stddev(x);
    EXPECT_NEAR(sharpe_ratio(x), expected, 1e-12);
}

TEST(StatsTest, SkewnessOfSymmetricDataIsNearZero) {
    std::vector<double> x = {-2.0, -1.0, 0.0, 1.0, 2.0};  // perfectly symmetric
    EXPECT_NEAR(skewness(x), 0.0, 1e-10);
}

TEST(StatsTest, NormalCdfKnownValues) {
    EXPECT_NEAR(normal_cdf(0.0), 0.5, 1e-9);        // median of standard normal
    EXPECT_GT(normal_cdf(1.0), 0.84);               // ~0.8413
    EXPECT_LT(normal_cdf(1.0), 0.85);
    EXPECT_NEAR(normal_cdf(-5.0), 0.0, 1e-6);        // far left tail ~0
    EXPECT_NEAR(normal_cdf(5.0), 1.0, 1e-6);         // far right tail ~1
}

// The key structural invariant: when the observed Sharpe ratio exactly equals the
// benchmark, the PSR test statistic's numerator is exactly zero regardless of
// sample size, skew, or kurtosis -- so PSR must be exactly 0.5. This is derivable
// directly from the formula, independent of any specific data, which makes it a
// strong test: it isn't checking against a number I picked, it's checking a
// property the formula is mathematically required to have.
TEST(StatsTest, PsrIsExactlyHalfWhenObservedEqualsBenchmark) {
    std::vector<double> returns = {0.01, -0.02, 0.015, -0.005, 0.02, -0.01, 0.008};
    double sr_hat = sharpe_ratio(returns);
    double psr = probabilistic_sharpe_ratio(returns, sr_hat);  // benchmark == observed
    EXPECT_NEAR(psr, 0.5, 1e-9);
}

TEST(StatsTest, PsrIncreasesAsBenchmarkDecreases) {
    std::vector<double> returns = {0.01, -0.02, 0.015, -0.005, 0.02, -0.01, 0.008, 0.012};
    double sr_hat = sharpe_ratio(returns);
    double psr_low_bar = probabilistic_sharpe_ratio(returns, sr_hat - 0.5);
    double psr_high_bar = probabilistic_sharpe_ratio(returns, sr_hat + 0.5);
    // Clearing a lower bar should be more probable than clearing a higher one.
    EXPECT_GT(psr_low_bar, 0.5);
    EXPECT_LT(psr_high_bar, 0.5);
    EXPECT_GT(psr_low_bar, psr_high_bar);
}

TEST(StatsTest, PsrIsBoundedBetweenZeroAndOne) {
    std::vector<double> returns = {0.05, -0.03, 0.04, 0.06, -0.01, 0.02, 0.03, -0.02, 0.01};
    for (double benchmark : {-2.0, -0.5, 0.0, 0.5, 2.0}) {
        double psr = probabilistic_sharpe_ratio(returns, benchmark);
        EXPECT_GE(psr, 0.0);
        EXPECT_LE(psr, 1.0);
    }
}

TEST(StatsTest, TooFewObservationsThrows) {
    std::vector<double> one_point = {0.01};
    EXPECT_THROW(probabilistic_sharpe_ratio(one_point, 0.0), std::invalid_argument);
}