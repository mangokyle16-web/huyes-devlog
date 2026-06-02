#!/usr/bin/env python3
"""
Pi5 → Mac Mini 同步客戶端

用法：
  # 連線測試
  python3 huyes_client.py ping

  # 送出批次分析結果（從 JSON 檔）
  python3 huyes_client.py send --file results.json

  # 直接從程式呼叫
  from huyes_client import HuyesClient
  client = HuyesClient()
  result = client.send_batch(beans, spectra_vec=mean_vec)
  print(result['qr_url'])
"""

import json
import sys
import time
from pathlib import Path
from typing import Optional

import urllib.request
import urllib.error

CONFIG_PATH = Path(__file__).parent / "config.json"


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return json.load(f)


class HuyesClient:
    def __init__(self, config: Optional[dict] = None):
        cfg = config or load_config()
        host = cfg["mac_mini_host"]
        port = cfg["mac_mini_port"]
        self.base_url = f"http://{host}:{port}"
        self.timeout = cfg.get("timeout_sec", 10)
        self.retry = cfg.get("retry_count", 3)

    def _post(self, path: str, data: dict) -> dict:
        url = self.base_url + path
        body = json.dumps(data).encode()
        req = urllib.request.Request(
            url, data=body,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        for attempt in range(self.retry):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return json.loads(resp.read())
            except urllib.error.URLError as e:
                if attempt < self.retry - 1:
                    print(f"  [retry {attempt+1}] {e}")
                    time.sleep(1)
                else:
                    raise

    def _get(self, path: str) -> dict:
        url = self.base_url + path
        try:
            with urllib.request.urlopen(url, timeout=self.timeout) as resp:
                return json.loads(resp.read())
        except urllib.error.URLError as e:
            raise ConnectionError(f"無法連接 Mac Mini ({self.base_url}): {e}")

    def ping(self) -> bool:
        """回傳 True 表示 Mac Mini API 可達。"""
        try:
            r = self._get("/health")
            return r.get("status") == "ok"
        except Exception:
            return False

    def send_batch(
        self,
        beans: list[dict],
        spectra_vec: Optional[list[float]] = None,
        notes: str = "",
    ) -> dict:
        """
        送出一批分析結果，回傳 {id, avg_bqs, grade_dist, qr_url}

        beans 格式：
          [{"bean_id": 1, "bqs": 92.0, "grade": "精選",
            "defect": 95.0, "roast": 88.0, "safety": 100.0,
            "morphology": 90.0, "reject": False}, ...]
        """
        payload = {"beans": beans, "notes": notes}
        if spectra_vec:
            payload["spectra_vec"] = spectra_vec

        result = self._post("/batch", payload)
        batch_id = result["id"]
        result["qr_url"] = f"{self.base_url}/batch/{batch_id}/qr"
        result["report_url"] = f"{self.base_url}/b/{batch_id}"
        return result

    def get_batch(self, batch_id: str) -> dict:
        return self._get(f"/batch/{batch_id}")


# ── CLI ───────────────────────────────────────────────────────────
def cmd_ping():
    client = HuyesClient()
    print(f"連接目標：{client.base_url}")
    if client.ping():
        print("✓ Mac Mini API 可達，同步正常")
    else:
        print("✗ 無法連接 Mac Mini，請確認：")
        print("  1. Mac Mini 已開機")
        print("  2. uvicorn 正在執行（port 8765）")
        print("  3. 兩台在同一網路")
        sys.exit(1)


def cmd_send(filepath: str):
    with open(filepath) as f:
        data = json.load(f)

    client = HuyesClient()
    if not client.ping():
        print("✗ Mac Mini 不可達，請先執行 ping 確認")
        sys.exit(1)

    result = client.send_batch(
        beans=data["beans"],
        spectra_vec=data.get("spectra_vec"),
        notes=data.get("notes", ""),
    )
    print(f"✓ 批次上傳成功")
    print(f"  Batch ID : {result['id']}")
    print(f"  平均 BQS : {result['avg_bqs']}")
    print(f"  報告 URL : {result['report_url']}")
    print(f"  QR URL   : {result['qr_url']}")
    return result


def main():
    if len(sys.argv) < 2:
        print("用法：python3 huyes_client.py <ping|send> [--file results.json]")
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "ping":
        cmd_ping()
    elif cmd == "send":
        if "--file" not in sys.argv:
            print("用法：python3 huyes_client.py send --file results.json")
            sys.exit(1)
        filepath = sys.argv[sys.argv.index("--file") + 1]
        cmd_send(filepath)
    else:
        print(f"未知指令：{cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
