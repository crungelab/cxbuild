cmake_minimum_required(VERSION 3.18...3.31)

project(cxbuild_test LANGUAGES CXX)

# Plain CPython API, no binding library: the pipeline tests exercise cxbuild,
# not a binding generator. Development.Module is enough to build extensions.
find_package(Python REQUIRED COMPONENTS Interpreter Development.Module)

add_subdirectory(pkg/cxb_simple)  # an ordinary package
add_subdirectory(pkg/second)      # cxbns.second and cxbns.third: two portions of one
add_subdirectory(pkg/third)       # namespace package, like the crunge projects
