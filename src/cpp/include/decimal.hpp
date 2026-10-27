#pragma once

#include <stdexcept>
#include <string>
#include <utility>

namespace md {

struct DecimalError : std::runtime_error {
    using std::runtime_error::runtime_error;
};

// Canonical decimal: no sign, no exponent, no leading integer zeros
// (except zero), no trailing fractional zeros. Zero is "0".
std::string canonical_decimal(const std::string& value);
int compare_decimal(const std::string& left, const std::string& right);
bool is_zero_decimal(const std::string& canonical);

struct DecimalLess {
    bool operator()(const std::string& left, const std::string& right) const {
        return compare_decimal(left, right) < 0;
    }
};

struct DecimalGreater {
    bool operator()(const std::string& left, const std::string& right) const {
        return compare_decimal(left, right) > 0;
    }
};

}  // namespace md
