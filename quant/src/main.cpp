#include "quant/price_history.hpp"
#include <iostream>

int main() {
    auto history = quant::PriceHistory::load_csv("sample_prices.csv");
    for (const auto& t : history.tickers()) {
        std::cout << t << ": " << history.bar_count(t) << " bars\n";
    }
    return 0;
}