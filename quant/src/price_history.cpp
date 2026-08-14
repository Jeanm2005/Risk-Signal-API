#include "quant/price_history.hpp"

#include <algorithm>
#include <fstream>
#include <sstream>
#include <stdexcept>

namespace quant {

namespace {

std::vector<std::string> split_csv_line(const std::string& line) {
    std::vector<std::string> fields;
    std::stringstream ss(line);
    std::string field;
    while (std::getline(ss, field, ',')) {
        fields.push_back(field);
    }
    return fields;
}

}  // namespace

PriceHistory PriceHistory::load_csv(const std::string& path) {
    std::ifstream file(path);
    if (!file.is_open()) {
        throw std::runtime_error("PriceHistory::load_csv: could not open " + path);
    }

    PriceHistory history;
    std::string line;
    bool first = true;
    while (std::getline(file, line)) {
        if (first) {  // skip header
            first = false;
            continue;
        }
        if (line.empty()) continue;

        auto f = split_csv_line(line);
        if (f.size() < 8) {
            throw std::runtime_error("PriceHistory::load_csv: malformed row: " + line);
        }

        PriceBar bar;
        const std::string& ticker = f[0];
        bar.date = f[1];
        bar.open = std::stod(f[2]);
        bar.high = std::stod(f[3]);
        bar.low = std::stod(f[4]);
        bar.close = std::stod(f[5]);
        bar.adj_close = std::stod(f[6]);
        bar.volume = std::stoll(f[7]);

        history.data_[ticker].push_back(std::move(bar));
    }

    // Sort each ticker's bars by date so downstream binary search / lookback works,
    // and so the CSV need not arrive pre-sorted.
    for (auto& [ticker, bars] : history.data_) {
        std::sort(bars.begin(), bars.end(),
                  [](const PriceBar& a, const PriceBar& b) { return a.date < b.date; });
    }

    return history;
}

std::vector<std::string> PriceHistory::tickers() const {
    std::vector<std::string> out;
    out.reserve(data_.size());
    for (const auto& [ticker, _] : data_) out.push_back(ticker);
    return out;
}

size_t PriceHistory::bar_count(const std::string& ticker) const {
    auto it = data_.find(ticker);
    return it == data_.end() ? 0 : it->second.size();
}

PriceHistory::View PriceHistory::as_of(const std::string& as_of_date) const {
    return View(*this, as_of_date);
}

PriceHistory::View::View(const PriceHistory& owner, std::string as_of_date)
    : owner_(owner), as_of_date_(std::move(as_of_date)) {}

std::vector<PriceBar> PriceHistory::View::bars(const std::string& ticker) const {
    auto it = owner_.data_.find(ticker);
    if (it == owner_.data_.end()) return {};

    const auto& all = it->second;
    // upper_bound on the (sorted) date: first bar strictly AFTER as_of_date_.
    // Everything before that iterator has date <= as_of_date_, which is exactly the
    // point-in-time-safe slice. Bars from date > as_of_date_ are never touched.
    auto cutoff = std::upper_bound(
        all.begin(), all.end(), as_of_date_,
        [](const std::string& date, const PriceBar& bar) { return date < bar.date; });

    return std::vector<PriceBar>(all.begin(), cutoff);
}

std::vector<PriceBar> PriceHistory::View::lookback(const std::string& ticker, size_t n) const {
    auto visible = bars(ticker);  // already point-in-time-safe
    if (visible.size() <= n) return visible;
    return std::vector<PriceBar>(visible.end() - static_cast<long>(n), visible.end());
}

}  // namespace quant