#include "decimal.hpp"
#include "orderbook.hpp"
#include "replay.hpp"

#include <iostream>
#include <string>

namespace {

int g_failures = 0;

void check(bool condition, const char* text, int line) {
    if (!condition) {
        std::cerr << "FAIL " << line << ": " << text << "\n";
        ++g_failures;
    }
}

}  // namespace

#define CHECK(cond) check((cond), #cond, __LINE__)

int main() {
    CHECK(md::canonical_decimal("0009.00") == "9");
    CHECK(md::canonical_decimal("0.10") == "0.1");
    CHECK(md::canonical_decimal("0.00000000") == "0");
    CHECK(md::canonical_decimal("100.00") == "100");
    CHECK(md::compare_decimal("9", "10") < 0);
    CHECK(md::compare_decimal("99", "100") < 0);
    CHECK(md::compare_decimal("1.9", "1.10") > 0);
    bool threw = false;
    try {
        md::canonical_decimal("-1");
    } catch (const md::DecimalError&) {
        threw = true;
    }
    CHECK(threw);
    threw = false;
    try {
        md::canonical_decimal("nan");
    } catch (const md::DecimalError&) {
        threw = true;
    }
    CHECK(threw);

    md::OrderBook book;
    book.apply_snapshot(100, {{"100.00", "1.50"}, {"20", "2"}, {"9", "3.0"}},
                        {{"100", "5"}, {"20.0", "4"}, {"9.00", "1"}});
    auto [bids, asks] = book.top_n(5);
    CHECK(bids.size() == 3 && bids[0].price == "100" && bids[1].price == "20" && bids[2].price == "9");
    CHECK(asks.size() == 3 && asks[0].price == "9" && asks[1].price == "20" && asks[2].price == "100");
    CHECK(bids[0].qty == "1.5");

    CHECK(book.apply_depth(90, 99, {{"10", "9"}}, {}) == md::ApplyStatus::IgnoredStale);
    CHECK(book.last_update_id() == 100);
    CHECK(book.apply_depth(100, 104, {{"99.50", "0.00000000"}, {"100", "2.0"}}, {{"20.0", "0"}}) ==
          md::ApplyStatus::Applied);
    threw = false;
    try {
        book.apply_depth(106, 107, {}, {});
    } catch (const md::OrderBookError& exc) {
        threw = exc.code == "gap";
    }
    CHECK(threw);
    CHECK(!book.synchronized());
    auto [empty_bids, empty_asks] = book.top_n(5);
    CHECK(empty_bids.empty() && empty_asks.empty());
    threw = false;
    try {
        book.apply_depth(108, 108, {}, {});
    } catch (const md::OrderBookError& exc) {
        threw = exc.code == "unsynchronized";
    }
    CHECK(threw);

    book.apply_snapshot(1, {{"99.50", "1"}, {"99.5", "2.00"}}, {});
    auto [collapsed, _] = book.top_n(5);
    CHECK(collapsed.size() == 1 && collapsed[0].price == "99.5" && collapsed[0].qty == "2");

    const std::string parity = std::string(FIXTURE_DIR) + "/parity.jsonl";
    const auto replay = md::replay_capture(parity, 5);
    CHECK(replay.at("synchronized").get<bool>());
    CHECK(replay.at("snapshots_applied").get<std::int64_t>() == 1);
    CHECK(replay.at("depth_applied").get<std::int64_t>() == 2);
    CHECK(replay.at("ignored_stale").get<std::int64_t>() == 1);
    CHECK(replay.at("agg_trades").get<std::int64_t>() == 1);
    CHECK(replay.at("gaps").get<std::int64_t>() == 0);
    CHECK(replay.at("invalid_records").get<std::int64_t>() == 0);
    CHECK(replay.at("final_top").at("bids").size() == 1);
    CHECK(replay.at("final_top").at("bids").at(0).at(0) == "100");
    CHECK(replay.at("final_top").at("bids").at(0).at(1) == "2");
    CHECK(replay.at("final_top").at("asks").at(0).at(0) == "100");
    CHECK(replay.at("final_top").at("asks").at(1).at(0) == "101");
    CHECK(replay.at("checkpoints").size() == 4);
    CHECK(replay.at("checkpoints").at(0).at("asks").at(0).at(0) == "20");
    CHECK(md::exit_code_for(replay) == 0);

    const auto gap = md::replay_capture(std::string(FIXTURE_DIR) + "/gap.jsonl", 5);
    CHECK(!gap.at("synchronized").get<bool>());
    CHECK(gap.at("gaps").get<std::int64_t>() == 1);
    CHECK(gap.at("final_top").at("bids").empty());
    CHECK(md::exit_code_for(gap) == 3);

    if (g_failures != 0) {
        std::cerr << g_failures << " failure(s)\n";
        return 1;
    }
    std::cout << "orderbook_tests ok\n";
    return 0;
}
