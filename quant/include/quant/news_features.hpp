#pragma once
#include <string>
#include <vector>
#include <unordered_map>

namespace quant {
    struct NewsFeatureBar {
        std::string date;
        int news_n{};
        double news_neg{};
        double neg_ratio{};
    };

    class NewsFeatureHistory {
        public:
            static NewsFeatureHistory load_csv(const std::string& path);
            std::vector<std::string> tickers() const;
            size_t bar_count(const std::string& ticker) const;

            class View;
            View as_of(const std::string& as_of_date) const;

        private:
            friend class View;
            std::unordered_map<std::string, std::vector<NewsFeatureBar>> data_;
    };

    class NewsFeatureHistory::View {
        public:
            std::vector<NewsFeatureBar> bars(const std::string& ticker) const;
            std::vector<NewsFeatureBar> lookback(const std::string& ticker, size_t n) const;
            const std::string& as_of_date() const { return as_of_date_; }

        private:
            friend class NewsFeatureHistory;
            View(const NewsFeatureHistory& owner, std::string as_of_date);
            const NewsFeatureHistory& owner_;
            std::string as_of_date_;
    };
} // namespace quant