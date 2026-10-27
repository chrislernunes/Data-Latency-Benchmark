#pragma once

#include <map>
#include <string>
#include <vector>
#include <optional>
#include <stdexcept>

struct PriceQty {
    std::string price;
    std::string qty;
};

class OrderBook {
public:
    OrderBook() = default;

    void apply_snapshot(long long last_update_id,
                        const std::vector<PriceQty>& bids,
                        const std::vector<PriceQty>& asks);

    void apply_depth(long long U, long long u,
                     const std::vector<PriceQty>& bids,
                     const std::vector<PriceQty>& asks);

    std::pair<std::vector<PriceQty>, std::vector<PriceQty>> top_n(int n = 5) const;

    bool synchronized() const { return synchronized_; }
    long long last_update_id() const { return last_update_id_.value_or(0); }

private:
    std::map<std::string, std::string, std::greater<std::string>> bids_;  // descending
    std::map<std::string, std::string> asks_;  // ascending
    std::optional<long long> last_update_id_;
    bool synchronized_ = false;

    void set_level(std::map<std::string, std::string>& side, const std::string& price, const std::string& qty);
    void set_level(std::map<std::string, std::string, std::greater<std::string>>& side, const std::string& price, const std::string& qty);
};
