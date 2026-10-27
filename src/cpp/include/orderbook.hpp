#pragma once

#include "decimal.hpp"

#include <cstdint>
#include <map>
#include <optional>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace md {

struct PriceQty {
    std::string price;
    std::string qty;
};

enum class ApplyStatus { Applied, IgnoredStale };

struct OrderBookError : std::runtime_error {
    std::string code;
    OrderBookError(std::string message, std::string error_code)
        : std::runtime_error(std::move(message)), code(std::move(error_code)) {}
};

class OrderBook {
public:
    void invalidate();

    void apply_snapshot(std::int64_t last_update_id,
                        const std::vector<PriceQty>& bids,
                        const std::vector<PriceQty>& asks);

    ApplyStatus apply_depth(std::int64_t first_id,
                            std::int64_t final_id,
                            const std::vector<PriceQty>& bids,
                            const std::vector<PriceQty>& asks);

    // Empty when the book is not synchronized, so a caller cannot read a
    // stale top of book without checking synchronized().
    std::pair<std::vector<PriceQty>, std::vector<PriceQty>> top_n(int n = 5) const;

    bool synchronized() const { return synchronized_; }
    std::optional<std::int64_t> last_update_id() const { return last_update_id_; }

private:
    std::map<std::string, std::string, DecimalGreater> bids_;
    std::map<std::string, std::string, DecimalLess> asks_;
    std::optional<std::int64_t> last_update_id_;
    bool synchronized_ = false;

    static std::vector<std::pair<std::string, std::optional<std::string>>> prepare(
        const std::vector<PriceQty>& levels);

    template <typename Map>
    static void commit(Map& side,
                       const std::vector<std::pair<std::string, std::optional<std::string>>>& ops) {
        for (const auto& [price, qty] : ops) {
            if (!qty) {
                side.erase(price);
            } else {
                side[price] = *qty;
            }
        }
    }
};

}  // namespace md
