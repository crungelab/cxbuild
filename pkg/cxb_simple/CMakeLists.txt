cmake_minimum_required(VERSION 3.15...3.26)

project(cxb_simple VERSION 0.1.0)

#set(PYBIND11_PYTHON_VERSION 3.10)
#add_subdirectory(../../extern/pybind11 pybind11)
#find_package(pybind11 CONFIG REQUIRED)

pybind11_add_module(_core MODULE src/main.cpp)
target_compile_definitions(_core PRIVATE VERSION_INFO=${PROJECT_VERSION})

target_link_directories(_core PRIVATE ${Python_LIBRARY_DIRS})
set_target_properties(_core PROPERTIES OUTPUT_NAME_DEBUG "_core_d")


install(TARGETS _core DESTINATION cxb_simple)
