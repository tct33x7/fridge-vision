"""轻量 ByteTrack 风格多目标跟踪器 (纯 numpy, 无 lap/scipy 依赖)。

两级关联:
  1. 高置信度检测 vs 全部轨迹 (IoU 贪心匹配)
  2. 低置信度检测 vs 剩余未匹配轨迹 (ByteTrack 核心: 挽回边缘/遮挡的低分检测)
  3. 未匹配的高分检测 -> 新轨迹

返回已确认 (连续命中 >= min_hits) 的轨迹, 供方向线计数使用。
"""

from __future__ import annotations

import numpy as np


def _iou_matrix(boxes_a, boxes_b):
    """(N,4)x(M,4) xyxy -> (N,M) IoU"""
    if len(boxes_a) == 0 or len(boxes_b) == 0:
        return np.zeros((len(boxes_a), len(boxes_b)))
    a = np.asarray(boxes_a, dtype=np.float32)
    b = np.asarray(boxes_b, dtype=np.float32)
    ax1, ay1, ax2, ay2 = a[:, 0:1], a[:, 1:2], a[:, 2:3], a[:, 3:4]  # (N,1)
    bx1, by1, bx2, by2 = b[:, 0:1].T, b[:, 1:2].T, b[:, 2:3].T, b[:, 3:4].T  # (1,M)
    iw = np.maximum(0.0, np.minimum(ax2, bx2) - np.maximum(ax1, bx1))
    ih = np.maximum(0.0, np.minimum(ay2, by2) - np.maximum(ay1, by1))
    inter = iw * ih
    union = (ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - inter
    return np.where(union > 0, inter / union, 0.0)


def _greedy_match(iou, threshold):
    """IoU 矩阵贪心匹配 -> (rows, cols) 已匹配索引对"""
    matched_rows, matched_cols = [], []
    if iou.size == 0:
        return matched_rows, matched_cols
    iou = iou.copy()
    while True:
        idx = np.argmax(iou)
        r, c = divmod(int(idx), iou.shape[1])
        if iou[r, c] < threshold:
            break
        matched_rows.append(r)
        matched_cols.append(c)
        iou[r, :] = -1.0
        iou[:, c] = -1.0
    return matched_rows, matched_cols


class _Track:
    __slots__ = ("tid", "cls_id", "box", "conf", "hits", "age", "confirmed", "best_conf")

    def __init__(self, tid, cls_id, box, conf):
        self.tid = tid
        self.cls_id = cls_id
        self.box = np.asarray(box, dtype=np.float32)
        self.conf = conf
        self.best_conf = conf
        self.hits = 1
        self.age = 0          # 连续未命中帧数
        self.confirmed = False


class ByteTrackLite:
    def __init__(self, high_conf=0.45, low_conf=0.15, match_iou=0.25,
                 min_hits=2, max_age=25):
        self.high_conf = high_conf
        self.low_conf = low_conf
        self.match_iou = match_iou
        self.min_hits = min_hits
        self.max_age = max_age
        self.tracks: list[_Track] = []
        self._next_id = 1

    def update(self, detections):
        """detections: [(x1,y1,x2,y2,conf,cls_id), ...] (原图坐标)
        返回 [(tid, cls_id, x1,y1,x2,y2, conf), ...] (仅已确认轨迹)"""
        if detections:
            dets = np.array([d[:4] for d in detections], dtype=np.float32)
            confs = np.array([d[4] for d in detections], dtype=np.float32)
            clss = np.array([d[5] for d in detections], dtype=np.int64)
        else:
            dets = np.zeros((0, 4), dtype=np.float32)
            confs = np.zeros((0,), dtype=np.float32)
            clss = np.zeros((0,), dtype=np.int64)

        track_boxes = np.array([t.box for t in self.tracks], dtype=np.float32) \
            if self.tracks else np.zeros((0, 4), dtype=np.float32)

        hi = confs >= self.high_conf
        lo = (~hi) & (confs >= self.low_conf)

        matched_tracks: set[int] = set()   # 已匹配轨迹索引
        assigned = {}  # det_idx -> track 引用

        # ---- 第一级: 高分检测 vs 全部轨迹 ----
        iou_h = _iou_matrix(dets[hi], track_boxes)
        rows, cols = _greedy_match(iou_h, self.match_iou)
        hi_idx = np.where(hi)[0]
        for r, c in zip(rows, cols):
            det_i = int(hi_idx[r])
            t = self.tracks[cols[c]]
            self._refresh(t, dets[det_i], confs[det_i], clss[det_i])
            assigned[det_i] = t
            matched_tracks.add(cols[c])

        # ---- 第二级: 低分检测 vs 剩余轨迹 ----
        remain_idx = [i for i in range(len(self.tracks)) if i not in matched_tracks]
        if remain_idx and lo.any():
            remain_boxes = track_boxes[remain_idx]
            iou_l = _iou_matrix(dets[lo], remain_boxes)
            rows2, cols2 = _greedy_match(iou_l, self.match_iou)
            lo_idx = np.where(lo)[0]
            for r, c in zip(rows2, cols2):
                det_i = int(lo_idx[r])
                t = self.tracks[remain_idx[cols2[c]]]
                self._refresh(t, dets[det_i], confs[det_i], clss[det_i])
                assigned[det_i] = t
                matched_tracks.add(remain_idx[cols2[c]])

        # ---- 未匹配高分检测 -> 新轨迹 ----
        for det_i in np.where(hi)[0]:
            if int(det_i) in assigned:
                continue
            t = _Track(self._next_id, int(clss[det_i]), dets[det_i], float(confs[det_i]))
            self._next_id += 1
            self.tracks.append(t)
            assigned[int(det_i)] = t

        # ---- 未匹配轨迹老化 / 移除 ----
        alive = []
        for i, t in enumerate(self.tracks):
            if i not in matched_tracks:
                t.age += 1
            if t.age <= self.max_age:
                alive.append(t)
        self.tracks = alive

        # ---- 输出已确认轨迹 ----
        out = []
        for det_i, t in sorted(assigned.items()):
            if not t.confirmed:
                continue
            x1, y1, x2, y2 = t.box.tolist()
            out.append((t.tid, t.cls_id, x1, y1, x2, y2, float(t.conf)))
        return out

    def _refresh(self, track, box, conf, cls_id):
        track.box = box
        track.conf = float(conf)
        track.best_conf = max(track.best_conf, float(conf))
        track.hits += 1
        track.age = 0
        if track.hits >= self.min_hits:
            track.confirmed = True
