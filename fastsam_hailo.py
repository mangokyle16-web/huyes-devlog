#!/usr/bin/env python3
"""
FastSAM Hailo-8 加速推論
- 推論：23ms on Hailo-8 NPU
- 後處理：mask 保持 256×256，bounding box 縮放到原始尺寸
- 總速度目標：< 100ms（CPU: 3038ms → >30x 加速）
"""
import threading
import queue
import numpy as np
import cv2

HEF_PATH   = "/home/kyle/KyleClaude/fastsam_s_v3.hef"
INPUT_SIZE = 256


class FastSAMHailo:
    def __init__(self, hef_path: str = HEF_PATH):
        self._req_q  = queue.Queue(maxsize=1)
        self._res_q  = queue.Queue(maxsize=1)
        self._thread = threading.Thread(
            target=self._worker, args=(hef_path,), daemon=True)
        self._thread.start()
        self._res_q.get(timeout=60)  # 等 warmup
        print(f"[FastSAMHailo] 就緒 (Hailo-8 NPU)")

    def _worker(self, hef_path: str):
        import hailo_platform as hp
        hef    = hp.HEF(hef_path)
        target = hp.VDevice()
        ng     = target.configure(hef)[0]
        in_name = ng.get_input_vstream_infos()[0].name
        in_p  = hp.InputVStreamParams.make_from_network_group(
            ng, quantized=False, format_type=hp.FormatType.UINT8)
        out_p = hp.OutputVStreamParams.make_from_network_group(
            ng, quantized=False, format_type=hp.FormatType.FLOAT32)

        dummy = np.zeros((1, INPUT_SIZE, INPUT_SIZE, 3), dtype=np.uint8)
        with ng.activate():
            with hp.InferVStreams(ng, in_p, out_p) as pipeline:
                pipeline.infer({in_name: dummy})
                self._res_q.put("ready")
                while True:
                    inp = self._req_q.get()
                    if inp is None: break
                    try:
                        self._res_q.put(pipeline.infer({in_name: inp}))
                    except Exception as e:
                        self._res_q.put(e)

    def predict(
        self,
        img_bgr: np.ndarray,
        conf: float = 0.50,
        iou_thr: float = 0.20,
        max_det: int = 100,
    ) -> tuple[list[np.ndarray], np.ndarray, np.ndarray]:
        """
        輸入：BGR 影像（任意尺寸）
        輸出：
          masks  - list of bool (256,256)  ← 保持小尺寸，快速
          boxes  - (N,4) float32 xyxy，原始影像座標
          scores - (N,) float32
        """
        H, W = img_bgr.shape[:2]
        inp = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
        inp = cv2.resize(inp, (INPUT_SIZE, INPUT_SIZE))[np.newaxis].astype(np.uint8)

        # Hailo 推論（23ms）
        self._req_q.put(inp)
        results = self._res_q.get(timeout=10)
        if isinstance(results, Exception):
            raise results

        scores_f = np.array(results["fastsam_s/activation1"]).reshape(-1)
        boxes_f  = np.array(results["fastsam_s/conv76"]).reshape(-1, 4)
        coefs_f  = np.array(results["fastsam_s/concat16"]).reshape(-1, 32)
        proto_f  = np.array(results["fastsam_s/conv48"]).reshape(32, -1)

        # 信心過濾
        keep = scores_f > conf
        if keep.sum() == 0:
            return [], np.empty((0, 4)), np.empty(0)
        scores_f = scores_f[keep]
        boxes_f  = boxes_f[keep]
        coefs_f  = coefs_f[keep]

        # cx,cy,w,h → x1,y1,x2,y2 (0-1)
        cx, cy, bw, bh = boxes_f[:,0], boxes_f[:,1], boxes_f[:,2], boxes_f[:,3]
        xyxy = np.stack([
            np.clip(cx-bw/2, 0, 1), np.clip(cy-bh/2, 0, 1),
            np.clip(cx+bw/2, 0, 1), np.clip(cy+bh/2, 0, 1)
        ], axis=1)

        # OpenCV NMS（快速，C++ 實作）
        boxes_xywh = [[float(b[0]), float(b[1]),
                       float(b[2]-b[0]), float(b[3]-b[1])] for b in xyxy]
        nms_idx = cv2.dnn.NMSBoxes(boxes_xywh, scores_f.tolist(), conf, iou_thr)
        if len(nms_idx) == 0:
            return [], np.empty((0, 4)), np.empty(0)
        nms_idx = nms_idx.flatten()[:max_det]

        xyxy_nms    = xyxy[nms_idx]
        scores_nms  = scores_f[nms_idx]
        coefs_nms   = coefs_f[nms_idx]

        # Mask decode：保持 64×64 → sigmoid → (N, 64, 64)
        proto_maps = (coefs_nms @ proto_f).reshape(-1, 64, 64)
        proto_maps = 1.0 / (1.0 + np.exp(-proto_maps))

        # 轉換 box 到原始影像座標
        boxes_px = (xyxy_nms * np.array([W, H, W, H])).astype(np.float32)

        # Mask resize 到 256×256（夠用於 IoU 計算）
        masks = [cv2.resize(pm, (INPUT_SIZE, INPUT_SIZE)) > 0.5
                 for pm in proto_maps]

        return masks, boxes_px, scores_nms

    def close(self):
        self._req_q.put(None)


if __name__ == "__main__":
    import sys, time
    path = sys.argv[1] if len(sys.argv) > 1 else \
        "/home/kyle/Desktop/Report/LuxVisions_20260518_220754/capture_2500us_gray.png"

    img = cv2.imread(path)
    if img is None: sys.exit(f"找不到：{path}")
    if len(img.shape) == 2 or img.shape[2] == 1:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)

    print("初始化（含 warmup）...")
    model = FastSAMHailo()

    # 暖機
    model.predict(img)

    t0 = time.time()
    N = 20
    for _ in range(N):
        masks, boxes, scores = model.predict(img, conf=0.50, iou_thr=0.10)
    elapsed = (time.time()-t0)/N*1000

    print(f"\n偵測到：{len(masks)} 顆豆子")
    print(f"平均總時間：{elapsed:.1f} ms/幀")
    print(f"vs CPU FastSAM（3038ms）→ 加速 {3038/elapsed:.0f}x")

    # 視覺化（box overlay，不需要大 mask）
    vis = img.copy()
    for box, score in zip(boxes, scores):
        c = tuple(int(x) for x in np.random.randint(80, 255, 3))
        cv2.rectangle(vis, tuple(box[:2].astype(int)), tuple(box[2:].astype(int)), c, 2)
        cv2.putText(vis, f"{score:.2f}", tuple(box[:2].astype(int)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, c, 1)
    cv2.imwrite("/tmp/fastsam_hailo_result.png", vis)
    print("結果圖：/tmp/fastsam_hailo_result.png")
    model.close()
