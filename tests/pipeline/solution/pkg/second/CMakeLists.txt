# Target names are global across the whole CMake build, so each project's
# target is unique and OUTPUT_NAME gives the module its import name.
Python_add_library(cxbns_second_core MODULE WITH_SOABI src/main.cpp)
set_target_properties(cxbns_second_core PROPERTIES OUTPUT_NAME _core)

install(TARGETS cxbns_second_core DESTINATION cxbns/second)
