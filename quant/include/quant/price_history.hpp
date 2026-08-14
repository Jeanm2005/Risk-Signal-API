#pragma once
#include <string>
#include <vector>
#include <unordered_map>

namespace quant {

/// One daily price bar. Dates are ISO 8601 "YYYY-MM-DD", which is intentional --
/// lexicographic string comparison on ISO dates gives correct chronological
/// ordering, so date filtering never needs a date-parsing library.
struct PriceBar {
    std::string date;
    double open{};
    double high{};
    double low{};
    double close{};
    double adj_close{};
    long long volume{};
};

/// Holds full historical daily price bars per ticker, sorted ascending by date.
///
/// The point-in-time guarantee is structural, not a convention to remember: there is
/// no method on PriceHistory that returns bars without a date cutoff. The only way to
/// read data is through a View bound to an as-of date, and the View's accessors are
/// defined to never return a bar dated after that cutoff. A caller who wants "all the
/// data" has no API surface to ask for that -- the same way the ONNX parity gate
/// isn't a checklist item, it's a build step that blocks a bad export from shipping.
class PriceHistory {
public:
    /// Loads daily bars from a CSV with header: ticker,date,open,high,low,close,adj_close,volume
    /// Rows for the same ticker need not be pre-sorted; load_csv sorts them by date.
    static PriceHistory load_csv(const std::string& path);

    std::vector<std::string> tickers() const;
    size_t bar_count(const std::string& ticker) const;

    class View;

    /// Returns a view that can only see bars dated on or before as_of_date.
    View as_of(const std::string& as_of_date) const;

private:
    friend class View;
    std::unordered_map<std::string, std::vector<PriceBar>> data_;
};

/// A point-in-time-bounded read handle. Every accessor here is defined so that it is
/// impossible to return a bar dated after as_of_date_, regardless of what's in the
/// underlying store. This is the enforcement point: if this class is correct, no code
/// that only holds a View -- which is the only way to read data at all -- can leak
/// future information into a simulation of the past.
class PriceHistory::View {
public:
    /// All bars for ticker with date <= as_of_date, ascending.
    std::vector<PriceBar> bars(const std::string& ticker) const;

    /// The last n bars for ticker with date <= as_of_date, ascending. Returns fewer
    /// than n if history doesn't go back far enough -- never pads or looks ahead.
    std::vector<PriceBar> lookback(const std::string& ticker, size_t n) const;

    const std::string& as_of_date() const { return as_of_date_; }

private:
    friend class PriceHistory;
    View(const PriceHistory& owner, std::string as_of_date);

    const PriceHistory& owner_;
    std::string as_of_date_;
};

}  // namespace quant