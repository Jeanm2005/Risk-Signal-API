#include <gtest/gtest.h>
#include "quant/news_features.hpp"

#include <fstream>
#include <cstdio>

using quant::NewsFeatureHistory;

namespace {

std::string write_fixture() {
    std::string path = "news_features_test_fixture.csv";
    std::ofstream f(path);
    f << "ticker,date,news_n,news_neg,neg_ratio\n";
    // AAA: five days, deliberately out of order in the file, and with a gap
    // (no row for 2026-01-04) to mirror how real data has no-news days simply
    // absent rather than present with zero values.
    f << "AAA,2026-01-03,4,0.70,0.50\n";
    f << "AAA,2026-01-01,2,0.30,0.00\n";
    f << "AAA,2026-01-05,6,0.90,0.83\n";
    f << "AAA,2026-01-02,1,0.20,0.00\n";
    // BBB: single sparse day
    f << "BBB,2026-01-03,3,0.60,0.33\n";
    return path;
}

class NewsFeaturesTest : public ::testing::Test {
protected:
    void SetUp() override {
        path_ = write_fixture();
        history_ = NewsFeatureHistory::load_csv(path_);
    }
    void TearDown() override { std::remove(path_.c_str()); }

    std::string path_;
    NewsFeatureHistory history_;
};

}  // namespace

TEST_F(NewsFeaturesTest, LoadsAllRows) {
    EXPECT_EQ(history_.bar_count("AAA"), 4u);
    EXPECT_EQ(history_.bar_count("BBB"), 1u);
}

TEST_F(NewsFeaturesTest, SortsOutOfOrderRowsByDate) {
    auto bars = history_.as_of("2026-01-05").bars("AAA");
    ASSERT_EQ(bars.size(), 4u);
    for (size_t i = 1; i < bars.size(); ++i) {
        EXPECT_LT(bars[i - 1].date, bars[i].date);
    }
}

// The same core guarantee as PriceHistory, checked independently for this bar
// type rather than assumed to transfer just because the mechanism looks similar.
TEST_F(NewsFeaturesTest, NeverReturnsABarAfterTheCutoff) {
    auto bars = history_.as_of("2026-01-03").bars("AAA");
    ASSERT_EQ(bars.size(), 3u);  // 01-01, 01-02, 01-03 (01-05 is excluded)
    for (const auto& b : bars) {
        EXPECT_LE(b.date, "2026-01-03") << "leaked a future bar: " << b.date;
    }
}

TEST_F(NewsFeaturesTest, CutoffExactlyOnABarIncludesThatBar) {
    auto bars = history_.as_of("2026-01-03").bars("AAA");
    bool found_cutoff_day = false;
    for (const auto& b : bars) if (b.date == "2026-01-03") found_cutoff_day = true;
    EXPECT_TRUE(found_cutoff_day) << "a bar dated exactly on the cutoff should be visible";
}

TEST_F(NewsFeaturesTest, AbsentDayIsSimplyMissingNotZero) {
    // 2026-01-04 has no row at all in the fixture (no news that day). Confirm the
    // gap is real: as_of("2026-01-04") should return the SAME bars as
    // as_of("2026-01-03"), since there is nothing new to include.
    auto through_03 = history_.as_of("2026-01-03").bars("AAA");
    auto through_04 = history_.as_of("2026-01-04").bars("AAA");
    EXPECT_EQ(through_03.size(), through_04.size());
}

TEST_F(NewsFeaturesTest, FeatureValuesAreReadCorrectly) {
    auto bars = history_.as_of("2026-01-01").bars("AAA");
    ASSERT_EQ(bars.size(), 1u);
    EXPECT_EQ(bars[0].news_n, 2);
    EXPECT_NEAR(bars[0].news_neg, 0.30, 1e-12);
    EXPECT_NEAR(bars[0].neg_ratio, 0.00, 1e-12);
}

TEST_F(NewsFeaturesTest, CutoffBeforeAllDataReturnsNothing) {
    auto bars = history_.as_of("2025-12-31").bars("AAA");
    EXPECT_TRUE(bars.empty());
}

TEST_F(NewsFeaturesTest, CutoffAfterAllDataReturnsEverything) {
    auto bars = history_.as_of("2099-01-01").bars("AAA");
    EXPECT_EQ(bars.size(), 4u);
}

TEST_F(NewsFeaturesTest, UnknownTickerReturnsEmptyNotError) {
    auto bars = history_.as_of("2026-01-05").bars("ZZZ");
    EXPECT_TRUE(bars.empty());
}

TEST_F(NewsFeaturesTest, LookbackNeverCrossesTheCutoff) {
    auto lb = history_.as_of("2026-01-03").lookback("AAA", 1);
    ASSERT_EQ(lb.size(), 1u);
    EXPECT_EQ(lb[0].date, "2026-01-03");
}

TEST_F(NewsFeaturesTest, SparseTickerRespectsCutoff) {
    EXPECT_EQ(history_.as_of("2026-01-02").bars("BBB").size(), 0u);
    EXPECT_EQ(history_.as_of("2026-01-03").bars("BBB").size(), 1u);
}