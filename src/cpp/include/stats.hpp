#pragma once

#include <nlohmann/json.hpp>

#include <cstdint>
#include <vector>

namespace md {

// Linear interpolation: rank = (pct / 100) * (n - 1). Empty samples
// produce count 0 and null percentile fields.
nlohmann::json latency_stats(const std::vector<std::int64_t>& values);
double percentile(const std::vector<std::int64_t>& values, double pct);

}  // namespace md
