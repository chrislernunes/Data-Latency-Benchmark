#include "replay.hpp"

#include "orderbook.hpp"
#include "stats.hpp"

#include <chrono>
#include <fstream>
#include <stdexcept>
#include <utility>

namespace md {
namespace {

struct FatalCaptureError : std::runtime_error {
    using std::runtime_error::runtime_error;
};

std::int64_t now_ns() {
    return std::chrono::duration_cast<std::chrono::nanoseconds>(
               std::chrono::steady_clock::now().time_since_epoch())
        .count();
}

std::int64_t read_i64(const nlohmann::json& object, const char* key) {
    if (!object.contains(key) || !object.at(key).is_number_integer()) {
        throw std::runtime_error(std::string(key) + " must be an integer");
    }
    const auto value = object.at(key).get<std::int64_t>();
    if (value < 0) {
        throw std::runtime_error(std::string(key) + " must be >= 0");
    }
    return value;
}

std::vector<PriceQty> read_levels(const nlohmann::json& object, const char* key) {
    if (!object.contains(key) || !object.at(key).is_array()) {
        throw std::runtime_error(std::string(key) + " must be a list");
    }
    std::vector<PriceQty> levels;
    for (const auto& level : object.at(key)) {
        if (!level.is_array() || level.size() < 2 || !level.at(0).is_string() || !level.at(1).is_string()) {
            throw std::runtime_error(std::string(key) + " levels must be [price, quantity] strings");
        }
        levels.push_back(PriceQty{level.at(0).get<std::string>(), level.at(1).get<std::string>()});
    }
    return levels;
}

nlohmann::json checkpoint_json(std::int64_t line_no, const OrderBook& book, int top_n) {
    const auto [bids, asks] = book.top_n(top_n);
    nlohmann::json bids_json = nlohmann::json::array();
    nlohmann::json asks_json = nlohmann::json::array();
    for (const auto& level : bids) {
        bids_json.push_back(nlohmann::json::array({level.price, level.qty}));
    }
    for (const auto& level : asks) {
        asks_json.push_back(nlohmann::json::array({level.price, level.qty}));
    }
    nlohmann::json checkpoint;
    checkpoint["i"] = line_no;
    checkpoint["synchronized"] = book.synchronized();
    checkpoint["bids"] = std::move(bids_json);
    checkpoint["asks"] = std::move(asks_json);
    return checkpoint;
}

nlohmann::json top_json(const OrderBook& book, int top_n) {
    const auto [bids, asks] = book.top_n(top_n);
    nlohmann::json payload;
    payload["bids"] = nlohmann::json::array();
    payload["asks"] = nlohmann::json::array();
    for (const auto& level : bids) {
        payload["bids"].push_back(nlohmann::json::array({level.price, level.qty}));
    }
    for (const auto& level : asks) {
        payload["asks"].push_back(nlohmann::json::array({level.price, level.qty}));
    }
    return payload;
}

bool blank_line(const std::string& line) {
    return line.find_first_not_of(" \t\r") == std::string::npos;
}

}  // namespace

int exit_code_for(const nlohmann::json& result) {
    if (result.at("synchronized").get<bool>() && result.at("invalid_records").get<std::int64_t>() == 0 &&
        result.at("rejected_unsynchronized").get<std::int64_t>() == 0) {
        return 0;
    }
    return 3;
}

nlohmann::json replay_capture(const std::string& path, int top_n) {
    if (top_n < 0) {
        throw std::runtime_error("top_n must be a non-negative integer");
    }
    std::ifstream input(path);
    if (!input) {
        throw std::runtime_error("capture not found: " + path);
    }

    OrderBook book;
    std::vector<std::int64_t> decode_samples;
    std::vector<std::int64_t> snapshot_samples;
    std::vector<std::int64_t> depth_samples;
    std::vector<std::int64_t> top_samples;
    std::vector<std::int64_t> event_samples;
    nlohmann::json checkpoints = nlohmann::json::array();

    std::int64_t snapshots_applied = 0;
    std::int64_t depth_applied = 0;
    std::int64_t ignored_stale = 0;
    std::int64_t gaps = 0;
    std::int64_t invalid_records = 0;
    std::int64_t rejected_unsynchronized = 0;
    std::int64_t agg_trades = 0;
    bool saw_header = false;
    bool saw_footer = false;

    const auto wall_start = now_ns();
    std::string raw;
    for (std::int64_t line_no = 0; std::getline(input, raw); ++line_no) {
        std::string line = raw;
        if (!line.empty() && line.back() == '\r') {
            line.pop_back();
        }
        if (blank_line(line)) {
            continue;
        }

        const auto decode_start = now_ns();
        nlohmann::json record;
        try {
            record = nlohmann::json::parse(line);
            if (!record.is_object() || !record.contains("type") || !record.at("type").is_string()) {
                throw std::runtime_error("JSONL record must be an object with a type");
            }
            const auto kind = record.at("type").get<std::string>();
            if (kind == "header" || kind == "footer") {
                if (!record.contains("version") || !record.at("version").is_number_integer()) {
                    throw std::runtime_error("version must be an integer");
                }
                if (record.at("version").get<std::int64_t>() != 1) {
                    throw FatalCaptureError("unsupported schema version");
                }
                if (kind == "header") {
                    if (!record.contains("symbol") || !record.at("symbol").is_string() ||
                        record.at("symbol").get<std::string>().empty() || !record.contains("market") ||
                        !record.at("market").is_string() || record.at("market").get<std::string>().empty()) {
                        throw std::runtime_error("header symbol and market are required");
                    }
                }
            } else if (kind == "snapshot") {
                read_i64(record, "last_update_id");
                read_levels(record, "bids");
                read_levels(record, "asks");
            } else if (kind == "depth") {
                read_i64(record, "U");
                read_i64(record, "u");
                read_levels(record, "b");
                read_levels(record, "a");
            } else if (kind == "agg_trade") {
                read_i64(record, "a");
                if (!record.contains("p") || !record.at("p").is_string() || record.at("p").get<std::string>().empty() ||
                    !record.contains("q") || !record.at("q").is_string() || record.at("q").get<std::string>().empty()) {
                    throw std::runtime_error("agg_trade price and quantity must be strings");
                }
            } else {
                throw std::runtime_error("unknown record type: " + kind);
            }
        } catch (const FatalCaptureError&) {
            throw;
        } catch (const std::exception&) {
            ++invalid_records;
            book.invalidate();
            checkpoints.push_back(checkpoint_json(line_no, book, top_n));
            continue;
        }
        const auto decode_ns = now_ns() - decode_start;
        decode_samples.push_back(decode_ns);
        const auto kind = record.at("type").get<std::string>();

        if (!saw_header) {
            if (kind != "header") {
                throw std::runtime_error("first record must be a versioned header");
            }
            saw_header = true;
            continue;
        }
        if (kind == "header") {
            throw std::runtime_error("duplicate header");
        }
        if (saw_footer) {
            throw std::runtime_error("records after footer");
        }
        if (kind == "footer") {
            if (!record.contains("status") || !record.at("status").is_string() ||
                record.at("status").get<std::string>() != "complete") {
                throw std::runtime_error("capture status is not complete");
            }
            saw_footer = true;
            continue;
        }
        if (kind == "snapshot") {
            const auto update_start = now_ns();
            try {
                book.apply_snapshot(read_i64(record, "last_update_id"), read_levels(record, "bids"),
                                    read_levels(record, "asks"));
                const auto update_ns = now_ns() - update_start;
                const auto top_start = now_ns();
                book.top_n(top_n);
                const auto top_ns = now_ns() - top_start;
                ++snapshots_applied;
                snapshot_samples.push_back(update_ns);
                top_samples.push_back(top_ns);
                event_samples.push_back(decode_ns + update_ns + top_ns);
            } catch (const OrderBookError&) {
                ++invalid_records;
                book.invalidate();
            }
            checkpoints.push_back(checkpoint_json(line_no, book, top_n));
            continue;
        }
        if (kind == "depth") {
            const auto update_start = now_ns();
            try {
                const auto status = book.apply_depth(read_i64(record, "U"), read_i64(record, "u"),
                                                      read_levels(record, "b"), read_levels(record, "a"));
                if (status == ApplyStatus::IgnoredStale) {
                    ++ignored_stale;
                } else {
                    const auto update_ns = now_ns() - update_start;
                    const auto top_start = now_ns();
                    book.top_n(top_n);
                    const auto top_ns = now_ns() - top_start;
                    ++depth_applied;
                    depth_samples.push_back(update_ns);
                    top_samples.push_back(top_ns);
                    event_samples.push_back(decode_ns + update_ns + top_ns);
                }
            } catch (const OrderBookError& exc) {
                if (exc.code == "gap") {
                    ++gaps;
                } else if (exc.code == "unsynchronized") {
                    ++rejected_unsynchronized;
                } else {
                    ++invalid_records;
                }
            }
            checkpoints.push_back(checkpoint_json(line_no, book, top_n));
            continue;
        }
        if (kind == "agg_trade") {
            ++agg_trades;
            continue;
        }
        ++invalid_records;
        book.invalidate();
        checkpoints.push_back(checkpoint_json(line_no, book, top_n));
    }

    if (!saw_header) {
        throw std::runtime_error("capture has no header: " + path);
    }
    const auto elapsed_ns = now_ns() - wall_start;
    const auto successful = snapshots_applied + depth_applied;

    nlohmann::json result;
    result["engine"] = "cpp";
    result["snapshots_applied"] = snapshots_applied;
    result["depth_applied"] = depth_applied;
    result["ignored_stale"] = ignored_stale;
    result["gaps"] = gaps;
    result["invalid_records"] = invalid_records;
    result["rejected_unsynchronized"] = rejected_unsynchronized;
    result["agg_trades"] = agg_trades;
    result["processed_successfully"] = successful;
    result["synchronized"] = book.synchronized();
    result["elapsed_ns"] = elapsed_ns;
    if (elapsed_ns == 0) {
        result["throughput_events_per_s"] = nullptr;
    } else {
        result["throughput_events_per_s"] =
            static_cast<double>(successful) / (static_cast<double>(elapsed_ns) / 1e9);
    }
    result["decode_ns"] = latency_stats(decode_samples);
    result["snapshot_update_ns"] = latency_stats(snapshot_samples);
    result["depth_update_ns"] = latency_stats(depth_samples);
    result["topn_ns"] = latency_stats(top_samples);
    result["event_processing_ns"] = latency_stats(event_samples);
    result["final_top"] = top_json(book, top_n);
    result["checkpoints"] = std::move(checkpoints);
    return result;
}

}  // namespace md
