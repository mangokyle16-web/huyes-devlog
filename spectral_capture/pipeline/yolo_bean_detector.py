#!/usr/bin/env python3
"""
YOLOv8n-bean Hailo-8 推論器
輸入：RGB 影像（任意尺寸）
輸出：list of {'bbox':(x,y,w,h), 'score':float, 'cx':int, 'cy':int, 'area':int}

模型架構：
  Input  : 640×640×3 UINT8
  Output : cv2.0(80×80×64) cv2.1(40×40×64) cv2.2(20×20×64)  ← bbox DFL
           cv3.0(80×80×1)  cv3.1(40×40×1)  cv3.2(20×20×1)   ← class logits

後處理：DFL decode → anchor-free decode → sigmoid → NMS
"""
import threading
import queue
import numpy as np
import cv2

HEF_PATH    = "/home/kyle/KyleClaude/bean_yolov8n_v3_recal.hef"
INPUT_SIZE  = 640
REG_MAX     = 16      # YOLOv8 DFL bins (64 channels / 4 = 16)
CONF_THRESH = 0.50
IOU_THRESH  = 0.45

# 後處理過濾（對應 SAM2 labeling 的邏輯）
MIN_BEAN_AREA  = 600   # px²，過小 = 小格子誤判
MAX_BEAN_AREA  = 80000 # px²，過大 = 背景區塊
MAX_ASPECT     = 3.0   # max(w,h)/min(w,h)，過長 = 非豆子形狀
MAX_BRIGHTNESS = 200   # bbox 最大亮度上限，超過 = IR LED 高反光（用 max 而非 mean）


def _make_anchors(strides=(8, 16, 32), grid_cell_offset=0.5):
    """預計算 anchor 點 (cx, cy) for 3 scales."""
    anchors, stride_tensor = [], []
    for stride in strides:
        h = w = INPUT_SIZE // stride
        sx = np.arange(w) + grid_cell_offset
        sy = np.arange(h) + grid_cell_offset
        xx, yy = np.meshgrid(sx, sy)
        anchors.append(np.stack([xx.ravel(), yy.ravel()], axis=1))
        stride_tensor.append(np.full(h * w, stride, dtype=np.float32))
    return (np.concatenate(anchors, axis=0).astype(np.float32),
            np.concatenate(stride_tensor))


_ANCHORS, _STRIDES = _make_anchors()
_LINSPACE = np.arange(REG_MAX, dtype=np.float32)   # [0..15] for DFL


def _decode_bbox(bbox_head):
    """
    bbox_head: (N, 4*REG_MAX)  float32
    Returns   : (N, 4) xyxy normalised to INPUT_SIZE
    """
    # reshape → (N, 4, REG_MAX), softmax over last axis, dot with linspace
    n = bbox_head.shape[0]
    pred = bbox_head.reshape(n, 4, REG_MAX)
    # softmax
    pred = pred - pred.max(axis=-1, keepdims=True)
    pred = np.exp(pred)
    pred = pred / pred.sum(axis=-1, keepdims=True)
    dist = (pred * _LINSPACE).sum(axis=-1)  # (N, 4)  lt, tb, rt, rb

    # dist2bbox: anchor ± dist * stride
    lt, tb = dist[:, :2], dist[:, 2:]
    xy_min = (_ANCHORS - lt) * _STRIDES[:, None]
    xy_max = (_ANCHORS + tb) * _STRIDES[:, None]
    return np.concatenate([xy_min, xy_max], axis=1)   # (N,4) x1y1x2y2


def _soft_nms(boxes, scores, sigma=0.5, score_thresh=0.25):
    """
    Soft-NMS with Gaussian decay (Bodla et al. 2017).
    重疊越多 → 分數衰減越多，而非直接刪除。
    比 hard NMS 對 INT8 量化的多框問題更穩健。
    sigma: 高斯衰減強度（越小越嚴格）
    """
    if len(boxes) == 0:
        return []

    boxes_arr  = np.array(boxes, dtype=np.float32)   # (N, 4) xyxy
    scores_arr = np.array(scores, dtype=np.float32).copy()
    N = len(scores_arr)
    indices = list(range(N))
    keep = []

    while indices:
        # 取當前最高分
        best = max(indices, key=lambda i: scores_arr[i])
        keep.append(best)
        indices.remove(best)

        bx1, by1, bx2, by2 = boxes_arr[best]
        for i in indices[:]:
            ix1, iy1, ix2, iy2 = boxes_arr[i]
            inter_w = max(0, min(bx2, ix2) - max(bx1, ix1))
            inter_h = max(0, min(by2, iy2) - max(by1, iy1))
            inter   = inter_w * inter_h
            union   = ((bx2-bx1)*(by2-by1) + (ix2-ix1)*(iy2-iy1) - inter)
            iou     = inter / union if union > 0 else 0.0
            # Gaussian decay
            scores_arr[i] *= np.exp(-(iou ** 2) / sigma)
            if scores_arr[i] < score_thresh:
                indices.remove(i)

    return keep


class YOLOBeanDetector:
    """
    YOLOv8n-bean on Hailo-8 NPU — background worker thread pattern
    (same as fastsam_hailo.py)
    """

    def __init__(self, hef_path: str = HEF_PATH):
        self._req_q = queue.Queue(maxsize=1)
        self._res_q = queue.Queue(maxsize=1)
        self._thread = threading.Thread(
            target=self._worker, args=(hef_path,), daemon=True)
        self._thread.start()
        self._res_q.get(timeout=60)   # wait for warmup
        print("[YOLOBeanDetector] 就緒 (Hailo-8 NPU)")

    def _worker(self, hef_path: str):
        import hailo_platform as hp
        hef    = hp.HEF(hef_path)
        target = hp.VDevice()
        ng     = target.configure(hef)[0]

        in_name  = ng.get_input_vstream_infos()[0].name
        out_names = [o.name for o in ng.get_output_vstream_infos()]

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
                    img = self._req_q.get()
                    if img is None:
                        break
                    try:
                        self._res_q.put(pipeline.infer({in_name: img}))
                    except Exception as e:
                        self._res_q.put(e)

    def detect(self, img_rgb: np.ndarray,
               conf: float = CONF_THRESH,
               iou:  float = IOU_THRESH) -> list:
        """
        img_rgb: (H, W, 3) uint8 RGB
        Returns: list of {'bbox':(x,y,w,h),'score':f,'cx':int,'cy':int,'area':int}
        """
        H, W = img_rgb.shape[:2]

        # 預先計算灰階圖供亮度過濾用
        img_gray = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2GRAY)

        # resize + to NHWC uint8
        inp = cv2.resize(img_rgb, (INPUT_SIZE, INPUT_SIZE))[np.newaxis].astype(np.uint8)

        self._req_q.put(inp)
        raw = self._res_q.get(timeout=10)
        if isinstance(raw, Exception):
            raise raw

        # ── parse outputs ──────────────────────────────────────────
        # Map by feature map size: 80→s=8, 40→s=16, 20→s=32
        bbox_by_stride, cls_by_stride = {}, {}
        for name, tensor in raw.items():
            arr = np.array(tensor)           # (1, H, W, C) float32
            arr = arr.squeeze(0)             # (H, W, C)
            fh = arr.shape[0]
            stride = INPUT_SIZE // fh        # 640/80=8, 640/40=16, 640/20=32
            C = arr.shape[-1]
            flat = arr.reshape(-1, C)        # (H*W, C)
            if C == 64:
                bbox_by_stride[stride] = flat
            else:
                cls_by_stride[stride] = flat   # (H*W, 1)

        # ── concatenate 3 scales ───────────────────────────────────
        strides = [8, 16, 32]
        bbox_all = np.concatenate([bbox_by_stride[s] for s in strides], axis=0)  # (8400,64)
        cls_all  = np.concatenate([cls_by_stride[s]  for s in strides], axis=0)  # (8400,1)

        # ── class confidence (sigmoid) ─────────────────────────────
        scores = 1.0 / (1.0 + np.exp(-cls_all[:, 0]))   # (8400,)

        # ── confidence filter ──────────────────────────────────────
        keep = scores > conf
        if keep.sum() == 0:
            return []

        scores_k  = scores[keep]
        bbox_k    = bbox_all[keep]

        # ── DFL decode → xyxy in INPUT_SIZE coords ─────────────────
        anchors_k = _ANCHORS[keep]
        strides_k = _STRIDES[keep]

        n = bbox_k.shape[0]
        pred = bbox_k.reshape(n, 4, REG_MAX)
        pred = pred - pred.max(axis=-1, keepdims=True)
        pred = np.exp(pred) / np.exp(pred).sum(axis=-1, keepdims=True)
        dist = (pred * _LINSPACE).sum(axis=-1)          # (n, 4)

        xy_min = (anchors_k - dist[:, :2]) * strides_k[:, None]
        xy_max = (anchors_k + dist[:, 2:]) * strides_k[:, None]
        boxes_640 = np.concatenate([xy_min, xy_max], axis=1)

        # ── Soft-NMS ────────────────────────────────────────────────
        keep_idx = _soft_nms(boxes_640, scores_k)
        if not keep_idx:
            return []

        # ── scale back to original image coords ────────────────────
        sx, sy = W / INPUT_SIZE, H / INPUT_SIZE
        results = []
        for i in keep_idx:
            x1, y1, x2, y2 = boxes_640[i]
            x1 = max(0, int(x1 * sx));  y1 = max(0, int(y1 * sy))
            x2 = min(W, int(x2 * sx));  y2 = min(H, int(y2 * sy))
            bw, bh = x2 - x1, y2 - y1
            if bw <= 0 or bh <= 0:
                continue
            area = bw * bh
            # 面積過濾：排除小格子誤判 & 大背景區塊
            if not (MIN_BEAN_AREA < area < MAX_BEAN_AREA):
                continue
            # 長寬比過濾：豆子是橢圓，不應過長
            if max(bw, bh) / max(min(bw, bh), 1) > MAX_ASPECT:
                continue
            # 亮度過濾：排除 IR LED 高反光（max 比 mean 更精準）
            roi = img_gray[y1:y2, x1:x2]
            if roi.size > 0 and int(roi.max()) > MAX_BRIGHTNESS:
                continue
            results.append({
                'bbox':  (x1, y1, bw, bh),
                'cx':    x1 + bw // 2,
                'cy':    y1 + bh // 2,
                'score': float(scores_k[i]),
                'area':  area,
            })
        if not results:
            return []

        # ── 中心點距離合併 ──────────────────────────────────────
        # INT8 量化讓同一顆豆產生多個低重疊框，中心距離近 → 合成一個
        avg_dim      = np.mean([max(b['bbox'][2], b['bbox'][3]) for b in results])
        cdist_thresh = avg_dim * 1.0    # 100% 豆徑內視為同一顆

        by_score = sorted(results, key=lambda b: -b['score'])
        used     = [False] * len(by_score)
        final    = []
        for i, a in enumerate(by_score):
            if used[i]:
                continue
            for j, b in enumerate(by_score):
                if i == j or used[j]:
                    continue
                dist = ((a['cx']-b['cx'])**2 + (a['cy']-b['cy'])**2) ** 0.5
                if dist < cdist_thresh:
                    used[j] = True      # 低分框被高分框吸收
            final.append(a)
            used[i] = True

        return sorted(final, key=lambda b: b['cx'])

    def close(self):
        self._req_q.put(None)
