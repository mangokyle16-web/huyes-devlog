#!/bin/bash
SDK=/home/kyle/KyleClaude/sdk_extract/linux-sdk-arm64/qssdk-20250817
OPENCV_LIB=$SDK/libarm64/opencv/lib
UVC_FIX=/home/kyle/KyleClaude/multispectral_demo/uvc_fix.so
CAMERA_PRIME=/home/kyle/KyleClaude/multispectral_demo/camera_prime

export LD_PRELOAD=$UVC_FIX
export LD_LIBRARY_PATH=$SDK:$OPENCV_LIB:$LD_LIBRARY_PATH

# Prime camera to absorb initial USB reset
$CAMERA_PRIME 2>/dev/null
sleep 1

cd /home/kyle/KyleClaude
echo "[start_capture] origin=${1:-unknown} roast=${2:-green}"
exec python3 -m spectral_capture.main     --origin "${1:-unknown}" --roast "${2:-green}"     --db spectral_capture/data/beans.db
