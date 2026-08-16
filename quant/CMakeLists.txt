cmake_minimum_required(VERSION 3.20)
project(risk_signal_quant LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Eigen: linear algebra, used throughout the stochastic model and Monte Carlo engine.
# Installed via vcpkg (see README.md in this folder for setup).
find_package(Eigen3 CONFIG REQUIRED)

add_library(quant_core
    src/price_history.cpp
    src/returns.cpp
    src/nelder_mead.cpp
    src/ms_garch.cpp
    src/backtest.cpp
    src/stats.cpp
    src/volatility_regime_strategy.cpp
)
target_include_directories(quant_core PUBLIC include)
target_link_libraries(quant_core PUBLIC Eigen3::Eigen)

# A tiny CLI to exercise the library end to end while it's under development.
add_executable(quant_cli src/main.cpp)
target_link_libraries(quant_cli PRIVATE quant_core)

# Tests (added as pieces come online).
enable_testing()
find_package(GTest CONFIG QUIET)
if(GTest_FOUND)
    add_executable(quant_tests
        tests/test_price_history.cpp
        tests/test_returns.cpp
        tests/test_nelder_mead.cpp
        tests/test_ms_garch.cpp
        tests/test_backtest.cpp
        tests/test_stats.cpp
        tests/test_volatility_regime_strategy.cpp
    )
    target_link_libraries(quant_tests PRIVATE quant_core GTest::gtest GTest::gtest_main)
    add_test(NAME quant_tests COMMAND quant_tests)
else()
    message(STATUS "GTest not found via vcpkg yet -- run: vcpkg install gtest")
endif()

add_executable(quant_run_cycle src/run_cycle.cpp)
target_link_libraries(quant_run_cycle PRIVATE quant_core)