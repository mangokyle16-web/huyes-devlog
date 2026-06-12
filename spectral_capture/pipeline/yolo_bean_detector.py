#!/usr/bin/env python3
"""
YOLOX-tiny bean detector — Hailo-8 NPU
架構：YOLOX-tiny（非 DFL），直接回歸 4 值 bbox
輸出：3 個 feature map (6ch × 3 尺寸) → decode → NMS

輸入：RGB 影像（任意尺寸）
輸出：list of {'bbox':(x,y,w,h), 'score':float, 'cx':int, 'cy':int, 'area':int}
"""
import threading
import queue
import numpy as np
import cv2

HEF_PATH    = "/home/kyle/KyleClaude/yolox_tiny_beans_final.hef"
INPUT_SIZE  = 416
NUM_CLASSES = 1
CONF_THRESH = 0.45    # obj × cls
NMS_THRESH  = 0.45

# 後處理過濾
MIN_BEAN_AREA  = 600
MAX_BEAN_AREA  = 80000
MAX_ASPECT     = 3.0
MAX_BRIGHTNESS = 200   # IR LED 過濾


def _decode_yolox(feat: np.ndarray, stride: int) -> np.ndarray:
    """
    feat: (H, W, 6) = [x_off, y_off, w_log, h_log, obj_logit, cls_logit]
    Returns: (H*W, 5) = [x1, y1, x2, y2, score]
    """
    H, W, _ = feat.shape
    yv, xv = np.meshgrid(np.arange(H), np.arange(W), indexing='ij')
    gx = xv.ravel().astype(np.float32)
    gy = yv.ravel().astype(np.float32)

    flat = feat.reshape(-1, 6)
    x = (flat[:, 0] + gx) * stride
    y = (flat[:, 1] + gy) * stride
    w = np.exp(np.clip(flat[:, 2], -10, 10)) * stride
    h = np.exp(np.clip(flat[:, 3], -10, 10)) * stride
    obj = 1.0 / (1.0 + np.exp(-np.clip(flat[:, 4], -50, 50)))
    cls = 1.0 / (1.0 + np.exp(-np.clip(flat[:, 5], -50, 50)))
    score = obj * cls

    x1 = x - w / 2
    y1 = y - h / 2
    x2 = x + w / 2
    y2 = y + h / 2
    return np.stack([x1, y1, x2, y2, score], axis=1)


def _soft_nms(boxes, scores, sigma=0.5, score_thresh=0.25):
    if len(boxes) == 0:
        return []
    boxes_arr  = np.array(boxes, dtype=np.float32)
    scores_arr = np.array(scores, dtype=np.float32).copy()
    indices = list(range(len(scores_arr)))
    keep = []
    while indices:
        best = max(indices, key=lambda i: scores_arr[i])
        keep.append(best)
        indices.remove(best)
        b = boxes_arr[best]
        for i in indices[:]:
            c = boxes_arr[i]
            iw = max(0, min(b[2],c[2]) - max(b[0],c[0]))
            ih = max(0, min(b[3],c[3]) - max(b[1],c[1]))
            inter = iw * ih
            union = (b[2]-b[0])*(b[3]-b[1]) + (c[2]-c[0])*(c[3]-c[1]) - inter
            iou = inter / union if union > 0 else 0.0
            scores_arr[i] *= np.exp(-(iou**2) / sigma)
            if scores_arr[i] < score_thresh:
                indices.remove(i)
    return keep


class YOLOBeanDetector:
    """YOLOX-tiny bean detector on Hailo-8 NPU — background worker thread"""

    def __init__(self, hef_path: str = HEF_PATH):
        self._req_q = queue.Queue(maxsize=1)
        self._res_q = queue.Queue(maxsize=1)
        self._thread = threading.Thread(
            target=self._worker, args=(hef_path,), daemon=True)
        self._thread.start()
        self._res_q.get(timeout=60)
        print("[YOLOBeanDetector] 就緒 (YOLOX-tiny Hailo-8 NPU)")

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
                    img = self._req_q.get()
                    if img is None:
                        break
                    try:
                        self._res_q.put(pipeline.infer({in_name: img}))
                    except Exception as e:
                        self._res_q.put(e)

    def detect(self, img_rgb: np.ndarray,
               conf: float = CONF_THRESH) -> list:
        """
        img_rgb: (H, W, 3) uint8 RGB
        Returns: list of {'bbox':(x,y,w,h),'score':f,'cx':int,'cy':int,'area':int}
        """
        H, W = img_rgb.shape[:2]

        # ── letterbox 預處理（保持比例 + 補邊 114，與訓練一致）──
        r = min(INPUT_SIZE / H, INPUT_SIZE / W)
        nh, nw = int(round(H * r)), int(round(W * r))
        resized = cv2.resize(img_rgb, (nw, nh))
        padded = np.full((INPUT_SIZE, INPUT_SIZE, 3), 114, dtype=np.uint8)
        padded[:nh, :nw] = resized
        inp = padded[np.newaxis].astype(np.uint8)

        self._req_q.put(inp)
        raw = self._res_q.get(timeout=10)
        if isinstance(raw, Exception):
            raise raw

        # ── 解析 3 個 feature map ─────────────────────────────
        strides_map = {}
        for name, tensor in raw.items():
            a = np.array(tensor).squeeze(0)   # (H, W, 6) NHWC
            fh = a.shape[0]
            stride = INPUT_SIZE // fh          # 416/52=8, 416/26=16, 416/13=32
            strides_map[stride] = a

        # ── YOLOX decode ──────────────────────────────────────
        all_dets = []
        for stride in [8, 16, 32]:
            if stride in strides_map:
                all_dets.append(_decode_yolox(strides_map[stride], stride))

        if not all_dets:
            return []
        all_dets = np.concatenate(all_dets, axis=0)

        # ── confidence filter ─────────────────────────────────
        keep = all_dets[:, 4] > conf
        if keep.sum() == 0:
            return []
        all_dets = all_dets[keep]

        # ── scale back from letterbox to original image ───────
        all_dets[:, :4] /= r

        # ── Soft-NMS ──────────────────────────────────────────
        boxes  = all_dets[:, :4].tolist()
        scores = all_dets[:, 4].tolist()
        keep_idx = _soft_nms(boxes, scores)
        if not keep_idx:
            return []

        # ── 後處理過濾 ────────────────────────────────────────
        results = []
        for i in keep_idx:
            x1, y1, x2, y2 = all_dets[i, :4]
            x1 = max(0, int(x1)); y1 = max(0, int(y1))
            x2 = min(W, int(x2)); y2 = min(H, int(y2))
            bw, bh = x2 - x1, y2 - y1
            if bw <= 0 or bh <= 0:
                continue
            area = bw * bh
            if not (MIN_BEAN_AREA < area < MAX_BEAN_AREA):
                continue
            if max(bw, bh) / max(min(bw, bh), 1) > MAX_ASPECT:
                continue
            # 註：移除舊的 MAX_BRIGHTNESS 過濾——YOLOX 已能區分豆子與 IR 反光，
            # 該過濾會誤殺過曝的亮豆子（frame_805 全數被殺）
            results.append({
                'bbox':  (x1, y1, bw, bh),
                'cx':    x1 + bw // 2,
                'cy':    y1 + bh // 2,
                'score': float(all_dets[i, 4]),
                'area':  area,
            })

        return sorted(results, key=lambda b: b['cx'])

    def close(self):
        self._req_q.put(None)
