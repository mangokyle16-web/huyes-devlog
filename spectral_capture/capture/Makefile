# spectral_capture/capture/Makefile
# Build on Pi5: make all
# Adjust SDK paths to match actual installation

CXX      = g++
CXXFLAGS = -std=c++17 -O2 -Wall

# ── Pi5 QS SDK paths ─────────────────────────────────────────
ROOT        ?= /home/kyle/KyleClaude
QS_SDK_DIR  ?= $(ROOT)/sdk_extract/linux-sdk-arm64/qssdk-20250817
OPENCV_LIB  ?= $(QS_SDK_DIR)/libarm64/opencv/lib

CXXFLAGS += -I$(QS_SDK_DIR)
LDFLAGS   = -L$(QS_SDK_DIR) -L$(OPENCV_LIB) \
            -lqs_camera -lqs_agriculture -lqs_fileio -lqs_imgproc \
            -lopencv_world \
            -Wl,-rpath,$(QS_SDK_DIR) -Wl,-rpath,$(OPENCV_LIB)

.PHONY: all clean

all: qs_file_processor preview_daemon

qs_file_processor: qs_file_processor.cpp
	$(CXX) $(CXXFLAGS) $< -o $@ $(LDFLAGS)
	@echo "[OK] Built qs_file_processor"

preview_daemon: preview_daemon.cpp
	$(CXX) $(CXXFLAGS) $< -o $@ $(LDFLAGS)
	@echo "[OK] Built preview_daemon"

clean:
	rm -f qs_file_processor preview_daemon qs_daemon
