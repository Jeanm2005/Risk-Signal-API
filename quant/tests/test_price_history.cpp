// Point-in-time correctness tests for PriceHistory / PriceHistory::View.
//
// The property under test is the one that matters most in this whole module: a View
// bound to an as-of date must NEVER expose a bar dated after that cutoff, under any
// input shape -- out-of-order rows, a cutoff date with no exact bar, a ticker with no
// data, a lookback longer than history, a cutoff before all data, a cutoff after all
// data. Each case here is an attempt to leak a future bar through the View. All of
// them must fail to leak.
#include <gtest/gtest.h>
#include "quant/price_history.hpp"

#include <fstream>
#include <cstdio>

using quant::PriceHistory;
using quant::PriceBar;

namespace {

// Writes a small CSV fixture and returns its path. Rows are deliberately NOT sorted
// by date, to prove load_csv's sort step is what makes the View's binary search valid.
std::string write_fixture() {
    std::string path = "pit_test_fixture.csv";
    std::ofstream f(path);
    f << "ticker,date,open,high,low,close,adj_close,volume\n";
    // AAA: five bars, intentionally out of order in the file.
    f << "AAA,2026-01-03,10,11,9,10.5,10.5,1000\n";
    f << "AAA,2026-01-01,10,11,9,10.0,10.0,1000\n";
    f << "AAA,2026-01-05,10,11,9,11.0,11.0,1000\n";
    f << "AAA,2026-01-02,10,11,9,10.2,10.2,1000\n";
    f << "AAA,2026-01-04,10,11,9,10.8,10.8,1000\n";
    // BBB: single bar, used for the "ticker exists but sparse" case.
    f << "BBB,2026-01-03,5,5,5,5,5,500\n";
    return path;
}

class PointInTimeTest : public ::testing::Test {
protected:
    void SetUp() override {
        path_ = write_fixture();
        history_ = PriceHistory::load_csv(path_);
    }
    void TearDown() override { std::remove(path_.c_str()); }

    std::string path_;
    PriceHistory history_;
};

}  // namespace

TEST_F(PointInTimeTest, LoadsAllRows) {
    EXPECT_EQ(history_.bar_count("AAA"), 5u);
    EXPECT_EQ(history_.bar_count("BBB"), 1u);
}

TEST_F(PointInTimeTest, SortsOutOfOrderRowsByDate) {
    auto bars = history_.as_of("2026-01-05").bars("AAA");
    ASSERT_EQ(bars.size(), 5u);
    for (size_t i = 1; i < bars.size(); ++i) {
        EXPECT_LT(bars[i - 1].date, bars[i].date) << "bars must be strictly ascending by date";
    }
}

// The core adversarial case: as-of a middle date, confirm NOTHING after it leaks.
TEST_F(PointInTimeTest, NeverReturnsABarAfterTheCutoff) {
    auto view = history_.as_of("2026-01-03");
    auto bars = view.bars("AAA");
    ASSERT_EQ(bars.size(), 3u);  // 01-01, 01-02, 01-03 only
    for (const auto& b : bars) {
        EXPECT_LE(b.date, "2026-01-03") << "leaked a future bar: " << b.date;
    }
    // Explicitly assert the two future bars are absent, not just that the count is right --
    // a wrong-but-same-size result would pass a count-only check.
    for (const auto& b : bars) {
        EXPECT_NE(b.date, "2026-01-04");
        EXPECT_NE(b.date, "2026-01-05");
    }
}

// A cutoff date with no exact bar on it (e.g. a weekend) must still only see the past.
TEST_F(PointInTimeTest, CutoffBetweenBarsSeesOnlyStrictlyPastData) {
    auto bars = history_.as_of("2026-01-03T12:00:00").bars("AAA");
    // ISO date-time > ISO date lexicographically, so this should behave like as_of
    // "2026-01-03" or later -- exercising that the comparison is purely lexicographic
    // and doesn't require an exact match to work correctly.
    for (const auto& b : bars) {
        EXPECT_LE(b.date, "2026-01-03T12:00:00");
    }
}

TEST_F(PointInTimeTest, CutoffBeforeAllDataReturnsNothing) {
    auto bars = history_.as_of("2025-12-31").bars("AAA");
    EXPECT_TRUE(bars.empty());
}

TEST_F(PointInTimeTest, CutoffAfterAllDataReturnsEverything) {
    auto bars = history_.as_of("2099-01-01").bars("AAA");
    EXPECT_EQ(bars.size(), 5u);
}

TEST_F(PointInTimeTest, UnknownTickerReturnsEmptyNotError) {
    auto bars = history_.as_of("2026-01-05").bars("ZZZ");
    EXPECT_TRUE(bars.empty());
}

// Lookback must be point-in-time-safe too -- it's built on top of bars(), but tested
// independently because it's a separate code path and a separate opportunity to leak.
TEST_F(PointInTimeTest, LookbackNeverCrossesTheCutoff) {
    auto lb = history_.as_of("2026-01-03").lookback("AAA", 2);
    ASSERT_EQ(lb.size(), 2u);
    EXPECT_EQ(lb[0].date, "2026-01-02");
    EXPECT_EQ(lb[1].date, "2026-01-03");
    for (const auto& b : lb) EXPECT_LE(b.date, "2026-01-03");
}

TEST_F(PointInTimeTest, LookbackLongerThanHistoryReturnsWhatExistsNotPadded) {
    auto lb = history_.as_of("2026-01-02").lookback("AAA", 10);
    EXPECT_EQ(lb.size(), 2u);  // only 01-01 and 01-02 exist at or before this cutoff
}

TEST_F(PointInTimeTest, LookbackZeroReturnsEmpty) {
    auto lb = history_.as_of("2026-01-05").lookback("AAA", 0);
    EXPECT_TRUE(lb.empty());
}

TEST_F(PointInTimeTest, SparseTickerRespectsCutoff) {
    EXPECT_EQ(history_.as_of("2026-01-02").bars("BBB").size(), 0u);
    EXPECT_EQ(history_.as_of("2026-01-03").bars("BBB").size(), 1u);
}