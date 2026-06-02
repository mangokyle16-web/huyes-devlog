#!/bin/bash
# run_pipeline.sh — 完整流程：背景差分 + 分割 + 光譜 + 黴菌分析
# 使用方式：./run_pipeline.sh [豆子數量，預設51]
# 前提：/home/kyle/Desktop/background_1250us.png 已存在（空碗背景）
set -e

SCRIPT_DIR="/home/kyle/KyleClaude"
DEMO_DIR="$SCRIPT_DIR/multispectral_demo"
BUILD_DIR="$DEMO_DIR/build"
SDK="$SCRIPT_DIR/sdk_extract/linux-sdk-arm64/qssdk-20250817"
BG_FILE="/home/kyle/Desktop/background_1250us.png"

export LD_LIBRARY_PATH="$SDK:$SDK/libarm64/spinvcore:$SDK/libarm64/opencv/lib"
export LD_PRELOAD="$DEMO_DIR/uvc_fix.so"

QSBS="$SCRIPT_DIR/camera_new.qsbs"
QSDB="$SCRIPT_DIR/db_std.qsdb"
N_BEANS="${1:-51}"

# 確認背景檔存在
if [ ! -f "$BG_FILE" ]; then
    echo "[ERROR] 找不到背景檔 $BG_FILE"
    echo "        請先移除豆子，執行以下指令拍攝背景："
    echo "        camera_prime && capture_one ... 1250 → qs_to_png → background_1250us.png"
    exit 1
fi

# 建立 session 目錄
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
SESSION="$HOME/Desktop/GigaImage_${TIMESTAMP}"
mkdir -p "$SESSION"

echo "======================================"
echo " Session : $SESSION"
echo " 豆子數  : $N_BEANS"
echo " 分割曝光: 1250us（背景差分）"
echo " 光譜曝光: 5000us"
echo " 背景檔  : $BG_FILE"
echo "======================================"

# ── 1. 相機 prime ──────────────────────────────────────────────────────────────
echo ""
echo "[1/6] 相機 prime..."
"$DEMO_DIR/camera_prime" 2>/dev/null || echo "      [WARN] prime 警告，繼續"
sleep 1

# ── 2. 拍攝分割用 1250us + 2500us ────────────────────────────────────────────
echo ""
echo "[2/6] 拍攝分割用 1250us（背景差分）..."
"$BUILD_DIR/capture_one" "$QSBS" "$SESSION/capture_1250us.qs" 1250
"$BUILD_DIR/qs_to_png"   "$SESSION/capture_1250us.qs" "$SESSION/capture_1250us_gray.png"
echo "      → capture_1250us_gray.png"

echo "      拍攝分割增強 2500us（SAM 紋理輸入）..."
"$BUILD_DIR/capture_one" "$QSBS" "$SESSION/capture_2500us.qs" 2500
"$BUILD_DIR/qs_to_png"   "$SESSION/capture_2500us.qs" "$SESSION/capture_2500us_gray.png"
echo "      → capture_2500us_gray.png"

# ── 3. 背景差分 ────────────────────────────────────────────────────────────────
echo ""
echo "[3/6] 背景差分..."
python3 - <<PYEOF
import cv2, numpy as np, sys
bg = cv2.imread("$BG_FILE", cv2.IMREAD_GRAYSCALE)
fg = cv2.imread("$SESSION/capture_1250us_gray.png", cv2.IMREAD_GRAYSCALE)
if bg is None or fg is None:
    print("[ERROR] 無法讀取影像"); sys.exit(1)
diff = np.clip(fg.astype(np.float32) - bg.astype(np.float32), 0, 255).astype(np.uint8)
diff = cv2.GaussianBlur(diff, (5, 5), 0)
cv2.imwrite("$SESSION/diff_1250us.png", diff)
print(f"      → diff_1250us.png  mean={diff.mean():.1f}  max={diff.max()}")
PYEOF

# ── 4. 豆子分割 ────────────────────────────────────────────────────────────────
echo ""
echo "[4/6] 豆子分割 FastSAM（目標 $N_BEANS 顆）..."
python3 -W ignore "$SCRIPT_DIR/segment_beans_sam.py" "$SESSION" "$N_BEANS"

# ── 5. 拍攝光譜用 5000us ───────────────────────────────────────────────────────
echo ""
echo "[5/6] 拍攝光譜用 5000us..."
"$BUILD_DIR/capture_one" "$QSBS" "$SESSION/capture_spec_5000us.qs" 5000
"$BUILD_DIR/qs_to_png"   "$SESSION/capture_spec_5000us.qs" "$SESSION/capture_5000us_gray.png"
echo "      → capture_spec_5000us.qs  capture_5000us_gray.png"

# ── 6. 光譜指紋提取 ────────────────────────────────────────────────────────────
echo ""
echo "[6/7] 光譜指紋提取..."
"$BUILD_DIR/spec_fingerprint" \
    "$QSBS" "$QSDB" \
    "$SESSION/capture_spec_5000us.qs" \
    "$SESSION/beans_rois.json" \
    "$SESSION/spec_raw.csv" \
    "$SESSION/beans_labelmap.png" \
    2>&1 | grep -E "OK|beans|FAIL"

# ── 7. 黴菌分析 + 視覺化 ───────────────────────────────────────────────────────
echo ""
echo "[7/7] 黴菌分析 + 標示圖..."
python3 "$SCRIPT_DIR/mold_analysis_51.py" "$SESSION"
python3 "$SCRIPT_DIR/visualize_beans.py"  "$SESSION"

echo ""
echo "======================================"
echo " 完成！"
echo " 全景圖  → $SESSION/mold_result/overview_labeled.png"
echo " 可疑放大 → $SESSION/mold_result/high_beans_zoom.png"
echo " 分析報告 → $SESSION/mold_result/mold_report.png"
echo "======================================"
