#include "orderbook.hpp"

#include <algorithm>
#include <stdexcept>

void OrderBook::set_level(std::map<std::string, std::string>& side, const std::string& price, const std::string& qty) {
    if (qty == "0" || qty.empty()) {
        side.erase(price);
    } else {
        side[price] = qty;
    }
}

void OrderBook::set_level(std::map<std::string, std::string, std::greater<std::string>>& side, const std::string& price, const std::string& qty) {
    if (qty == "0" || qty.empty()) {
        side.erase(price);
    } else {
        side[price] = qty;
    }
}

void OrderBook::apply_snapshot(long long last_update_id,
                               const std::vector<PriceQty>& bids,
                               const std::vector<PriceQty>& asks) {
    bids_.clear();
    asks_.clear();
    for (const auto& pq : bids) {
        set_level(bids_, pq.price, pq.qty);
    }
    for (const auto& pq : asks) {
        set_level(asks_, pq.price, pq.qty);
    }
    last_update_id_ = last_update_id;
    synchronized_ = true;
}

void OrderBook::apply_depth(long long U, long long u,
                            const std::vector<PriceQty>& bids,
                            const std::vector<PriceQty>& asks) {
    if (!synchronized_ || !last_update_id_) {
        throw std::runtime_error("Book not synchronized");
    }
    if (U != *last_update_id_ + 1) {
        synchronized_ = false;
        throw std::runtime_error("Sequence gap");
    }
    for (const auto& pq : bids) {
        set_level(bids_, pq.price, pq.qty);
    }
    for (const auto& pq : asks) {
        set_level(asks_, pq.price, pq.qty);
    }
    last_update_id_ = u;
}

std::pair<std::vector<PriceQty>, std::vector<PriceQty>> OrderBook::top_n(int n) const {
    std::vector<PriceQty> top_bids, top_asks;
    int c = 0;
    for (const auto& [p, q] : bids_) {
        if (c++ >= n) break;
        top_bids.push_back({p, q});
    }
    c = 0;
    for (const auto& [p, q] : asks_) {
        if (c++ >= n) break;
        top_asks.push_back({p, q});
    }
    return {top_bids, top_asks};
}
