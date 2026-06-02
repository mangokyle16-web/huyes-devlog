#!/usr/bin/env python3
"""
Pi5 分析完成後呼叫此腳本，整合 BQS 計算 + 上傳到 Mac Mini + 顯示 QR Code

用法（Pi5 上，每次批次分析完後）：
  python3 post_analysis.py \
    --session_dir ~/KyleClaude/data/sessions/LuxVisions_20260602_120000 \
    --agtron 78.5 \
    --agtron_target 80.0

Pi5 的 main.cpp 可用 subprocess 呼叫：
  system("python3 /home/kyle/KyleClaude/huyes-app/pi5_client/post_analysis.py ...");
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

# 把 siamese 目錄加到 path（BQS 計算需要）
REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "siamese"))

from huyes_client import HuyesClient


def load_session(session_dir: Path) -> list[dict]:
    """
    從 session 目錄讀取分割結果。
    預期格式：session_dir/results.json（由 mold_analysis.py 或 agtron_analysis.py 產生）
    若不存在，嘗試從 Pi5 的既有輸出格式解析。
    """
    results_file = session_dir / "results.json"
    if results_file.exists():
        with open(results_file) as f:
            return json.load(f)
    return []


def build_beans_from_session(
    session_dir: Path,
    agtron: float | None,
    agtron_target: float | None,
) -> tuple[list[dict], list[float] | None]:
    """
    從 Pi5 的分析輸出建立 BQS beans list。
    返回 (beans, mean_spectra_vec)
    """
    # 嘗試讀 mold_analysis 輸出（含 fl_norm）
    mold_file = session_dir / "mold_results.json"
    seg_file  = session_dir / "seg_results.json"

    mold_data: dict[int, float] = {}
    seg_data: dict[int, dict]   = {}

    if mold_file.exists():
        with open(mold_file) as f:
            for row in json.load(f):
                mold_data[row["bean_id"]] = row.get("fl_norm", 0.0)

    if seg_file.exists():
        with open(seg_file) as f:
            for row in json.load(f):
                seg_data[row["bean_id"]] = row

    # 合併成 beans list
    bean_ids = sorted(set(mold_data) | set(seg_data))
    if not bean_ids:
        print("  警告：session 目錄中沒有找到分析結果，送出空批次")
        return [], None

    beans = []
    spectra_vecs = []
    for bid in bean_ids:
        fl_norm  = mold_data.get(bid, 0.0)
        seg      = seg_data.get(bid, {})
        area     = seg.get("area")
        aspect   = seg.get("aspect_ratio")
        spec_vec = seg.get("spectra_vec")

        if spec_vec:
            spectra_vecs.append(spec_vec)

        # 簡化 BQS（不依賴 Siamese，等模型訓練完再升級）
        safety_score    = max(0, 100 - fl_norm * 15)
        reject          = fl_norm >= 6.0
        morpho_score    = _morpho(area, aspect)

        # 烘焙分數
        if agtron is not None and agtron_target is not None:
            dev = abs(agtron - agtron_target)
            roast_score = max(0, 100 - max(0, dev - 5) * 4)
        else:
            roast_score = None

        # 暫時以 safety + morpho 估算 defect（Siamese 模型完成前的替代）
        defect_score = (safety_score * 0.6 + morpho_score * 0.4)

        scores = [defect_score, roast_score or 50, safety_score, morpho_score]
        bqs = defect_score * 0.40 + (roast_score or 50) * 0.25 + safety_score * 0.25 + morpho_score * 0.10

        grade = _grade(bqs, reject)
        beans.append({
            "bean_id":   bid,
            "bqs":       round(bqs, 1),
            "grade":     grade,
            "defect":    round(defect_score, 1),
            "roast":     round(roast_score, 1) if roast_score is not None else None,
            "safety":    round(safety_score, 1),
            "morphology": round(morpho_score, 1),
            "reject":    reject,
        })

    mean_vec = None
    if spectra_vecs:
        n = len(spectra_vecs[0])
        mean_vec = [sum(v[i] for v in spectra_vecs) / len(spectra_vecs) for i in range(n)]

    return beans, mean_vec


def _morpho(area, aspect) -> float:
    score = 100.0
    if area is not None and (area < 800 or area > 3000):
        score -= 30
    if aspect is not None:
        if aspect > 1.5:
            score -= 30
        elif aspect > 1.2:
            score -= 10
    return max(0, score)


def _grade(bqs: float, reject: bool) -> str:
    if reject: return "淘汰"
    if bqs >= 90: return "精選"
    if bqs >= 70: return "標準"
    if bqs >= 40: return "混豆"
    return "淘汰"


def show_qr_on_screen(qr_url: str):
    """在 Pi5 的 7" 螢幕上顯示 QR Code（用 feh 或 Python PIL）。"""
    import urllib.request, io
    try:
        with urllib.request.urlopen(qr_url, timeout=5) as r:
            img_bytes = r.read()
        # 存到 /tmp 再用 feh 顯示
        qr_path = "/tmp/huyes_qr.png"
        with open(qr_path, "wb") as f:
            f.write(img_bytes)
        subprocess.Popen(
            ["feh", "--fullscreen", "--auto-zoom", qr_path],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        print(f"  QR Code 顯示在螢幕上（按任意鍵關閉）")
    except Exception as e:
        print(f"  QR 顯示失敗（{e}），請手動開啟：{qr_url}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--session_dir", required=True)
    parser.add_argument("--agtron", type=float, default=None)
    parser.add_argument("--agtron_target", type=float, default=None)
    parser.add_argument("--notes", default="")
    parser.add_argument("--no_qr", action="store_true", help="不在螢幕顯示 QR Code")
    args = parser.parse_args()

    session_dir = Path(args.session_dir).expanduser()
    print(f"[post_analysis] session: {session_dir.name}")

    # 1. 建立 beans
    beans, mean_vec = build_beans_from_session(session_dir, args.agtron, args.agtron_target)
    if not beans:
        print("  無分析結果，略過上傳")
        sys.exit(0)

    print(f"  豆子數：{len(beans)}")

    # 2. 連接 Mac Mini
    client = HuyesClient()
    print(f"  連接 Mac Mini：{client.base_url}")
    if not client.ping():
        print("  ✗ Mac Mini 不可達，結果已儲存在本地")
        # 儲存到 session 目錄以便稍後重試
        with open(session_dir / "pending_upload.json", "w") as f:
            json.dump({"beans": beans, "spectra_vec": mean_vec, "notes": args.notes}, f)
        sys.exit(0)

    # 3. 上傳
    result = client.send_batch(beans, spectra_vec=mean_vec, notes=args.notes)
    print(f"  ✓ 上傳成功  Batch ID: {result['id']}  BQS: {result['avg_bqs']}")
    print(f"  報告：{result['report_url']}")

    # 4. 顯示 QR Code
    if not args.no_qr:
        mac_ip = client.base_url.replace("http://kyleckagentdeMac-mini-2.local", "http://192.168.68.173")
        qr_url = f"{mac_ip}/batch/{result['id']}/qr"
        show_qr_on_screen(qr_url)

    # 5. 儲存 batch_id 到 session 目錄
    with open(session_dir / "huyes_batch.json", "w") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
