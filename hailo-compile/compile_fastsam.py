"""FastSAM-s HAR → HEF（直接修補 binary_path）"""
import os, sys

# 設定 LD_LIBRARY_PATH 讓 compiler binary 能找到 protobuf
HAILO_TOOLS = "/usr/local/lib/python3.10/dist-packages/hailo_tools"
os.environ["LD_LIBRARY_PATH"] = (
    f"{HAILO_TOOLS}/or-tools/dependencies/install/lib:"
    f"{HAILO_TOOLS}/or-tools/lib:"
    + os.environ.get("LD_LIBRARY_PATH", "")
)
os.environ["HAILO_SDK_CLIENT_LOG_LEVEL"] = "WARNING"

from hailo_sdk_client import ClientRunner
from hailo_sdk_client.allocator import hailo_tools_runner as htr

# 修補：把 None 的 binary_path 替換為已知路徑
_orig_run = htr.run_tool_from_binary
def _patched_run(binary_path, *args, **kwargs):
    if binary_path is None:
        binary_path = f"{HAILO_TOOLS}/build/compiler"
        print(f"      [patch] binary_path → {binary_path}")
    return _orig_run(binary_path, *args, **kwargs)
htr.run_tool_from_binary = _patched_run

HAR_PATH = "fastsam_s.har"
HEF_PATH = "fastsam_s.hef"

print("[1/2] 載入 HAR...")
runner = ClientRunner(hw_arch="hailo8", har=HAR_PATH)
print("      OK")

print("[2/2] 編譯 → HEF...")
hef = runner.compile()
with open(HEF_PATH, "wb") as f:
    f.write(hef)
size_mb = os.path.getsize(HEF_PATH) // 1024 // 1024
print(f"      ✓ {HEF_PATH}（{size_mb} MB）")
