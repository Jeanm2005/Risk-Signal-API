#include "quant/price_history.hpp"
#include "quant/volatility_regime_strategy.hpp"
#include "quant/backtest.hpp"
#include "quant/stats.hpp"
#include <iostream>
#include <iomanip>
#include <vector>

using namespace quant;

int main(int argc, char** argv) {
    if (argc != 5) {
        std::cerr << "Usage: " << argv[0]
                  << "<csv_path> <ticker> <calibration_end_date> <backtest_end_date>\n";
        return 1;
    }
    std::string csv_path = argv[1];
    std::string ticker = argv[2];
    std::string calibration_end = argv[3];
    std::string backtest_end = argv[4];

    try {
        std::cout << "Loading " << csv_path << "...\n";
        auto history = PriceHistory::load_csv(csv_path);
        std::cout << " " << ticker << ": " << history.bar_count(ticker) << " bars total\n\n";

        std::cout << "Calibrating ONE volatility model on data through " << calibration_end
                  << "\n(shared across every trial below -- only the turbulence threshold\n"
                  << "differs per trial, so threshold choice is the only thing being tested) ...\n";
        auto base_strategy = build_volatility_regime_strategy(history, ticker, calibration_end);

        std::vector<double> thresholds = {0.3, 0.4, 0.5, 0.6, 0.7};
        std::vector<double> trial_sharpes;
        std::vector<std::vector<double>> trial_returns_list;
        std::vector<double> trial_thresholds;

        std::cout << "\n--- " << thresholds.size() << " trials (this IS the honest trial count "
                  << "the DSR below is computed against) ---\n";
        for (double th : thresholds) {
            VolatilityRegimeStrategy variant = base_strategy;
            variant.turbulence_threshold = th;
            auto rule = variant.as_rule();
            auto result = run_backtest(history, ticker, rule, calibration_end, backtest_end);

            if (result.net_returns.size() < 2) {
                std::cout << "  threshold=" << th << ": not enough backtest data, skipping\n";
                continue;
            }
            double sr = sharpe_ratio(result.net_returns);
            trial_sharpes.push_back(sr);
            trial_returns_list.push_back(result.net_returns);
            trial_thresholds.push_back(th);

            std::cout << std::fixed << std::setprecision(2)
                      << "  threshold=" << th << std::setprecision(6)
                      << "  daily Sharpe=" << sr
                      << "  annualized=" << sr * std::sqrt(252.0)
                      << "  position changes=" << result.n_position_changes << "\n";
        }

        if (trial_sharpes.empty()) {
            std::cout << "\nNo trial produced enough data to evaluate.\n";
            return 1;
        }
 
        size_t best_idx = 0;
            for (size_t i = 1; i < trial_sharpes.size(); ++i) {
                if (trial_sharpes[i] > trial_sharpes[best_idx]) best_idx = i;
            }
 
        std::cout << "\n--- Best trial: threshold=" << trial_thresholds[best_idx]
                  << "  daily Sharpe=" << trial_sharpes[best_idx] << " ---\n";
 
        double psr_naive = probabilistic_sharpe_ratio(trial_returns_list[best_idx], 0.0);
        double dsr_honest = deflated_sharpe_ratio(trial_returns_list[best_idx], trial_sharpes);
 
        std::cout << std::fixed << std::setprecision(6);
        std::cout << "\nPSR if this were the ONLY threshold ever tried:  " << psr_naive << "\n";
        std::cout << "DSR, honestly accounting for all " << trial_sharpes.size()
                  << " thresholds tried:  " << dsr_honest << "\n";
 
        if (dsr_honest < psr_naive) {
            std::cout << "\nDSR is lower than the naive PSR, as it should be: picking the best\n"
                      << "of " << trial_sharpes.size() << " tried variants and reporting only that one's\n"
                      << "performance makes it look more credible than it really is. DSR is the\n"
                      << "correction for exactly that temptation.\n";
        } else {
            std::cout << "\nDSR is not lower than the naive PSR here -- with only "
                      << trial_sharpes.size() << " trials and this much spread\n"
                      << "in their Sharpe ratios, the multiple-testing correction is small. This can\n"
                      << "happen honestly; it does not mean the correction failed.\n";
        }
 
    } catch (const std::exception& e) {
        std::cerr << "error: " << e.what() << "\n";
        return 1;
    }
 
    return 0;
}