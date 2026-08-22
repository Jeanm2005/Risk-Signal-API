#include "quant/news_features.hpp"

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

NewsFeatureHistory NewsFeatureHistory::load_csv(const std::string& path) {
    std::ifstream file(path);
    if (!file.is_open()) {
        throw std::runtime_error("NewsFeatureHistory::load_csv: could not open " + path);
    }

    NewsFeatureHistory history;
    std::string line;
    bool first = true;
    while (std::getline(file, line)) {
        if (first) {
            first = false;
            continue;
        }
        if (line.empty()) continue;

        auto f = split_csv_line(line);
        if (f.size() < 5) {
            throw std::runtime_error("NewsFeatureHistory::load_csv: malformed row: " + line);
        }

        NewsFeatureBar bar;
        const std::string& ticker = f[0];
        bar.date = f[1];
        bar.news_n = std::stoi(f[2]);
        bar.news_neg = std::stod(f[3]);
        bar.neg_ratio = std::stod(f[4]);

        history.data_[ticker].push_back(std::move(bar));
    }

    for (auto& [ticker, bars] : history.data_) {
        std::sort(bars.begin(), bars.end(),
                  [](const NewsFeatureBar& a, const NewsFeatureBar& b) { return a.date < b.date; });
    }

    return history;
}

std::vector<std::string> NewsFeatureHistory::tickers() const {
    std::vector<std::string> out;
    out.reserve(data_.size());
    for (const auto& [ticker, _] : data_) out.push_back(ticker);
    return out;
}

size_t NewsFeatureHistory::bar_count(const std::string& ticker) const {
    auto it = data_.find(ticker);
    return it == data_.end() ? 0 : it->second.size();
}

NewsFeatureHistory::View NewsFeatureHistory::as_of(const std::string& as_of_date) const {
    return View(*this, as_of_date);
}

NewsFeatureHistory::View::View(const NewsFeatureHistory& owner, std::string as_of_date)
    : owner_(owner), as_of_date_(std::move(as_of_date)) {}

std::vector<NewsFeatureBar> NewsFeatureHistory::View::bars(const std::string& ticker) const {
    auto it = owner_.data_.find(ticker);
    if (it == owner_.data_.end()) return {};

    const auto& all = it->second;
    auto cutoff = std::upper_bound(
        all.begin(), all.end(), as_of_date_,
        [](const std::string& date, const NewsFeatureBar& bar) { return date < bar.date; });

    return std::vector<NewsFeatureBar>(all.begin(), cutoff);
}

std::vector<NewsFeatureBar> NewsFeatureHistory::View::lookback(const std::string& ticker,
                                                               size_t n) const {
    auto visible = bars(ticker);
    if (visible.size() <= n) return visible;
    return std::vector<NewsFeatureBar>(visible.end() - static_cast<long>(n), visible.end());
}

}  // namespace quant