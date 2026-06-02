#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BUILD_DIR="$SCRIPT_DIR/build"

echo "=== Multispectral Demo - Build ==="
echo "Build dir: $BUILD_DIR"

# Check dependencies
if ! command -v cmake &>/dev/null; then
    echo "[INFO] cmake not found, installing..."
    sudo apt-get install -y cmake build-essential
fi

mkdir -p "$BUILD_DIR"

# Build uvc_fix.so (version script required for glibc versioned symbol interposition)
echo "[build] Compiling uvc_fix.so..."
gcc -shared -fPIC -O2 \
    -o "$SCRIPT_DIR/uvc_fix.so" \
    "$SCRIPT_DIR/uvc_fix.c" \
    -ldl -lpthread \
    -Wl,--version-script="$SCRIPT_DIR/uvc_fix.map"

# Build camera_prime
echo "[build] Compiling camera_prime..."
gcc -O2 -o "$SCRIPT_DIR/camera_prime" "$SCRIPT_DIR/camera_prime.c"

cd "$BUILD_DIR"
cmake "$SCRIPT_DIR" -DCMAKE_BUILD_TYPE=Release
make -j$(nproc)

echo ""
echo "=== Build complete ==="
echo "Run with:"
echo "  $BUILD_DIR/multispectral_demo"
echo "  $BUILD_DIR/multispectral_demo /path/to/calibration.qsbs /path/to/db.qsdb"
echo ""
echo "Default calibration files (auto-detected on USB disk):"
echo "  /media/kyle/Kyle/camera_new.qsbs"
echo "  /media/kyle/Kyle/db_std.qsdb"
