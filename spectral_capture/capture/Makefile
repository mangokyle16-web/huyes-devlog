# spectral_capture/capture/Makefile
# Build on Pi5: make
# Adjust QS_SDK_DIR to match actual QS SDK installation path

CXX      = g++
CXXFLAGS = -std=c++17 -O2 -Wall
TARGET   = qs_daemon

# ── Set this to the QS SDK root on Pi5 ───────────────────────
QS_SDK_DIR ?= /opt/qs_sdk
QS_INC      = $(QS_SDK_DIR)/include
QS_LIB      = $(QS_SDK_DIR)/lib

CXXFLAGS += -I$(QS_INC)
LDFLAGS   = -L$(QS_LIB) \
            -lqs_camera -lqs_agriculture -lqs_fileio -lqs_imgproc \
            -Wl,-rpath,$(QS_LIB)

$(TARGET): qs_daemon.cpp
	$(CXX) $(CXXFLAGS) $< -o $@ $(LDFLAGS)
	@echo "[OK] Built $(TARGET)"

clean:
	rm -f $(TARGET)

.PHONY: clean
