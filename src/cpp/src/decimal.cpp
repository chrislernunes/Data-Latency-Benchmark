#include "decimal.hpp"

#include <algorithm>

namespace md {
namespace {

void reject(const std::string& value) {
    throw DecimalError("malformed decimal: " + value);
}

}  // namespace

std::string canonical_decimal(const std::string& value) {
    if (value.empty()) {
        reject(value);
    }
    for (char c : value) {
        if (!((c >= '0' && c <= '9') || c == '.')) {
            reject(value);
        }
    }
    const auto dot = value.find('.');
    if (dot != std::string::npos && value.find('.', dot + 1) != std::string::npos) {
        reject(value);
    }
    if (value.front() == '.' || value.back() == '.') {
        reject(value);
    }

    std::string integer;
    std::string frac;
    if (dot == std::string::npos) {
        integer = value;
    } else {
        integer = value.substr(0, dot);
        frac = value.substr(dot + 1);
    }
    if (integer.empty()) {
        reject(value);
    }

    std::size_t start = 0;
    while (start + 1 < integer.size() && integer[start] == '0') {
        ++start;
    }
    integer = integer.substr(start);
    while (!frac.empty() && frac.back() == '0') {
        frac.pop_back();
    }
    if (frac.empty()) {
        return integer;
    }
    return integer + "." + frac;
}

bool is_zero_decimal(const std::string& canonical) { return canonical == "0"; }

int compare_decimal(const std::string& left, const std::string& right) {
    const auto split = [](const std::string& value) {
        const auto dot = value.find('.');
        if (dot == std::string::npos) {
            return std::make_pair(value, std::string{});
        }
        return std::make_pair(value.substr(0, dot), value.substr(dot + 1));
    };
    const auto [li, lf] = split(left);
    const auto [ri, rf] = split(right);
    if (li.size() != ri.size()) {
        return li.size() < ri.size() ? -1 : 1;
    }
    if (li != ri) {
        return li < ri ? -1 : 1;
    }
    const std::size_t width = std::max(lf.size(), rf.size());
    for (std::size_t i = 0; i < width; ++i) {
        const char lc = i < lf.size() ? lf[i] : '0';
        const char rc = i < rf.size() ? rf[i] : '0';
        if (lc != rc) {
            return lc < rc ? -1 : 1;
        }
    }
    return 0;
}

}  // namespace md
