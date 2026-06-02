#!/bin/bash
# cam_diag.sh — 多光譜相機診斷資訊收集 + 影像擷取
# 用法：./cam_diag.sh [cam_label]
# 例：./cam_diag.sh cam_A  或  ./cam_diag.sh cam_B
# 擷取時固定曝光 7000μs 以利兩台亮度公平比對
# 影像存於 /tmp/capture_<label>.jpg

LABEL="${1:-cam_unknown}"
OUTFILE="/tmp/diag_${LABEL}.txt"
BMP_OUT="/tmp/capture_${LABEL}.bmp"
QS_OUT="/tmp/capture_${LABEL}.qs"
FIXED_EXPOSURE=7000   # μs，與舊相機一致，用於公平比對

echo "========================================" | tee "$OUTFILE"
echo " 多光譜相機診斷報告：$LABEL" | tee -a "$OUTFILE"
echo " 時間：$(date)" | tee -a "$OUTFILE"
echo "========================================" | tee -a "$OUTFILE"

# 1. USB 裝置資訊
echo "" | tee -a "$OUTFILE"
echo "--- USB 裝置 (lsusb) ---" | tee -a "$OUTFILE"
lsusb 2>/dev/null | tee -a "$OUTFILE"

echo "" | tee -a "$OUTFILE"
echo "--- USB 詳細資訊 (相機廠商 ID，嘗試常見 QS/UVC ID) ---" | tee -a "$OUTFILE"
# 找所有 UVC 相關裝置
for dev in /sys/bus/usb/devices/*/; do
    id_vendor=$(cat "$dev/idVendor" 2>/dev/null)
    id_product=$(cat "$dev/idProduct" 2>/dev/null)
    bcd=$(cat "$dev/bcdDevice" 2>/dev/null)
    manufacturer=$(cat "$dev/manufacturer" 2>/dev/null)
    product=$(cat "$dev/product" 2>/dev/null)
    serial=$(cat "$dev/serial" 2>/dev/null)
    speed=$(cat "$dev/speed" 2>/dev/null)
    # 過濾掉空白裝置
    [ -z "$id_vendor" ] && continue
    [ -z "$product" ] && continue
    echo "  VID:PID=$id_vendor:$id_product  bcdDevice=$bcd  Speed=${speed}Mbps" | tee -a "$OUTFILE"
    echo "  Manufacturer=$manufacturer  Product=$product  Serial=$serial" | tee -a "$OUTFILE"
    echo "" | tee -a "$OUTFILE"
done

# 2. V4L2 節點
echo "--- V4L2 裝置節點 ---" | tee -a "$OUTFILE"
for node in /dev/video*; do
    echo "" | tee -a "$OUTFILE"
    echo "  節點：$node" | tee -a "$OUTFILE"
    v4l2-ctl -d "$node" --info 2>&1 | sed 's/^/    /' | tee -a "$OUTFILE"
done

# 3. V4L2 支援格式
echo "" | tee -a "$OUTFILE"
echo "--- V4L2 支援格式 (主要節點 video0 或 video1) ---" | tee -a "$OUTFILE"
for node in /dev/video0 /dev/video1; do
    [ -e "$node" ] || continue
    echo "  $node 格式：" | tee -a "$OUTFILE"
    v4l2-ctl -d "$node" --list-formats-ext 2>&1 | sed 's/^/    /' | tee -a "$OUTFILE"
done

# 4. V4L2 控制項
echo "" | tee -a "$OUTFILE"
echo "--- V4L2 控制項 (主要節點) ---" | tee -a "$OUTFILE"
for node in /dev/video0 /dev/video1; do
    [ -e "$node" ] || continue
    cap=$(v4l2-ctl -d "$node" --info 2>/dev/null)
    echo "$cap" | grep -q "Video Capture" || continue
    echo "  $node 控制項：" | tee -a "$OUTFILE"
    v4l2-ctl -d "$node" --list-ctrls-menus 2>&1 | sed 's/^/    /' | tee -a "$OUTFILE"
    break
done

# 5. dmesg 相機相關
echo "" | tee -a "$OUTFILE"
echo "--- dmesg 相機相關訊息 (最後 200 行過濾) ---" | tee -a "$OUTFILE"
dmesg 2>/dev/null | grep -iE "uvc|usb|video|camera|uvcvideo|gadget|gs_usb" | tail -80 | tee -a "$OUTFILE"

# 6. uvcvideo 模組資訊
echo "" | tee -a "$OUTFILE"
echo "--- uvcvideo 模組 ---" | tee -a "$OUTFILE"
modinfo uvcvideo 2>/dev/null | grep -E "version|filename|description" | tee -a "$OUTFILE"

# 7. 影像擷取（固定曝光，公平比對）
echo "" | tee -a "$OUTFILE"
echo "--- 影像擷取 (固定曝光 ${FIXED_EXPOSURE}μs) ---" | tee -a "$OUTFILE"

# 找主要 Video Capture 節點
CAM_NODE=""
for node in /dev/video0 /dev/video1; do
    [ -e "$node" ] || continue
    v4l2-ctl -d "$node" --info 2>/dev/null | grep -q "Video Capture" && { CAM_NODE="$node"; break; }
done

if [ -z "$CAM_NODE" ]; then
    echo "  找不到 Video Capture 節點，跳過影像擷取" | tee -a "$OUTFILE"
else
    echo "  使用節點：$CAM_NODE" | tee -a "$OUTFILE"

    # 強制設定固定曝光（Manual Mode）
    v4l2-ctl -d "$CAM_NODE" --set-ctrl=auto_exposure=1 2>/dev/null
    v4l2-ctl -d "$CAM_NODE" --set-ctrl=exposure_time_absolute=${FIXED_EXPOSURE} 2>/dev/null
    echo "  曝光設定：${FIXED_EXPOSURE}μs (Manual)" | tee -a "$OUTFILE"

    SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

    # --- (1) BMP：無損，用 ffmpeg，skip 前 5 幀讓曝光穩定 ---
    echo "  [1/2] 擷取 BMP（無損）..." | tee -a "$OUTFILE"
    ffmpeg -loglevel error \
        -f v4l2 -input_format yuyv422 -video_size 1600x1200 \
        -i "$CAM_NODE" \
        -vf "select=gte(n\,5)" -frames:v 1 \
        -y "$BMP_OUT" 2>&1 | tee -a "$OUTFILE"
    if [ -f "$BMP_OUT" ]; then
        SIZE=$(stat -c%s "$BMP_OUT" 2>/dev/null)
        echo "  BMP 儲存：$BMP_OUT ($(( SIZE/1024 )) KB)" | tee -a "$OUTFILE"
    else
        echo "  BMP 擷取失敗" | tee -a "$OUTFILE"
    fi

    # --- (2) .qs：相機原始 raw 格式（GREY 544x384），供原廠分析 ---
    echo "  [2/2] 擷取 .qs（原始 raw）..." | tee -a "$OUTFILE"
    if [ -x "$SCRIPT_DIR/capture_v4l2" ]; then
        "$SCRIPT_DIR/capture_v4l2" --grey "$CAM_NODE" "$QS_OUT" 2>&1 | tee -a "$OUTFILE"
        if [ -f "$QS_OUT" ]; then
            SIZE=$(stat -c%s "$QS_OUT" 2>/dev/null)
            echo "  .qs 儲存：$QS_OUT ($(( SIZE/1024 )) KB)" | tee -a "$OUTFILE"
        fi
    else
        echo "  找不到 capture_v4l2，跳過 .qs 擷取" | tee -a "$OUTFILE"
    fi
fi

echo "" | tee -a "$OUTFILE"
echo "========================================" | tee -a "$OUTFILE"
echo " 診斷完成" | tee -a "$OUTFILE"
echo " 報告 ：$OUTFILE" | tee -a "$OUTFILE"
echo " BMP  ：$BMP_OUT" | tee -a "$OUTFILE"
echo " Raw  ：$QS_OUT" | tee -a "$OUTFILE"
echo "========================================" | tee -a "$OUTFILE"
