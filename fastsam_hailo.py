#!/usr/bin/env python3
"""
FastSAM Hailo-8 加速推論
取代 segment_beans_sam.py 中的 CPU FastSAM，速度從 ~800ms → ~2.6ms

用法：
  from fastsam_hailo import FastSAMHailo
  model = FastSAMHailo()
  masks, boxes, scores = model.predict(img_bgr, conf=0.30)
"""
import numpy as np
import cv2

HEF_PATH = "/home/kyle/KyleClaude/fastsam_s.hef"

# 編譯時的輸入尺寸
INPUT_SIZE = 256


class FastSAMHailo:
    def __init__(self, hef_path: str = HEF_PATH):
        import hailo_platform as hp
        self.target = hp.VDevice()
        self.infer  = self.target.create_infer_model(hef_path)
        self.out_shapes = {
            name: self.infer.output(name).shape
            for name in self.infer.output_names
        }
        # 預先建立 bindings，避免每次 predict 重新分配
        self._cm = self.infer.configure().__enter__()
        self._bindings = self._cm.create_bindings()
        for name, shape in self.out_shapes.items():
            self._bindings.output(name).set_buffer(np.empty(shape, dtype=np.uint8))
        print(f"[FastSAMHailo] 載入 HEF：{hef_path}")
        print(f"  輸出：{list(self.out_shapes.keys())}")

    def predict(
        self,
        img_bgr: np.ndarray,
        conf: float = 0.30,
        iou_thr: float = 0.45,
    ) -> tuple[list[np.ndarray], np.ndarray, np.ndarray]:
        """
        輸入：BGR 影像（任意尺寸）
        輸出：
          masks  - list of bool mask (H, W)，原始影像尺寸
          boxes  - (N, 4) float32，xyxy 格式，原始影像座標
          scores - (N,) float32
        """
        H, W = img_bgr.shape[:2]

        # 前處理：resize → RGB → uint8
        inp = cv2.resize(img_bgr, (INPUT_SIZE, INPUT_SIZE))
        inp = cv2.cvtColor(inp, cv2.COLOR_BGR2RGB)
        inp = inp[np.newaxis]  # (1, 256, 256, 3) uint8

        # Hailo 推論
        self._bindings.input().set_buffer(inp)
        self._cm.run([self._bindings], 5000)

        # 讀取輸出（uint8 → float32，反量化）
        boxes_raw  = self._bindings.output("fastsam_s/conv76").get_buffer()     # (1,1344,4)
        scores_raw = self._bindings.output("fastsam_s/activation1").get_buffer()  # (1,1344,1)
        coefs_raw  = self._bindings.output("fastsam_s/concat16").get_buffer()   # (1,1344,32)
        proto_raw  = self._bindings.output("fastsam_s/conv48").get_buffer()     # (64,64,32)

        boxes_f  = boxes_raw.astype(np.float32).reshape(1344, 4) / 255.0
        scores_f = scores_raw.astype(np.float32).reshape(1344) / 255.0
        coefs_f  = coefs_raw.astype(np.float32).reshape(1344, 32) / 255.0
        proto_f  = proto_raw.astype(np.float32).reshape(32, 64 * 64) / 255.0

        # 篩選高於閾值的 proposals
        keep = scores_f > conf
        if keep.sum() == 0:
            return [], np.empty((0, 4)), np.empty(0)

        boxes_f  = boxes_f[keep]   # (K, 4)  cx,cy,w,h 0-1
        scores_f = scores_f[keep]  # (K,)
        coefs_f  = coefs_f[keep]   # (K, 32)

        # 轉換 cx,cy,w,h → x1,y1,x2,y2（0-1）
        cx, cy, bw, bh = boxes_f[:, 0], boxes_f[:, 1], boxes_f[:, 2], boxes_f[:, 3]
        x1 = np.clip(cx - bw / 2, 0, 1)
        y1 = np.clip(cy - bh / 2, 0, 1)
        x2 = np.clip(cx + bw / 2, 0, 1)
        y2 = np.clip(cy + bh / 2, 0, 1)
        xyxy = np.stack([x1, y1, x2, y2], axis=1)

        # NMS
        indices = _nms(xyxy, scores_f, iou_thr)
        xyxy    = xyxy[indices]
        scores_f = scores_f[indices]
        coefs_f  = coefs_f[indices]

        # 生成 mask：coefs @ proto → (K, 64, 64)
        proto_maps = (coefs_f @ proto_f).reshape(-1, 64, 64)  # (K, 64, 64)
        proto_maps = 1.0 / (1.0 + np.exp(-proto_maps))        # sigmoid

        # resize 到原始影像尺寸
        masks = []
        for i, (pm, box) in enumerate(zip(proto_maps, xyxy)):
            mask_full = cv2.resize(pm, (W, H), interpolation=cv2.INTER_LINEAR)
            # 用 bounding box 裁切 mask 範圍
            x1i = int(box[0] * W)
            y1i = int(box[1] * H)
            x2i = int(box[2] * W)
            y2i = int(box[3] * H)
            bm = np.zeros((H, W), dtype=bool)
            bm[y1i:y2i, x1i:x2i] = mask_full[y1i:y2i, x1i:x2i] > 0.5
            masks.append(bm)

        # 反正規化 boxes 到像素座標
        xyxy_px = xyxy * np.array([W, H, W, H])

        return masks, xyxy_px.astype(np.float32), scores_f


def _nms(boxes: np.ndarray, scores: np.ndarray, iou_thr: float) -> list[int]:
    """Simple NMS，回傳保留的 index list。"""
    order = scores.argsort()[::-1]
    kept  = []
    while len(order):
        i = order[0]
        kept.append(i)
        if len(order) == 1:
            break
        ious = _batch_iou(boxes[i], boxes[order[1:]])
        order = order[1:][ious < iou_thr]
    return kept


def _batch_iou(box: np.ndarray, boxes: np.ndarray) -> np.ndarray:
    x1 = np.maximum(box[0], boxes[:, 0])
    y1 = np.maximum(box[1], boxes[:, 1])
    x2 = np.minimum(box[2], boxes[:, 2])
    y2 = np.minimum(box[3], boxes[:, 3])
    inter = np.clip(x2 - x1, 0, None) * np.clip(y2 - y1, 0, None)
    a1 = (box[2] - box[0]) * (box[3] - box[1])
    a2 = (boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1])
    return inter / (a1 + a2 - inter + 1e-8)


# ── 測試入口 ──────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys, time

    img_path = sys.argv[1] if len(sys.argv) > 1 else \
        "/home/kyle/Desktop/Report/LuxVisions_20260518_220754/capture_2500us_gray.png"

    img = cv2.imread(img_path)
    if img is None:
        print(f"找不到影像：{img_path}")
        sys.exit(1)

    # 灰階 → 偽 RGB（相機輸出是灰階）
    if len(img.shape) == 2 or img.shape[2] == 1:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)

    print(f"影像尺寸：{img.shape}")
    model = FastSAMHailo()

    # 暖機
    model.predict(img, conf=0.30)

    t0 = time.time()
    N = 20
    for _ in range(N):
        masks, boxes, scores = model.predict(img, conf=0.30)
    elapsed = (time.time() - t0) / N * 1000

    print(f"\n偵測到：{len(masks)} 顆豆子")
    print(f"平均推論時間：{elapsed:.1f} ms")
    print(f"吞吐量：{1000/elapsed:.1f} FPS")

    # 視覺化結果
    vis = img.copy()
    for i, (mask, box, score) in enumerate(zip(masks, boxes, scores)):
        color = tuple(int(c) for c in np.random.randint(80, 255, 3))
        vis[mask] = (vis[mask] * 0.5 + np.array(color) * 0.5).astype(np.uint8)
        x1, y1, x2, y2 = box.astype(int)
        cv2.rectangle(vis, (x1, y1), (x2, y2), color, 1)
        cv2.putText(vis, f"{score:.2f}", (x1, y1-4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1)

    out_path = "/tmp/fastsam_hailo_result.png"
    cv2.imwrite(out_path, vis)
    print(f"結果圖：{out_path}")
