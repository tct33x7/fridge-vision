# -*- coding: utf-8 -*-
"""
检测 + 追踪（app.py 和 replay.py 共用）。

以前用 model.track(conf=0.35)：YOLO 检测完直接交给 ByteTrack，0.35 以下的框在进追踪器之前就被扔掉了。
现在拆成两步：
  1. Detector：YOLO 每帧只做检测，门槛放到 0.1，把低分框也留下（顺便取出每个框的特征向量，给带"外观"的追踪器用）；
  2. Tracker：把检测框连成轨迹、给编号。可以换不同的追踪器。
好处：同一份检测结果可以分别交给不同追踪器，比较才公平；ByteTrack 的"低分框补配"也能真正起作用
（物体被手挡住、快速移动变糊时，分数常掉到 0.35 以下）。

可选的追踪器（都用 ultralytics 自带的实现，这里只统一门槛和开关）：
  bytetrack     ByteTrack。卡尔曼滤波按"匀速运动"预测每个物体下一帧在哪（即惯性），按重叠程度（IoU）配对；
                先配高分框，没配上的轨迹再用低分框补配。
  ocsort        OC-SORT。针对"丢了又找回来"改了三处：ORU 找回时按前后两次真实看到的位置重新校正卡尔曼；
                OCM 配对时看运动方向和之前是否一致（参数 inertia，"惯性"）；OCR 用最后一次真实看到的位置再配一轮。
  ocsort-byte   OC-SORT + ByteTrack 的低分框补配。
  botsort       BoT-SORT。ByteTrack + 用稀疏光流估计"相机自己动了多少"并补偿（GMC）。相机固定时这一步理论上没用。
  botsort-flow0 BoT-SORT 关掉光流补偿（对照用：看 botsort 和 bytetrack 的差别是不是光流带来的）。
  botsort-reid  BoT-SORT + 外观特征（ReID；直接用 YOLO 自己算出的特征，不另装模型）。
  ocsort-flow   OC-SORT + 光流相机补偿（"惯性 + 光流"）。实现上是 Deep OC-SORT 关掉外观。
  deepocsort    Deep OC-SORT = OC-SORT + 光流相机补偿 + 外观特征，也就是把 OC-SORT 和 BoT-SORT 的做法合在一起。
  bytetrack-oflow / ocsort-oflow
                加"物体光流"（这里自己加的，见 ObjectFlow）：用光流量出每个物体这一帧真实移动了多少，
                代替卡尔曼按旧速度外推的预测位置。专门对付"移动太快、前后两帧的框不重叠"。

注意两种光流的区别：BoT-SORT 的光流（GMC）估计的是整个画面一起动了多少 = 相机自己的运动；
我们的相机是固定的，这一步没用。物体光流估计的是每个物体框里的点动了多少，用来预测物体下一帧在哪。
"""
from __future__ import annotations

import time

import cv2
import numpy as np

# 名字 → (ultralytics 的追踪器配置文件, 要覆盖的参数)
TRACKERS = {
    "bytetrack": ("bytetrack.yaml", {}),
    "ocsort": ("ocsort.yaml", {"use_byte": False}),
    "ocsort-byte": ("ocsort.yaml", {"use_byte": True}),
    "botsort": ("botsort.yaml", {"gmc_method": "sparseOptFlow", "with_reid": False}),
    "botsort-flow0": ("botsort.yaml", {"gmc_method": "none", "with_reid": False}),
    "botsort-reid": ("botsort.yaml", {"gmc_method": "sparseOptFlow", "with_reid": True, "model": "auto"}),
    "ocsort-flow": ("deepocsort.yaml", {"gmc_method": "sparseOptFlow", "with_reid": False, "use_byte": False}),
    "deepocsort": ("deepocsort.yaml", {"gmc_method": "sparseOptFlow", "with_reid": True, "model": "auto",
                                       "use_byte": False}),
    "bytetrack-oflow": ("bytetrack.yaml", {"object_flow": True}),
    "ocsort-oflow": ("ocsort.yaml", {"use_byte": False, "object_flow": True}),
}

DETECT_CONF = 0.1      # YOLO 检测门槛：低分框也留下，交给追踪器决定用不用


def parse_spec(spec):
    """'bytetrack' = 和以前一样只送分数 ≥ conf 的框；'bytetrack+low' = 低分框（0.1～conf）也送进去。返回 (名字, 是否用低分框)。"""
    name, _, opt = spec.partition("+")
    if name not in TRACKERS or opt not in ("", "low"):
        raise ValueError(f"不认识的追踪器 {spec}；可选：{', '.join(TRACKERS)}，名字后可加 +low")
    return name, opt == "low"


def tracker_config(name, conf=0.35, low_conf=DETECT_CONF):
    """读 ultralytics 的配置，再统一门槛：分数 ≥ conf 才能新建轨迹、参加第一轮配对；low_conf～conf 之间的只用来补配。"""
    from ultralytics.utils import YAML, IterableSimpleNamespace
    from ultralytics.utils.checks import check_yaml
    if name not in TRACKERS:
        raise ValueError(f"未知的追踪器 {name}，可选：{', '.join(TRACKERS)}")
    yaml_name, over = TRACKERS[name]
    cfg = dict(YAML.load(check_yaml(yaml_name)))
    cfg.update(over)
    cfg.update(track_high_thresh=conf, new_track_thresh=conf, track_low_thresh=low_conf)
    return IterableSimpleNamespace(**cfg)


class Tracker:
    """
    包一层 ultralytics 的追踪器。
    use_low=False：和以前一样，分数低于 conf 的框不进追踪器；
    use_low=True ：0.1～conf 的低分框也送进去（ByteTrack / BoT-SORT / ocsort-byte 会拿它们补配已有轨迹，不会用它们新建轨迹）。
    """

    def __init__(self, name="bytetrack", conf=0.35, use_low=False):
        from ultralytics.trackers.basetrack import BaseTrack
        from ultralytics.trackers.track import TRACKER_MAP
        self.name, self.conf, self.use_low = name, conf, use_low
        self.cfg = tracker_config(name, conf)
        cls = TRACKER_MAP[self.cfg.tracker_type]
        self.object_flow = bool(getattr(self.cfg, "object_flow", False))
        if self.object_flow:
            cls = with_object_flow(cls)
        self.impl = cls(args=self.cfg)
        self.needs_frame = (getattr(self.cfg, "gmc_method", "none") != "none"      # 光流（相机补偿 / 物体光流）要用整帧画面
                            or self.object_flow)
        self.needs_feats = bool(getattr(self.cfg, "with_reid", False))           # 外观特征（YOLO 自己的特征）
        self._BaseTrack = BaseTrack
        self._count = 0           # ultralytics 的编号计数器是全局的；每个追踪器自己存一份，几个追踪器可以交替跑
        self.ms, self.n = 0.0, 0
        if use_low:
            self._plain_iou_second_pass()

    def _plain_iou_second_pass(self):
        """
        低分框补配只看重叠程度（IoU），和 ByteTrack 原论文一样。
        ultralytics 默认（fuse_score=True）补配时也把"重叠 × 分数"当相似度，门槛 0.5；
        低分框的分数本来就 < conf（这里 0.35），乘完永远过不了 0.5，补配等于没开。第一轮配对不受影响。
        """
        impl, orig = self.impl, self.impl._second_association

        def second_association(*args, **kwargs):
            fuse = impl.args.fuse_score
            impl.args.fuse_score = False
            try:
                return orig(*args, **kwargs)
            finally:
                impl.args.fuse_score = fuse

        impl._second_association = second_association

    def set_conf(self, conf):
        """网页上调了置信度门槛时用。"""
        self.conf = conf
        self.impl.args.track_high_thresh = conf
        self.impl.args.new_track_thresh = conf

    def reset(self):
        self.impl.reset()
        self._count = 0

    def update(self, xyxy, conf, cls, frame=None, feats=None, shape=(720, 1280)):
        """
        xyxy (N,4)、conf (N,)、cls (N,)：YOLO 这一帧的检测（门槛 0.1）。feats (N,D)：每个框的特征（可选）。
        返回 (M,7) 数组：x1, y1, x2, y2, 编号, 分数, 类别。
        """
        from ultralytics.engine.results import Boxes
        conf = np.asarray(conf, dtype=np.float32)
        keep = conf > (DETECT_CONF if self.use_low else self.conf)
        if keep.any():
            data = np.column_stack([np.asarray(xyxy, np.float32)[keep], conf[keep],
                                    np.asarray(cls, np.float32)[keep]])
        else:
            data = np.zeros((0, 6), np.float32)
        boxes = Boxes(data, orig_shape=frame.shape[:2] if frame is not None else shape)
        f = None
        if self.needs_feats and feats is not None and len(feats):
            f = np.asarray(feats, np.float32)[keep]
        t0 = time.perf_counter()
        self._BaseTrack._count, saved = self._count, self._BaseTrack._count
        try:
            out = self.impl.update(boxes, frame if self.needs_frame else None, feats=f)
        finally:
            self._count, self._BaseTrack._count = self._BaseTrack._count, saved
        self.ms += (time.perf_counter() - t0) * 1000
        self.n += 1
        if len(out) == 0:
            return np.zeros((0, 7), np.float32)
        return np.asarray(out)[:, :7]

    @property
    def ms_per_frame(self):
        return self.ms / max(1, self.n)


class ObjectFlow:
    """
    物体光流：上一帧真实看到的每个物体框，取框中间 60% 里的角点，用 Lucas-Kanade 光流跟到这一帧，
    取位移的中位数，把卡尔曼预测的位置换成"上一帧位置 + 光流位移"（速度也换成这个位移）。

    为什么需要：卡尔曼只会按以前的速度往前推，刚出现的物体还没有速度（预测 = 原地不动）。
    物体一帧移动超过半个框宽时，预测框和新检测框几乎不重叠，配不上 → 新轨迹每帧都被丢掉、重开，
    一直到物体慢下来才连上。E02b 里 jitter1 的快速苹果就是这样漏的（YOLO 其实每帧都检测到了）。
    光流量的是这一帧的真实移动，所以快也能连上。点太少（没纹理、被挡住、出画面）时保留卡尔曼的预测。

    只用在"出生不到 young 帧"的轨迹上：老轨迹的卡尔曼已经有了靠谱的速度（惯性），
    物体被手挡住时光流会跟着手走，反而把速度改坏（E02b：mix1 里被另一只手挡住的碗就因此漏了）。
    和一条更老的同类轨迹大半重叠（重叠面积占小框 60% 以上）的新轨迹也不用：那多半是 YOLO 对同一个物体多出的一个框，
    帮它连上会变成两条轨迹一起过线、计两次（E02b：合成视频里出现过）。
    """

    def __init__(self, downscale=2, max_pts=30, min_pts=4, fb_px=2.0, young=5):
        self.ds, self.max_pts, self.min_pts, self.fb_px = downscale, max_pts, min_pts, fb_px
        self.young = young
        self.prev = None
        self.boxes = {}           # 编号 → 上一帧真实看到的框（原图坐标 xyxy）
        self.cls = {}             # 编号 → 类别
        self.used = 0             # 用光流代替了多少次预测（统计用）

    def _gray(self, img):
        g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
        if self.ds > 1:
            g = cv2.resize(g, (g.shape[1] // self.ds, g.shape[0] // self.ds), interpolation=cv2.INTER_AREA)
        return g

    def predict(self, tracks, img, frame_id=None):
        gray = self._gray(img)
        prev, self.prev = self.prev, gray
        if prev is None or prev.shape != gray.shape or not tracks or not self.boxes:
            return
        H, W = gray.shape
        start = {t.track_id: t.start_frame for t in tracks}
        sel, pts, owner = [], [], []
        for t in tracks:
            b = self.boxes.get(t.track_id)
            if b is None:
                continue                  # 上一帧没真实看到（已丢失），不用光流
            if self.young and frame_id is not None and frame_id - t.start_frame >= self.young:
                continue                  # 老轨迹：相信卡尔曼的速度（惯性）
            if any(_overlap(b, ob) > 0.6 for oid, ob in self.boxes.items()
                   if oid != t.track_id and self.cls.get(oid) == t.cls and start.get(oid, -1) < t.start_frame):
                continue                  # 和更老的同类轨迹大半重叠：多半是重复框
            x1, y1, x2, y2 = np.asarray(b, np.float32) / self.ds
            cx, cy, w, h = (x1 + x2) / 2, (y1 + y2) / 2, (x2 - x1) * 0.6, (y2 - y1) * 0.6
            xa, ya = int(max(0, cx - w / 2)), int(max(0, cy - h / 2))
            xb, yb = int(min(W, cx + w / 2)), int(min(H, cy + h / 2))
            if xb - xa < 6 or yb - ya < 6:
                continue
            p = cv2.goodFeaturesToTrack(prev[ya:yb, xa:xb], maxCorners=self.max_pts, qualityLevel=0.01, minDistance=3)
            if p is None or len(p) < self.min_pts:
                continue
            sel.append((t, b))
            pts.append(p.reshape(-1, 2) + (xa, ya))
            owner.append(np.full(len(p), len(sel) - 1))
        if not sel:
            return
        P = np.concatenate(pts).astype(np.float32).reshape(-1, 1, 2)
        owner = np.concatenate(owner)
        crit = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 20, 0.03)
        Q, st, _ = cv2.calcOpticalFlowPyrLK(prev, gray, P, None, winSize=(21, 21), maxLevel=3, criteria=crit)
        R, st2, _ = cv2.calcOpticalFlowPyrLK(gray, prev, Q, None, winSize=(21, 21), maxLevel=3, criteria=crit)
        fb = np.linalg.norm((P - R).reshape(-1, 2), axis=1)       # 正着跟过去、再倒着跟回来，差太多的点不要
        good = (st.ravel() == 1) & (st2.ravel() == 1) & (fb < self.fb_px)
        disp = (Q - P).reshape(-1, 2)
        for k, (t, b) in enumerate(sel):
            m = good & (owner == k)
            if m.sum() < self.min_pts:
                continue
            dx, dy = np.median(disp[m], axis=0) * self.ds
            t.mean[0] = (b[0] + b[2]) / 2 + dx       # 卡尔曼状态前两维是中心点，第 5、6 维是每帧的速度
            t.mean[1] = (b[1] + b[3]) / 2 + dy
            t.mean[4], t.mean[5] = dx, dy
            self.used += 1

    def remember(self, tracks):
        self.boxes = {t.track_id: t.xyxy.copy() for t in tracks}
        self.cls = {t.track_id: t.cls for t in tracks}


def _overlap(a, b):
    """重叠面积占小的那个框的比例（重复框常常是套在大框里的小框，用 IoU 会偏小）。"""
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    small = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
    return ix * iy / small if small > 0 else 0.0


def with_object_flow(base):
    """给 ultralytics 的某个追踪器类加上物体光流（在卡尔曼预测之后、第一轮配对之前修正预测位置）。"""

    class WithObjectFlow(base):
        def __init__(self, args):
            super().__init__(args)
            self.oflow = ObjectFlow()

        def _pre_first_associate(self, strack_pool, unconfirmed, img, results_high):
            super()._pre_first_associate(strack_pool, unconfirmed, img, results_high)
            if img is not None:
                self.oflow.predict(list(strack_pool) + list(unconfirmed), img, self.frame_id)

        def update(self, results, img=None, feats=None, **kwargs):
            out = super().update(results, img, feats, **kwargs)
            self.oflow.remember([t for t in self.tracked_stracks if t.frame_id == self.frame_id])
            return out

        def reset(self):
            super().reset()
            self.oflow = ObjectFlow()

    WithObjectFlow.__name__ = base.__name__ + "WithObjectFlow"
    return WithObjectFlow


class Detector:
    """YOLO 只做检测（不追踪）。with_feats=True 时顺便取出每个框的特征向量（ultralytics 给 ReID 用的同一种）。"""

    def __init__(self, model_path, device=None, imgsz=640, conf=DETECT_CONF, with_feats=False):
        from ultralytics import YOLO
        self.model = YOLO(model_path)
        self.device, self.imgsz, self.conf = device, imgsz, conf
        self.with_feats = with_feats
        self.names = self.model.names
        self._hooked = False

    def _predict(self, frame):
        return self.model.predict(frame, conf=self.conf, imgsz=self.imgsz, device=self.device, verbose=False)[0]

    def __call__(self, frame):
        """返回 xyxy (N,4)、conf (N,)、cls (N,)、feats (N,D) 或 None。"""
        r = self._predict(frame)
        if self.with_feats and not self._hooked:
            # predictor 第一次预测后才存在；在检测头上挂钩子取它的输入特征（和 ultralytics 追踪时 model=auto 一样）
            p = self.model.predictor

            def pre_hook(module, inp):
                p._feats = list(inp[0])

            p.model.model.model[-1].register_forward_pre_hook(pre_hook)
            self._hooked = True
            r = self._predict(frame)
        b = r.boxes
        xyxy = b.xyxy.cpu().numpy() if b is not None else np.zeros((0, 4), np.float32)
        conf = b.conf.cpu().numpy() if b is not None else np.zeros(0, np.float32)
        cls = b.cls.cpu().numpy().astype(np.int16) if b is not None else np.zeros(0, np.int16)
        feats = None
        if self.with_feats:
            f = getattr(r, "feats", None)
            if f is None or len(f) == 0:
                feats = np.zeros((0, 1), np.float32)
            else:
                feats = f.float().cpu().numpy() if hasattr(f, "cpu") else np.asarray(f, np.float32)
        return xyxy, conf, cls, feats


__all__ = ["TRACKERS", "DETECT_CONF", "Tracker", "Detector", "ObjectFlow", "tracker_config", "parse_spec"]
