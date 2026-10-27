#pragma once

#include <nlohmann/json.hpp>

#include <string>

namespace md {

// Replay a schema-version-1 JSONL capture. Throws std::runtime_error for
// missing files, an unsupported schema, or a truncated capture. A readable
// file that ends unsynchronized still returns JSON; the caller chooses
// the exit code.
nlohmann::json replay_capture(const std::string& path, int top_n);

// 0 when the book ends synchronized with no malformed records; otherwise 3.
int exit_code_for(const nlohmann::json& result);

}  // namespace md
