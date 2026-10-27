#include "orderbook.hpp"

namespace md {

void OrderBook::invalidate() {
    bids_.clear();
    asks_.clear();
    last_update_id_.reset();
    synchronized_ = false;
}

std::vector<std::pair<std::string, std::optional<std::string>>> OrderBook::prepare(
    const std::vector<PriceQty>& levels) {
    std::vector<std::pair<std::string, std::optional<std::string>>> ops;
    ops.reserve(levels.size());
    for (const auto& level : levels) {
        std::string price;
        std::string qty;
        try {
            price = canonical_decimal(level.price);
            qty = canonical_decimal(level.qty);
        } catch (const DecimalError& exc) {
            throw OrderBookError(exc.what(), "invalid_level");
        }
        if (is_zero_decimal(price)) {
            throw OrderBookError("price must be positive", "invalid_level");
        }
        if (is_zero_decimal(qty)) {
            ops.emplace_back(std::move(price), std::nullopt);
        } else {
            ops.emplace_back(std::move(price), std::move(qty));
        }
    }
    return ops;
}

void OrderBook::apply_snapshot(std::int64_t last_update_id,
                               const std::vector<PriceQty>& bids,
                               const std::vector<PriceQty>& asks) {
    if (last_update_id < 0) {
        throw OrderBookError("snapshot last_update_id must be >= 0", "invalid_level");
    }
    auto new_bids_ops = prepare(bids);
    auto new_asks_ops = prepare(asks);
    bids_.clear();
    asks_.clear();
    commit(bids_, new_bids_ops);
    commit(asks_, new_asks_ops);
    last_update_id_ = last_update_id;
    synchronized_ = true;
}

ApplyStatus OrderBook::apply_depth(std::int64_t first_id,
                                   std::int64_t final_id,
                                   const std::vector<PriceQty>& bids,
                                   const std::vector<PriceQty>& asks) {
    if (!synchronized_ || !last_update_id_) {
        throw OrderBookError("book is not synchronized", "unsynchronized");
    }
    if (first_id < 0 || final_id < 0) {
        invalidate();
        throw OrderBookError("update ids must be >= 0", "malformed");
    }
    if (final_id < *last_update_id_) {
        return ApplyStatus::IgnoredStale;
    }
    if (first_id > final_id) {
        invalidate();
        throw OrderBookError("malformed depth ids", "malformed");
    }
    if (first_id > *last_update_id_ + 1) {
        const auto book_id = *last_update_id_;
        invalidate();
        throw OrderBookError("sequence gap at book=" + std::to_string(book_id) +
                                 " U=" + std::to_string(first_id),
                             "gap");
    }
    std::vector<std::pair<std::string, std::optional<std::string>>> bid_ops;
    std::vector<std::pair<std::string, std::optional<std::string>>> ask_ops;
    try {
        bid_ops = prepare(bids);
        ask_ops = prepare(asks);
    } catch (const OrderBookError&) {
        invalidate();
        throw;
    }
    commit(bids_, bid_ops);
    commit(asks_, ask_ops);
    last_update_id_ = final_id;
    return ApplyStatus::Applied;
}

std::pair<std::vector<PriceQty>, std::vector<PriceQty>> OrderBook::top_n(int n) const {
    if (n < 0) {
        throw OrderBookError("top n must be a non-negative integer", "invalid_level");
    }
    std::vector<PriceQty> top_bids;
    std::vector<PriceQty> top_asks;
    if (!synchronized_) {
        return {top_bids, top_asks};
    }
    for (const auto& [price, qty] : bids_) {
        if (static_cast<int>(top_bids.size()) >= n) {
            break;
        }
        top_bids.push_back(PriceQty{price, qty});
    }
    for (const auto& [price, qty] : asks_) {
        if (static_cast<int>(top_asks.size()) >= n) {
            break;
        }
        top_asks.push_back(PriceQty{price, qty});
    }
    return {top_bids, top_asks};
}

}  // namespace md
