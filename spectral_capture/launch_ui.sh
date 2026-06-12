#!/bin/bash
set -e

BASE=/home/kyle/KyleClaude
SDK=$BASE/sdk_extract/linux-sdk-arm64/qssdk-20250817

export LD_PRELOAD=$BASE/multispectral_demo/uvc_fix.so
export SDK
export LD_LIBRARY_PATH=$SDK:$SDK/libarm64/opencv/lib:$LD_LIBRARY_PATH
export DISPLAY=:0
export WAYLAND_DISPLAY=wayland-0
export XDG_RUNTIME_DIR=/run/user/1000
export SDL_VIDEODRIVER=wayland

daemon_pid=""
cleanup() {
    if [ -n "$daemon_pid" ] && kill -0 "$daemon_pid" 2>/dev/null; then
        kill "$daemon_pid" 2>/dev/null || true
        wait "$daemon_pid" 2>/dev/null || true
    fi
}
trap cleanup EXIT INT TERM

# 清除任何殘留的舊進程，避免相機被佔用 (Device busy)
pkill -9 -f preview_display.py 2>/dev/null || true
pkill -9 -f preview_daemon 2>/dev/null || true
pkill -9 qs_daemon 2>/dev/null || true
for _p in $(fuser /dev/video0 2>/dev/null); do kill -9 "$_p" 2>/dev/null || true; done
sleep 2

$BASE/multispectral_demo/camera_prime
sleep 2

$BASE/spectral_capture/capture/preview_daemon \
    $BASE/spectral_capture/capture/msi.qsbs \
    5 &
daemon_pid=$!

sleep 3

cd $BASE
python3 spectral_capture/preview_display.py
