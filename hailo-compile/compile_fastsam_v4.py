"""FastSAM v4：純灰階影像量化（完全匹配推論輸入分佈）"""
import os, glob, numpy as np, cv2
os.environ["HAILO_SDK_CLIENT_LOG_LEVEL"] = "WARNING"

HAILO_TOOLS = "/usr/local/lib/python3.10/dist-packages/hailo_tools"
os.environ["LD_LIBRARY_PATH"] = (
    f"{HAILO_TOOLS}/or-tools/dependencies/install/lib:"
    f"{HAILO_TOOLS}/or-tools/lib:"
    + os.environ.get("LD_LIBRARY_PATH", "")
)
from hailo_sdk_client.allocator import hailo_tools_runner as htr
_orig = htr.run_tool_from_binary
def _p(bp, *a, **k):
    return _orig(bp or f"{HAILO_TOOLS}/build/compiler", *a, **k)
htr.run_tool_from_binary = _p
from hailo_sdk_client import ClientRunner

END_NODES = [
    "/model.22/Concat_2", "/model.22/Sigmoid",
    "/model.22/proto/cv3/act/Mul", "/model.22/dfl/Reshape_1",
]

print("[1/5] 建立校正資料（純灰階→偽RGB，完全匹配推論輸入）...")
calib = []
for p in sorted(glob.glob("/workspace/calib_gray/*.png")):
    img = cv2.imread(p, cv2.IMREAD_GRAYSCALE)
    if img is None: continue
    # 完全複製推論時的前處理：GRAY→BGR→RGB (R=G=B)
    rgb = cv2.cvtColor(img, cv2.COLOR_GRAY2RGB)
    # 全圖 resize
    calib.append(cv2.resize(rgb, (256, 256)))
    # 多個 crops（從 1600×1200 的碗中心區域）
    h, w = img.shape
    cx, cy = w//2, h//2
    for size in [512, 400, 300]:
        x1 = max(0, cx-size//2); y1 = max(0, cy-size//2)
        x2 = min(w, cx+size//2); y2 = min(h, cy+size//2)
        crop = rgb[y1:y2, x1:x2]
        if crop.shape[0] >= 64 and crop.shape[1] >= 64:
            calib.append(cv2.resize(crop, (256, 256)))

calib_data = np.array(calib, dtype=np.uint8)
print(f"      {len(calib_data)} 張（59 張原圖 × 4 crops）")

print("[2/5] 解析 ONNX...")
runner = ClientRunner(hw_arch="hailo8")
runner.translate_onnx_model(
    "FastSAM-s-256.onnx", "fastsam_s",
    net_input_shapes={"images": [1, 3, 256, 256]},
    end_node_names=END_NODES,
)

print("[3/5] 量化（純灰階校正）...")
runner.optimize(calib_data)
print("      完成")

print("[4/5] 儲存 HAR...")
runner.save_har("fastsam_s_v4.har")

print("[5/5] 編譯 → HEF...")
cr = ClientRunner(hw_arch="hailo8", har="fastsam_s_v4.har")
hef = cr.compile()
with open("fastsam_s_v4.hef", "wb") as f:
    f.write(hef)
print(f"      ✓ fastsam_s_v4.hef ({os.path.getsize('fastsam_s_v4.hef')//1024//1024}MB)")
