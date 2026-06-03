"""FastSAM-s 第三版：用真實彩色咖啡豆影像校正"""
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
def _patched(binary_path, *args, **kwargs):
    if binary_path is None:
        binary_path = f"{HAILO_TOOLS}/build/compiler"
    return _orig(binary_path, *args, **kwargs)
htr.run_tool_from_binary = _patched
from hailo_sdk_client import ClientRunner

END_NODES = [
    "/model.22/Concat_2", "/model.22/Sigmoid",
    "/model.22/proto/cv3/act/Mul", "/model.22/dfl/Reshape_1",
]

# 彩色咖啡豆影像 + 灰階轉 RGB（模擬推論時的輸入）
print("[1/5] 建立校正資料集...")
calib = []
# 真實彩色圖
for p in sorted(glob.glob("/workspace/calib_images/*.jpg")):
    img = cv2.imread(p)
    if img is None: continue
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    calib.append(cv2.resize(img, (256, 256)))
    # 8 個 random crops
    h, w = img.shape[:2]
    for _ in range(8):
        y = np.random.randint(0, max(1, h-256))
        x = np.random.randint(0, max(1, w-256))
        c = img[y:y+256, x:x+256]
        if c.shape[:2] == (256, 256):
            calib.append(c)

# 灰階轉 RGB（模擬相機輸入）
for p in sorted(glob.glob("/workspace/calib_images/*.png")):
    img = cv2.imread(p, cv2.IMREAD_GRAYSCALE)
    if img is None: continue
    rgb = cv2.cvtColor(img, cv2.COLOR_GRAY2RGB)
    calib.append(cv2.resize(rgb, (256, 256)))

calib_data = np.array(calib, dtype=np.uint8)
print(f"      {len(calib_data)} 張（彩色+灰階混合）")

print("[2/5] 解析 ONNX...")
runner = ClientRunner(hw_arch="hailo8")
runner.translate_onnx_model(
    "FastSAM-s-256.onnx", "fastsam_s",
    net_input_shapes={"images": [1, 3, 256, 256]},
    end_node_names=END_NODES,
)

print("[3/5] 量化...")
runner.optimize(calib_data)
print("      完成")

print("[4/5] 儲存 HAR...")
runner.save_har("fastsam_s_v3.har")

print("[5/5] 編譯 → HEF...")
cr = ClientRunner(hw_arch="hailo8", har="fastsam_s_v3.har")
hef = cr.compile()
with open("fastsam_s_v3.hef", "wb") as f:
    f.write(hef)
print(f"      ✓ fastsam_s_v3.hef ({os.path.getsize('fastsam_s_v3.hef')//1024//1024}MB)")
