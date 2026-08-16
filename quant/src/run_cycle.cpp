// Runs the full judge cycle against REAL data: calibrates the volatility-regime
// strategy on an initial window, backtests it forward, and reports basic
// statistics plus the Probabilistic Sharpe Ratio against a zero benchmark
// ("is this distinguishable from having no edge at all").
//
// This is deliberately a thin, throwaway CLI, not part of the tested library --
// its job is to give you one real number from real data, not to be itself
// rigorously correct in every edge case the way quant_core is required to be.
//
// Usage:
//   quant_run_cycle <csv_path> <ticker> <calibration_end_date> <backtest_end_date>
// Example:
//   quant_run_cycle ../sample_prices.csv AAPL 2025-01-01 2026-07-01
#include "quant/price_history.hpp"
#include "quant/volatility_regime_strategy.hpp"
#include "quant/backtest.hpp"
#include "quant/stats.hpp"

#include <iostream>
#include <iomanip>

using namespace quant;

int main(int argc, char** argv) {
    if (argc != 5) {
        std::cerr << "Usage: " << argv[0]
                  << " <csv_path> <ticker> <calibration_end_date> <backtest_end_date>\n";
        return 1;
    }
    std::string csv_path = argv[1];
    std::string ticker = argv[2];
    std::string calibration_end = argv[3];
    std::string backtest_end = argv[4];

    try {
        std::cout << "Loading " << csv_path << " ...\n";
        auto history = PriceHistory::load_csv(csv_path);
        std::cout << "  " << ticker << ": " << history.bar_count(ticker) << " bars total\n\n";

        std::cout << "Calibrating volatility-regime strategy on data through "
                  << calibration_end << " ...\n";
        auto strategy = build_volatility_regime_strategy(history, ticker, calibration_end);

        auto implied_var = [&](size_t k) {
            double denom = 1.0 - strategy.params.alpha[k] - strategy.params.beta[k];
            return (denom > 1e-6) ? strategy.params.omega[k] / denom : strategy.params.omega[k];
        };
        std::cout << "  regime 0: implied daily vol = "
                  << std::sqrt(implied_var(0)) * 100 << "%"
                  << (strategy.turbulent_regime_index == 0 ? "  [turbulent]" : "  [calm]") << "\n";
        std::cout << "  regime 1: implied daily vol = "
                  << std::sqrt(implied_var(1)) * 100 << "%"
                  << (strategy.turbulent_regime_index == 1 ? "  [turbulent]" : "  [calm]") << "\n\n";

        std::cout << "Backtesting from " << calibration_end << " to " << backtest_end << " ...\n";
        auto rule = strategy.as_rule();
        auto result = run_backtest(history, ticker, rule, calibration_end, backtest_end);

        if (result.net_returns.size() < 2) {
            std::cout << "Not enough data in the backtest window to report statistics.\n";
            return 1;
        }

        double m = mean(result.net_returns);
        double sd = stddev(result.net_returns);
        double sr = sharpe_ratio(result.net_returns);
        double psr = probabilistic_sharpe_ratio(result.net_returns, 0.0);

        std::cout << std::fixed << std::setprecision(6);
        std::cout << "\n--- Backtest result: " << ticker << " ---\n";
        std::cout << "  trading days:          " << result.net_returns.size() << "\n";
        std::cout << "  position changes:      " << result.n_position_changes << "\n";
        std::cout << "  total transaction cost:" << result.total_cost << "\n";
        std::cout << "  mean daily net return: " << m << "\n";
        std::cout << "  daily stddev:          " << sd << "\n";
        std::cout << "  daily Sharpe ratio:    " << sr << "\n";
        std::cout << "  annualized Sharpe:     " << sr * std::sqrt(252.0) << "\n";
        std::cout << "\n  PSR (vs. zero benchmark): " << psr << "\n";
        std::cout << "  -> the probability that this strategy's TRUE Sharpe ratio\n";
        std::cout << "     exceeds zero, given the observed data and its non-normality.\n";
        std::cout << "     This is NOT yet the Deflated Sharpe Ratio: DSR additionally\n";
        std::cout << "     corrects for how many strategy variants were tried before\n";
        std::cout << "     this one, which this single run does not account for.\n";

    } catch (const std::exception& e) {
        std::cerr << "error: " << e.what() << "\n";
        return 1;
    }

    return 0;
}