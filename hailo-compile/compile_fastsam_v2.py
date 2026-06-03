"""FastSAM-s 重新量化：使用真實豆子影像做校正"""
import os, glob, numpy as np, cv2
os.environ["HAILO_SDK_CLIENT_LOG_LEVEL"] = "WARNING"
from hailo_sdk_client.allocator import hailo_tools_runner as htr

# 修補 binary_path
HAILO_TOOLS = "/usr/local/lib/python3.10/dist-packages/hailo_tools"
os.environ["LD_LIBRARY_PATH"] = (
    f"{HAILO_TOOLS}/or-tools/dependencies/install/lib:"
    f"{HAILO_TOOLS}/or-tools/lib:"
    + os.environ.get("LD_LIBRARY_PATH", "")
)
_orig = htr.run_tool_from_binary
def _patched(binary_path, *args, **kwargs):
    if binary_path is None:
        binary_path = f"{HAILO_TOOLS}/build/compiler"
    return _orig(binary_path, *args, **kwargs)
htr.run_tool_from_binary = _patched

from hailo_sdk_client import ClientRunner

MODEL_NAME = "fastsam_s"
ONNX_PATH  = "FastSAM-s-256.onnx"
HAR_PATH   = "fastsam_s_v2.har"
HEF_PATH   = "fastsam_s_v2.hef"
HW_ARCH    = "hailo8"
END_NODES  = [
    "/model.22/Concat_2", "/model.22/Sigmoid",
    "/model.22/proto/cv3/act/Mul", "/model.22/dfl/Reshape_1",
]

# 載入真實校正影像
print("[1/5] 載入校正影像...")
calib_imgs = []
for path in sorted(glob.glob("/workspace/calib_images/*.png")):
    img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    if img is None: continue
    # 灰階 → 偽 RGB，resize 到 256×256
    img_rgb = cv2.cvtColor(img, cv2.COLOR_GRAY2RGB)
    img_256 = cv2.resize(img_rgb, (256, 256))
    calib_imgs.append(img_256)
    # 8 個 crops 做資料增強
    h, w = img_rgb.shape[:2]
    for _ in range(8):
        y = np.random.randint(0, h - 256) if h > 256 else 0
        x = np.random.randint(0, w - 256) if w > 256 else 0
        crop = img_rgb[y:y+256, x:x+256]
        if crop.shape[0] == 256 and crop.shape[1] == 256:
            calib_imgs.append(crop)

calib_data = np.array(calib_imgs, dtype=np.uint8)  # (N, 256, 256, 3)
print(f"      {len(calib_data)} 張校正影像")

print("[2/5] 解析 ONNX...")
runner = ClientRunner(hw_arch=HW_ARCH)
runner.translate_onnx_model(
    ONNX_PATH, MODEL_NAME,
    net_input_shapes={"images": [1, 3, 256, 256]},
    end_node_names=END_NODES,
)

print("[3/5] 量化（真實影像）...")
runner.optimize(calib_data)
print("      量化完成")

print(f"[4/5] 儲存 HAR...")
runner.save_har(HAR_PATH)

print("[5/5] 編譯 → HEF...")
compile_runner = ClientRunner(hw_arch=HW_ARCH, har=HAR_PATH)
hef = compile_runner.compile()
with open(HEF_PATH, "wb") as f:
    f.write(hef)
print(f"      ✓ {HEF_PATH}（{os.path.getsize(HEF_PATH)//1024//1024} MB）")
