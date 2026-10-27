#include "stats.hpp"

#include <algorithm>
#include <stdexcept>

namespace md {
namespace {

nlohmann::json empty_stats() {
    nlohmann::json stats;
    stats["count"] = 0;
    stats["min"] = nullptr;
    stats["mean"] = nullptr;
    stats["p50"] = nullptr;
    stats["p90"] = nullptr;
    stats["p95"] = nullptr;
    stats["p99"] = nullptr;
    stats["p99_9"] = nullptr;
    stats["max"] = nullptr;
    return stats;
}

}  // namespace

double percentile(const std::vector<std::int64_t>& values, double pct) {
    if (pct < 0.0 || pct > 100.0) {
        throw std::invalid_argument("pct must be between 0 and 100");
    }
    if (values.empty()) {
        throw std::invalid_argument("empty sample");
    }
    auto ordered = values;
    std::sort(ordered.begin(), ordered.end());
    if (ordered.size() == 1) {
        return static_cast<double>(ordered[0]);
    }
    const double rank = (pct / 100.0) * static_cast<double>(ordered.size() - 1);
    const auto low = static_cast<std::size_t>(rank);
    const auto high = std::min(low + 1, ordered.size() - 1);
    const double frac = rank - static_cast<double>(low);
    return static_cast<double>(ordered[low]) * (1.0 - frac) +
           static_cast<double>(ordered[high]) * frac;
}

nlohmann::json latency_stats(const std::vector<std::int64_t>& values) {
    if (values.empty()) {
        return empty_stats();
    }
    nlohmann::json stats;
    const auto [min_it, max_it] = std::minmax_element(values.begin(), values.end());
    long double sum = 0;
    for (auto value : values) {
        sum += static_cast<long double>(value);
    }
    stats["count"] = static_cast<std::int64_t>(values.size());
    stats["min"] = *min_it;
    stats["mean"] = static_cast<double>(sum / static_cast<long double>(values.size()));
    stats["p50"] = percentile(values, 50);
    stats["p90"] = percentile(values, 90);
    stats["p95"] = percentile(values, 95);
    stats["p99"] = percentile(values, 99);
    stats["p99_9"] = percentile(values, 99.9);
    stats["max"] = *max_it;
    return stats;
}

}  // namespace md
