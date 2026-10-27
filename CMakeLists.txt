cmake_minimum_required(VERSION 3.16)
project(binance_md_latency_benchmark LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release)
endif()

# nlohmann/json 3.11.3 is vendored under third_party/ (MIT).
# No system-wide install is required.

add_library(md_core
  src/cpp/src/decimal.cpp
  src/cpp/src/orderbook.cpp
  src/cpp/src/stats.cpp
  src/cpp/src/replay.cpp
)
target_include_directories(md_core PUBLIC src/cpp/include third_party)
target_compile_options(md_core PRIVATE -Wall -Wextra)

add_executable(binance_md_benchmark src/cpp/src/main.cpp)
target_link_libraries(binance_md_benchmark PRIVATE md_core)
target_compile_options(binance_md_benchmark PRIVATE -Wall -Wextra)

add_executable(orderbook_tests src/cpp/src/orderbook_tests.cpp)
target_link_libraries(orderbook_tests PRIVATE md_core)
target_compile_options(orderbook_tests PRIVATE -Wall -Wextra)
target_compile_definitions(orderbook_tests PRIVATE FIXTURE_DIR="${CMAKE_SOURCE_DIR}/tests/fixtures")

enable_testing()
add_test(NAME orderbook_tests COMMAND orderbook_tests)
