cmake_minimum_required(VERSION 3.16)
project(multispectral_demo CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_BUILD_TYPE Release)

# ── SDK paths ──────────────────────────────────────────────────────────────────
set(SDK_DIR     "/home/kyle/KyleClaude/sdk_extract/linux-sdk-arm64/qssdk-20250817")
set(SDK_LIB_DIR "${SDK_DIR}")
set(SPINV_DIR   "${SDK_DIR}/libarm64/spinvcore")
set(OPENCV_DIR  "${SDK_DIR}/libarm64/opencv")

# ── System OpenCV ──────────────────────────────────────────────────────────────
find_package(OpenCV REQUIRED)

# ── Include dirs ──────────────────────────────────────────────────────────────
include_directories(
    ${SDK_DIR}
    ${OpenCV_INCLUDE_DIRS}
)

# ── SDK libraries ─────────────────────────────────────────────────────────────
find_library(LIB_CAMERA    qs_camera       PATHS ${SDK_LIB_DIR} NO_DEFAULT_PATH REQUIRED)
find_library(LIB_FILEIO    qs_fileio       PATHS ${SDK_LIB_DIR} NO_DEFAULT_PATH REQUIRED)
find_library(LIB_IMGPROC   qs_imgproc      PATHS ${SDK_LIB_DIR} NO_DEFAULT_PATH REQUIRED)
find_library(LIB_SPECINV   qs_specinv      PATHS ${SDK_LIB_DIR} NO_DEFAULT_PATH REQUIRED)
find_library(LIB_AGRI      qs_agriculture  PATHS ${SDK_LIB_DIR} NO_DEFAULT_PATH REQUIRED)

# ── Executables ───────────────────────────────────────────────────────────────
find_package(X11 REQUIRED)

add_executable(multispectral_demo main.cpp)

target_include_directories(multispectral_demo PRIVATE ${X11_INCLUDE_DIR})

target_link_libraries(multispectral_demo
    ${LIB_CAMERA}
    ${LIB_FILEIO}
    ${LIB_IMGPROC}
    ${LIB_SPECINV}
    ${LIB_AGRI}
    ${OpenCV_LIBS}
    opencv_freetype
    ${X11_LIBRARIES}
    pthread
    dl
)

add_executable(capture_one capture_one.cpp)

target_link_libraries(capture_one
    ${LIB_CAMERA}
    ${LIB_FILEIO}
    pthread
    dl
)

add_executable(spec_fingerprint spec_fingerprint.cpp)

target_link_libraries(spec_fingerprint
    ${LIB_SPECINV}
    ${LIB_FILEIO}
    pthread
    dl
)

add_executable(spec_gate spec_gate.cpp)

target_link_libraries(spec_gate
    ${LIB_SPECINV}
    ${LIB_FILEIO}
    pthread
    dl
)

add_executable(qs_to_png qs_to_png.cpp)

target_link_libraries(qs_to_png
    ${LIB_IMGPROC}
    ${LIB_FILEIO}
    ${OpenCV_LIBS}
    pthread
    dl
)

# ── RPATH: so the binary finds .so files at runtime without LD_LIBRARY_PATH ──
# Use old DT_RPATH (not RUNPATH) so transitive deps also inherit the search path
# Also add rpath-link for the bundled opencv so the linker resolves SDK transitive deps
set(CMAKE_EXE_LINKER_FLAGS "${CMAKE_EXE_LINKER_FLAGS} -Wl,--disable-new-dtags -Wl,-rpath-link,${OPENCV_DIR}/lib")

foreach(_tgt multispectral_demo capture_one spec_fingerprint spec_gate qs_to_png)
    set_target_properties(${_tgt} PROPERTIES
        BUILD_RPATH   "${SDK_LIB_DIR};${OPENCV_DIR}/lib;${SPINV_DIR}"
        INSTALL_RPATH "${SDK_LIB_DIR};${OPENCV_DIR}/lib;${SPINV_DIR}"
        BUILD_WITH_INSTALL_RPATH ON
    )
endforeach()

message(STATUS "SDK dir    : ${SDK_DIR}")
message(STATUS "OpenCV     : ${OpenCV_VERSION} at ${OpenCV_INCLUDE_DIRS}")
