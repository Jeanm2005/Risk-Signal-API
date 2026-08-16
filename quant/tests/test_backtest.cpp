#include <gtest/gtest.h>
#include "quant/backtest.hpp"
#include "quant/price_history.hpp"

#include <fstream>
#include <cstdio>
#include <cmath>

using namespace quant;

namespace {

std::string write_fixture() {
    std::string path = "backtest_fixture.csv";
    std::ofstream f(path);
    f << "ticker,date,open,high,low,close,adj_close,volume\n";
    // Clean, deterministic price path: AAA doubles then halves, five bars.
    f << "AAA,2026-01-01,100,100,100,100,100,1000\n";
    f << "AAA,2026-01-02,100,100,100,110,110,1000\n";
    f << "AAA,2026-01-03,100,100,100,121,121,1000\n";
    f << "AAA,2026-01-04,100,100,100,100,100,1000\n";
    f << "AAA,2026-01-05,100,100,100,90,90,1000\n";
    return path;
}

class BacktestTest : public ::testing::Test {
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

TEST_F(BacktestTest, FlatRuleEarnsNothingAndPaysNoCost) {
    StrategyRule always_flat = [](const PriceHistory::View&, const std::string&) { return 0.0; };
    auto result = run_backtest(history_, "AAA", always_flat, "2026-01-01", "2026-01-05");

    ASSERT_FALSE(result.net_returns.empty());
    for (double r : result.net_returns) EXPECT_NEAR(r, 0.0, 1e-12);
    EXPECT_NEAR(result.total_cost, 0.0, 1e-12);
    EXPECT_EQ(result.n_position_changes, 0);  // never moves off 0, so never "changes"
}

TEST_F(BacktestTest, AlwaysLongWithZeroCostMatchesRawLogReturn) {
    StrategyRule always_long = [](const PriceHistory::View&, const std::string&) { return 1.0; };
    TransactionCostModel free{0.0};
    auto result = run_backtest(history_, "AAA", always_long, "2026-01-01", "2026-01-05", free);

    // 01-01->01-02: ln(110/100); 01-02->01-03: ln(121/110); etc.
    ASSERT_EQ(result.net_returns.size(), 4u);
    EXPECT_NEAR(result.net_returns[0], std::log(110.0 / 100.0), 1e-10);
    EXPECT_NEAR(result.net_returns[1], std::log(121.0 / 110.0), 1e-10);
    EXPECT_NEAR(result.net_returns[2], std::log(100.0 / 121.0), 1e-10);
    EXPECT_NEAR(result.net_returns[3], std::log(90.0 / 100.0), 1e-10);
    EXPECT_NEAR(result.total_cost, 0.0, 1e-12);
}

TEST_F(BacktestTest, OpeningAPositionChargesTheConfiguredCost) {
    // Flat, then long once, then flat again -- two position changes: 0->1, 1->0.
    int call_count = 0;
    StrategyRule flip_once = [&](const PriceHistory::View&, const std::string&) -> Position {
        ++call_count;
        return (call_count == 2) ? 1.0 : 0.0;  // long only on the second decision
    };
    TransactionCostModel costs{10.0};  // 10 bps = 0.001 per unit turnover
    auto result = run_backtest(history_, "AAA", flip_once, "2026-01-01", "2026-01-05", costs);

    ASSERT_EQ(result.n_position_changes, 2);  // 0->1 and 1->0
    // Each full unit turnover costs 10bps = 0.001; two such moves total.
    EXPECT_NEAR(result.total_cost, 0.002, 1e-9);
}

// The core adversarial case, same spirit as the point-in-time price store tests:
// prove the rule can never see the return it is about to be exposed to. The rule
// here records the LAST date visible to it on each call; if the backtester leaked
// tomorrow's bar into the view, the last visible date would equal the return date
// instead of the prior day.
TEST_F(BacktestTest, RuleNeverSeesTheBarWhoseReturnItWillEarn) {
    std::vector<std::string> visible_last_dates;
    StrategyRule spy = [&](const PriceHistory::View& v, const std::string& ticker) -> Position {
        auto bars = v.bars(ticker);
        visible_last_dates.push_back(bars.empty() ? "" : bars.back().date);
        return 1.0;  // always long; behavior isn't the point, visibility is
    };
    auto result = run_backtest(history_, "AAA", spy, "2026-01-01", "2026-01-05");

    ASSERT_EQ(visible_last_dates.size(), result.days.size());
    for (size_t i = 0; i < result.days.size(); ++i) {
        // result.days[i].date is the date whose return was just earned (the
        // "tomorrow" bar). The rule's last-visible date must be STRICTLY BEFORE
        // that -- i.e. the bar immediately prior, never the bar itself.
        EXPECT_LT(visible_last_dates[i], result.days[i].date)
            << "leak: rule could see the bar dated " << visible_last_dates[i]
            << " while deciding the position that earns the return dated "
            << result.days[i].date;
    }
}

TEST_F(BacktestTest, ShortPositionEarnsTheNegativeOfTheMove) {
    StrategyRule always_short = [](const PriceHistory::View&, const std::string&) { return -1.0; };
    TransactionCostModel free{0.0};
    auto result = run_backtest(history_, "AAA", always_short, "2026-01-01", "2026-01-05", free);

    ASSERT_EQ(result.net_returns.size(), 4u);
    EXPECT_NEAR(result.net_returns[0], -std::log(110.0 / 100.0), 1e-10);
}

TEST_F(BacktestTest, EmptyOrTooShortHistoryReturnsEmptyResult) {
    StrategyRule any_rule = [](const PriceHistory::View&, const std::string&) { return 1.0; };
    auto result = run_backtest(history_, "ZZZ_UNKNOWN", any_rule, "2026-01-01", "2026-01-05");
    EXPECT_TRUE(result.net_returns.empty());
}

TEST_F(BacktestTest, StartDateAfterAllDataReturnsEmptyResult) {
    StrategyRule any_rule = [](const PriceHistory::View&, const std::string&) { return 1.0; };
    auto result = run_backtest(history_, "AAA", any_rule, "2099-01-01", "2099-12-31");
    EXPECT_TRUE(result.net_returns.empty());
}