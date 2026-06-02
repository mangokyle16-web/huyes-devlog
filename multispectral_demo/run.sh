#!/bin/bash
# Multispectral Demo - Run Script
# Sets library paths and launches the demo

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BINARY="$SCRIPT_DIR/build/multispectral_demo"
SPINV_DIR="/home/kyle/KyleClaude/sdk_extract/linux-sdk-arm64/qssdk-20250817/libarm64/spinvcore"
OPENCV_DIR="/home/kyle/KyleClaude/sdk_extract/linux-sdk-arm64/qssdk-20250817/libarm64/opencv/lib"

if [ ! -f "$BINARY" ]; then
    echo "Binary not found. Run build.sh first."
    exit 1
fi

# Prevent concurrent invocations (two runs = cascading USB resets → D-state).
LOCKFILE="/tmp/multispectral_demo.lock"
if [ -e "$LOCKFILE" ]; then
    LOCK_PID=$(cat "$LOCKFILE" 2>/dev/null)
    if kill -0 "$LOCK_PID" 2>/dev/null; then
        echo "[run.sh] Already running (PID $LOCK_PID). Aborting."
        exit 1
    fi
fi
echo $$ > "$LOCKFILE"

# Stop the Wayland panel so it doesn't overlap the kiosk window.
# Kill lwrespawn first so it won't revive the panel, then kill the panel itself.
_LWRESP_PID=$(pgrep -f "lwrespawn.*wf-panel-pi" 2>/dev/null | head -1)
_PANEL_PID=$(pgrep -x wf-panel-pi 2>/dev/null | head -1)
[ -n "$_LWRESP_PID" ] && kill "$_LWRESP_PID" 2>/dev/null
[ -n "$_PANEL_PID" ]  && kill "$_PANEL_PID"  2>/dev/null
sleep 0.3

trap 'rm -f "$LOCKFILE"; nohup /bin/sh /usr/bin/lwrespawn /usr/bin/wf-panel-pi >/dev/null 2>&1 &' EXIT

# Prime the camera: absorb the one-time USB reset triggered by first STREAMON.
# Safe to run even if camera is already primed (detects no-reset and skips).
# Skip with: SKIP_PRIME=1 ./run.sh
if [ "${SKIP_PRIME:-0}" != "1" ] && [ -f "$SCRIPT_DIR/camera_prime" ]; then
    echo "=== Camera Prime ==="
    "$SCRIPT_DIR/camera_prime"
    PRIME_RET=$?
    if [ $PRIME_RET -ne 0 ]; then
        echo "[run.sh] camera_prime failed (exit $PRIME_RET) — aborting"
        exit 1
    fi
    echo "===================="
fi

export LD_LIBRARY_PATH="$SPINV_DIR:$OPENCV_DIR${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export LD_PRELOAD="$SCRIPT_DIR/uvc_fix.so"

# Force X11/XCB mode so cv::moveWindow and override_redirect work correctly.
# Without this Qt auto-detects the Wayland socket and ignores cv::moveWindow.
export DISPLAY=:0
unset WAYLAND_DISPLAY
export QT_QPA_PLATFORM=xcb

DEFAULT_QSBS="/home/kyle/KyleClaude/camera_new.qsbs"
DEFAULT_QSDB="/home/kyle/KyleClaude/db_std.qsdb"

if [ "$#" -eq 0 ]; then
    "$BINARY" "$DEFAULT_QSBS" "$DEFAULT_QSDB"
else
    "$BINARY" "$@"
fi
