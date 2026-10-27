cmake_minimum_required(VERSION 3.16)
project(binance_md_latency_benchmark LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release)
endif()

add_executable(binance_md_benchmark
  src/cpp/src/main.cpp
  src/cpp/src/orderbook.cpp
)

target_include_directories(binance_md_benchmark PRIVATE src/cpp/include)
