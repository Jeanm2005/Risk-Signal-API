#include <gtest/gtest.h>
#include "quant/stats.hpp"
#include <cmath>

using namespace quant;

TEST(StatsTest, MeanAndStddevOnSimpleData) {
    std::vector<double> x = {1.0, 2.0, 3.0, 4.0, 5.0};
    EXPECT_NEAR(mean(x), 3.0, 1e-12);
    EXPECT_NEAR(stddev(x), std::sqrt(2.0), 1e-12);
}

TEST(StatsTest, SharpeRatioOfConstantSeriesIsZeroNotCrash) {
    std::vector<double> x = {0.01, 0.01, 0.01, 0.01};
    EXPECT_NEAR(sharpe_ratio(x), 0.0, 1e-12);
}

TEST(StatsTest, SharpeRatioMatchesHandComputation) {
    std::vector<double> x = {0.02, -0.01, 0.03, 0.01, -0.02};
    double expected = mean(x) / stddev(x);
    EXPECT_NEAR(sharpe_ratio(x), expected, 1e-12);
}

TEST(StatsTest, SkewnessOfSymmetricDataIsNearZero) {
    std::vector<double> x = {-2.0, -1.0, 0.0, 1.0, 2.0};
    EXPECT_NEAR(skewness(x), 0.0, 1e-10);
}

TEST(StatsTest, NormalCdfKnownValues) {
    EXPECT_NEAR(normal_cdf(0.0), 0.5, 1e-9);
    EXPECT_GT(normal_cdf(1.0), 0.84);
    EXPECT_LT(normal_cdf(1.0), 0.85);
    EXPECT_NEAR(normal_cdf(-5.0), 0.0, 1e-6);
    EXPECT_NEAR(normal_cdf(5.0), 1.0, 1e-6);
}

TEST(StatsTest, PsrIsExactlyHalfWhenObservedEqualsBenchmark) {
    std::vector<double> returns = {0.01, -0.02, 0.015, -0.005, 0.02, -0.01, 0.008};
    double sr_hat = sharpe_ratio(returns);
    double psr = probabilistic_sharpe_ratio(returns, sr_hat);
    EXPECT_NEAR(psr, 0.5, 1e-9);
}

TEST(StatsTest, PsrIncreasesAsBenchmarkDecreases) {
    std::vector<double> returns = {0.01, -0.02, 0.015, -0.005, 0.02, -0.01, 0.008, 0.012};
    double sr_hat = sharpe_ratio(returns);
    double psr_low_bar = probabilistic_sharpe_ratio(returns, sr_hat - 0.5);
    double psr_high_bar = probabilistic_sharpe_ratio(returns, sr_hat + 0.5);
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

// --- inverse_normal_cdf: checked against well-known, independently verifiable
// standard normal quantiles -- these are not numbers I chose, they're textbook
// z-values (e.g. 1.95996 is the exact z-value behind "1.96" in every 95%
// confidence interval anyone has ever computed).
TEST(InverseNormalCdfTest, KnownQuantiles) {
    EXPECT_NEAR(inverse_normal_cdf(0.5), 0.0, 1e-6);
    EXPECT_NEAR(inverse_normal_cdf(0.975), 1.959964, 1e-5);
    EXPECT_NEAR(inverse_normal_cdf(0.995), 2.575829, 1e-5);
    EXPECT_NEAR(inverse_normal_cdf(0.90), 1.281552, 1e-5);
    EXPECT_NEAR(inverse_normal_cdf(0.025), -1.959964, 1e-5);
}

TEST(InverseNormalCdfTest, RoundTripsThroughNormalCdf) {
    // normal_cdf(inverse_normal_cdf(p)) should return p, across a spread of values
    // including the extreme tails where the rational approximation is hardest.
    for (double p : {0.001, 0.01, 0.1, 0.3, 0.5, 0.7, 0.9, 0.99, 0.999}) {
        double z = inverse_normal_cdf(p);
        EXPECT_NEAR(normal_cdf(z), p, 1e-6) << "round-trip failed for p=" << p;
    }
}

TEST(InverseNormalCdfTest, RejectsOutOfRangeInput) {
    EXPECT_THROW(inverse_normal_cdf(0.0), std::invalid_argument);
    EXPECT_THROW(inverse_normal_cdf(1.0), std::invalid_argument);
    EXPECT_THROW(inverse_normal_cdf(-0.1), std::invalid_argument);
    EXPECT_THROW(inverse_normal_cdf(1.1), std::invalid_argument);
}

// --- expected_max_sharpe ---
TEST(ExpectedMaxSharpeTest, SingleTrialReturnsZero) {
    // Documented special case: with only one trial, there is no "best of several"
    // effect to correct for.
    EXPECT_NEAR(expected_max_sharpe(1, 0.5), 0.0, 1e-12);
    EXPECT_NEAR(expected_max_sharpe(0, 0.5), 0.0, 1e-12);
}

TEST(ExpectedMaxSharpeTest, ZeroVarianceReturnsZero) {
    EXPECT_NEAR(expected_max_sharpe(50, 0.0), 0.0, 1e-12);
}

TEST(ExpectedMaxSharpeTest, IncreasesWithMoreTrials) {
    // More trials -> a higher expected max Sharpe by pure chance -> a higher
    // benchmark future strategies must clear. This monotonicity is the whole
    // point of the correction, so it's the most important property to check.
    double var = 0.3;
    double sr2 = expected_max_sharpe(2, var);
    double sr10 = expected_max_sharpe(10, var);
    double sr100 = expected_max_sharpe(100, var);
    double sr1000 = expected_max_sharpe(1000, var);
    EXPECT_LT(sr2, sr10);
    EXPECT_LT(sr10, sr100);
    EXPECT_LT(sr100, sr1000);
}

TEST(ExpectedMaxSharpeTest, ScalesWithSquareRootOfVariance) {
    // The formula is sqrt(variance) * (a fixed factor depending only on n_trials),
    // so doubling the variance should scale the result by sqrt(2), exactly.
    double sr_a = expected_max_sharpe(20, 0.25);
    double sr_b = expected_max_sharpe(20, 0.50);
    EXPECT_NEAR(sr_b / sr_a, std::sqrt(2.0), 1e-6);
}

TEST(ExpectedMaxSharpeTest, RejectsNegativeVariance) {
    EXPECT_THROW(expected_max_sharpe(10, -0.1), std::invalid_argument);
}

// --- deflated_sharpe_ratio ---
TEST(DeflatedSharpeRatioTest, WithOneTrialEqualsPlainPsrAgainstZero) {
    std::vector<double> returns = {0.01, -0.02, 0.015, -0.005, 0.02, -0.01, 0.008};
    double dsr = deflated_sharpe_ratio(returns, 1, 0.0);
    double psr = probabilistic_sharpe_ratio(returns, 0.0);
    EXPECT_NEAR(dsr, psr, 1e-9);
}

TEST(DeflatedSharpeRatioTest, IsLowerThanPlainPsrWhenManyTrialsWereTried) {
    // The central point of DSR: for the SAME return series, having tried many
    // variants first must make the result look LESS credible than testing that
    // same series against a naive zero benchmark, because more trials means a
    // higher chance of finding something that merely LOOKS good by chance.
    std::vector<double> returns = {0.01, -0.02, 0.015, -0.005, 0.02, -0.01, 0.008, 0.012};
    double psr_naive = probabilistic_sharpe_ratio(returns, 0.0);
    double dsr_many_trials = deflated_sharpe_ratio(returns, 200, 0.3);
    EXPECT_LT(dsr_many_trials, psr_naive);
}

TEST(DeflatedSharpeRatioTest, VectorOverloadMatchesManualComputation) {
    std::vector<double> returns = {0.01, -0.02, 0.015, -0.005, 0.02, -0.01, 0.008, 0.012};
    std::vector<double> trial_sharpes = {0.1, 0.3, -0.2, 0.15, 0.05, 0.25, -0.1, 0.2};

    double manual_var = stddev(trial_sharpes);
    manual_var = manual_var * manual_var;
    double expected = deflated_sharpe_ratio(returns, static_cast<int>(trial_sharpes.size()), manual_var);
    double actual = deflated_sharpe_ratio(returns, trial_sharpes);
    EXPECT_NEAR(actual, expected, 1e-12);
}

TEST(DeflatedSharpeRatioTest, IsBoundedBetweenZeroAndOne) {
    std::vector<double> returns = {0.03, -0.01, 0.02, 0.04, -0.02, 0.01, 0.025, -0.015, 0.01};
    for (int n : {1, 5, 50, 500}) {
        double dsr = deflated_sharpe_ratio(returns, n, 0.2);
        EXPECT_GE(dsr, 0.0);
        EXPECT_LE(dsr, 1.0);
    }
}