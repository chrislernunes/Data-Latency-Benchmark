#include "replay.hpp"

#include <iostream>
#include <string>

namespace {

void usage(std::ostream& out) {
    out << "Usage: binance_md_benchmark replay --input <capture.jsonl> [--top N]\n";
}

}  // namespace

int main(int argc, char** argv) {
    if (argc < 2) {
        usage(std::cerr);
        return 2;
    }
    const std::string command = argv[1];
    if (command != "replay") {
        std::cerr << "unsupported command: " << command << "\n";
        usage(std::cerr);
        return 2;
    }
    std::string input;
    int top_n = 5;
    for (int i = 2; i < argc; ++i) {
        const std::string arg = argv[i];
        if (arg == "--input" && i + 1 < argc) {
            input = argv[++i];
        } else if (arg == "--top" && i + 1 < argc) {
            try {
                top_n = std::stoi(argv[++i]);
            } catch (const std::exception&) {
                std::cerr << "--top must be an integer\n";
                return 2;
            }
        } else {
            std::cerr << "unknown argument: " << arg << "\n";
            usage(std::cerr);
            return 2;
        }
    }
    if (input.empty()) {
        std::cerr << "--input is required\n";
        usage(std::cerr);
        return 2;
    }
    try {
        const auto result = md::replay_capture(input, top_n);
        std::cout << result.dump(2) << "\n";
        return md::exit_code_for(result);
    } catch (const std::exception& exc) {
        std::cerr << exc.what() << "\n";
        return 1;
    }
}
