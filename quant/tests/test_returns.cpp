#include <gtest/gtest.h>
#include "quant/returns.hpp"
#include <cmath>

using quant::log_returns;
using quant::PriceBar;

TEST(LogReturnsTest, ComputesCorrectLogReturn) {
    std::vector<PriceBar> bars;
    bars.push_back(PriceBar{"2026-01-01", 0,0,0, 100.0, 100.0, 0});
    bars.push_back(PriceBar{"2026-01-02", 0,0,0, 110.0, 110.0, 0});

    auto r = log_returns(bars);
    ASSERT_EQ(r.size(), 1u);
    EXPECT_NEAR(r[0], std::log(110.0 / 100.0), 1e-12);
}

TEST(LogReturnsTest, EmptyOrSingleBarReturnsEmpty) {
    std::vector<PriceBar> one_bar = {PriceBar{"2026-01-01", 0,0,0,100.0,100.0,0}};
    EXPECT_TRUE(log_returns({}).empty());
    EXPECT_TRUE(log_returns(one_bar).empty());
}

TEST(LogReturnsTest, ThreeBarsGiveTwoReturns) {
    std::vector<PriceBar> bars = {
        PriceBar{"2026-01-01", 0,0,0,100.0,100.0,0},
        PriceBar{"2026-01-02", 0,0,0,105.0,105.0,0},
        PriceBar{"2026-01-03", 0,0,0,100.0,100.0,0},
    };
    auto r = log_returns(bars);
    ASSERT_EQ(r.size(), 2u);
    EXPECT_NEAR(r[0], std::log(105.0/100.0), 1e-12);
    EXPECT_NEAR(r[1], std::log(100.0/105.0), 1e-12);
}

TEST(LogReturnsTest, SkipsNonPositiveClose) {
    std::vector<PriceBar> bars = {
        PriceBar{"2026-01-01", 0,0,0,100.0,100.0,0},
        PriceBar{"2026-01-02", 0,0,0,0.0,0.0,0},   // bad row
        PriceBar{"2026-01-03", 0,0,0,105.0,105.0,0},
    };
    auto r = log_returns(bars);
    // (day1->day2) skipped because day2.close==0; (day2->day3) also skipped for the
    // same reason. Only a genuinely clean consecutive pair would produce a value.
    EXPECT_TRUE(r.empty());
}