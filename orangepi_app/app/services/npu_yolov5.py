"""
Orange Pi 4 Pro (全志 A733) NPU YOLOv5 推理器
基于 libNBGlinker.so (VIPLite / vip_lite C API) 的 Python ctypes 绑定。

模型: /opt/yolov5/model/yolov5.nb (官方镜像自带, 经典 YOLOv5s COCO 80 类)
输入: 640x640 uint8, RGB, NCHW 平面排布 (R/G/B 三平面), letterbox 黑边填充
输出: 3 个 P3/P4/P5 层 float32 原始 logits, 每层 [A=3, H, W, C=85] 内存排布,
      C = [tx, ty, tw, th, obj, cls0..cls79], 标准 v5 sigmoid 解码。

布局/格式结论来自对官方 demo 二进制的反汇编与 vpm_run 输出转储的实证校验
(dog 图解码置信度与官方 result.png 吻合: dog 0.87 / bicycle 0.49 / truck 0.54)。
"""

import ctypes
import os
import threading

import numpy as np

# ---------------------------------------------------------------------------
# vip_lite 常量 (见 /usr/include/vip_lite.h)
# ---------------------------------------------------------------------------
VIP_SUCCESS = 0

VIP_CREATE_NETWORK_FROM_FILE = 0x01

VIP_BUFFER_FORMAT_FP32 = 0
VIP_BUFFER_FORMAT_UINT8 = 2

VIP_BUFFER_QUANTIZE_NONE = 0
VIP_BUFFER_QUANTIZE_TF_ASYMM = 2

VIP_NETWORK_PROP_OUTPUT_COUNT = 2

VIP_BUFFER_PROP_NUM_OF_DIMENSION = 1
VIP_BUFFER_PROP_SIZES_OF_DIMENSION = 2
VIP_BUFFER_PROP_DATA_FORMAT = 3
VIP_BUFFER_PROP_TF_SCALE = 5
VIP_BUFFER_PROP_TF_ZERO_POINT = 6

VIP_BUFFER_OPER_TYPE_FLUSH = 1
VIP_BUFFER_OPER_TYPE_INVALIDATE = 2

_LIB_CANDIDATES = ("/lib/libNBGlinker.so", "/usr/lib/libNBGlinker.so")

# COCO 80 类
COCO_CLASSES = (
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train",
    "truck", "boat", "traffic light", "fire hydrant", "stop sign",
    "parking meter", "bench", "bird", "cat", "dog", "horse", "sheep", "cow",
    "elephant", "bear", "zebra", "giraffe", "backpack", "umbrella",
    "handbag", "tie", "suitcase", "frisbee", "skis", "snowboard",
    "sports ball", "kite", "baseball bat", "baseball glove", "skateboard",
    "surfboard", "tennis racket", "bottle", "wine glass", "cup", "fork",
    "knife", "spoon", "bowl", "banana", "apple", "sandwich", "orange",
    "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair",
    "couch", "potted plant", "bed", "dining table", "toilet", "tv",
    "laptop", "mouse", "remote", "keyboard", "cell phone", "microwave",
    "oven", "toaster", "sink", "refrigerator", "book", "clock", "vase",
    "scissors", "teddy bear", "hair drier", "toothbrush",
)

# 每层 (anchor 数固定 3): feat_h -> (stride, anchors[(aw,ah)x3])
ANCHORS = {
    80: (8, ((10, 13), (16, 30), (33, 23))),
    40: (16, ((30, 61), (62, 45), (59, 119))),
    20: (32, ((116, 90), (156, 198), (373, 326))),
}


class _BufferCreateParams(ctypes.Structure):
    """对应 C 的 vip_buffer_create_params_t (48 字节)"""
    _fields_ = [
        ("num_of_dims", ctypes.c_uint32),
        ("sizes", ctypes.c_uint32 * 6),
        ("data_format", ctypes.c_uint32),
        ("quant_format", ctypes.c_uint32),
        ("scale", ctypes.c_float),        # union quant_data.affine
        ("zero_point", ctypes.c_int32),
        ("memory_type", ctypes.c_uint32),
    ]


def _sigmoid(x):
    return 1.0 / (1.0 + np.exp(-x))


class NpuYolov5Error(RuntimeError):
    pass


class NpuYolov5:
    """线程安全的单模型推理器 (推理本身由调用方串行; 互斥锁防 ctypes 竞争)"""

    def __init__(self, model_path="/opt/yolov5/model/yolov5.nb",
                 conf_threshold=0.30, iou_threshold=0.45,
                 lib_path=None):
        self.conf_threshold = conf_threshold
        self.iou_threshold = iou_threshold
        self._lock = threading.Lock()

        lib = lib_path or next((p for p in _LIB_CANDIDATES if os.path.exists(p)), None)
        if not lib:
            raise NpuYolov5Error("找不到 libNBGlinker.so (NPU 驱动库)")
        self._lib = ctypes.CDLL(lib, mode=ctypes.RTLD_GLOBAL)
        self._bind_symbols()

        self._init_lib()
        self._net = None
        self._input_buf = self._output_bufs = None
        self._create_network(model_path)
        self._prepare_buffers()
        self._class_names = COCO_CLASSES

    # ------------------------------------------------------------------ C API
    def _bind_symbols(self):
        L = self._lib
        L.vip_init.restype = ctypes.c_int
        L.vip_destroy.restype = ctypes.c_int
        L.vip_create_network.argtypes = [ctypes.c_void_p, ctypes.c_uint32,
                                         ctypes.c_int, ctypes.POINTER(ctypes.c_void_p)]
        L.vip_create_network.restype = ctypes.c_int
        L.vip_destroy_network.argtypes = [ctypes.c_void_p]
        L.vip_destroy_network.restype = ctypes.c_int
        L.vip_prepare_network.argtypes = [ctypes.c_void_p]
        L.vip_prepare_network.restype = ctypes.c_int
        L.vip_finish_network.argtypes = [ctypes.c_void_p]
        L.vip_finish_network.restype = ctypes.c_int
        L.vip_query_network.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
        L.vip_query_network.restype = ctypes.c_int
        L.vip_query_input.argtypes = [ctypes.c_void_p, ctypes.c_uint32,
                                      ctypes.c_int, ctypes.c_void_p]
        L.vip_query_input.restype = ctypes.c_int
        L.vip_query_output.argtypes = [ctypes.c_void_p, ctypes.c_uint32,
                                       ctypes.c_int, ctypes.c_void_p]
        L.vip_query_output.restype = ctypes.c_int
        L.vip_create_buffer.argtypes = [ctypes.POINTER(_BufferCreateParams),
                                        ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p)]
        L.vip_create_buffer.restype = ctypes.c_int
        L.vip_destroy_buffer.argtypes = [ctypes.c_void_p]
        L.vip_destroy_buffer.restype = ctypes.c_int
        L.vip_map_buffer.argtypes = [ctypes.c_void_p]
        L.vip_map_buffer.restype = ctypes.c_void_p
        L.vip_flush_buffer.argtypes = [ctypes.c_void_p, ctypes.c_int]
        L.vip_flush_buffer.restype = ctypes.c_int
        L.vip_set_input.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p]
        L.vip_set_input.restype = ctypes.c_int
        L.vip_set_output.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p]
        L.vip_set_output.restype = ctypes.c_int
        L.vip_run_network.argtypes = [ctypes.c_void_p]
        L.vip_run_network.restype = ctypes.c_int

    @staticmethod
    def _check(status, what):
        if status != VIP_SUCCESS:
            raise NpuYolov5Error(f"{what} 失败: status={status}")

    def _init_lib(self):
        self._check(self._lib.vip_init(), "vip_init")

    def _create_network(self, model_path):
        net = ctypes.c_void_p()
        path = model_path.encode()
        self._check(self._lib.vip_create_network(path, 0, VIP_CREATE_NETWORK_FROM_FILE,
                                                 ctypes.byref(net)), "vip_create_network")
        self._net = net
        self._check(self._lib.vip_prepare_network(net), "vip_prepare_network")

    def _query_buf_info(self, query_fn, index):
        """返回 (dims 列表, data_format, scale, zero_point, 元素数)"""
        n_dim = ctypes.c_uint32()
        self._check(query_fn(self._net, index, VIP_BUFFER_PROP_NUM_OF_DIMENSION,
                             ctypes.byref(n_dim)), "query NUM_OF_DIMENSION")
        dims = (ctypes.c_uint32 * 6)()
        self._check(query_fn(self._net, index, VIP_BUFFER_PROP_SIZES_OF_DIMENSION,
                             ctypes.cast(dims, ctypes.c_void_p)), "query SIZES")
        fmt = ctypes.c_uint32()
        self._check(query_fn(self._net, index, VIP_BUFFER_PROP_DATA_FORMAT,
                             ctypes.byref(fmt)), "query DATA_FORMAT")
        scale = ctypes.c_float()
        zp = ctypes.c_uint32()
        query_fn(self._net, index, VIP_BUFFER_PROP_TF_SCALE, ctypes.byref(scale))
        query_fn(self._net, index, VIP_BUFFER_PROP_TF_ZERO_POINT, ctypes.byref(zp))
        dim_list = [dims[i] for i in range(n_dim.value)]
        count = 1
        for d in dim_list:
            count *= d
        return dim_list, fmt.value, scale.value, zp.value, count

    def _make_buffer(self, dims, data_format, quant_format, scale, zero_point):
        params = _BufferCreateParams()
        params.num_of_dims = len(dims)
        for i, d in enumerate(dims):
            params.sizes[i] = d
        params.data_format = data_format
        params.quant_format = quant_format
        params.scale = scale
        params.zero_point = zero_point
        params.memory_type = 0
        buf = ctypes.c_void_p()
        self._check(self._lib.vip_create_buffer(ctypes.byref(params),
                                                ctypes.sizeof(params),
                                                ctypes.byref(buf)), "vip_create_buffer")
        return buf

    def _prepare_buffers(self):
        # ---- 输入: 640x640x3 uint8 (dim 顺序原样使用驱动返回值) ----
        in_dims, in_fmt, in_scale, in_zp, in_count = self._query_buf_info(
            self._lib.vip_query_input, 0)
        self._input_dims = in_dims
        if in_fmt != VIP_BUFFER_FORMAT_UINT8:
            raise NpuYolov5Error(f"意外输入格式 {in_fmt}, 期望 uint8")
        self._input_count = in_count  # 640*640*3
        self._input_buf = self._make_buffer(in_dims, in_fmt,
                                            VIP_BUFFER_QUANTIZE_TF_ASYMM, in_scale, in_zp)
        self._check(self._lib.vip_set_input(self._net, 0, self._input_buf), "vip_set_input")
        ptr = self._lib.vip_map_buffer(self._input_buf)
        self._input_arr = np.ctypeslib.as_array(
            ctypes.cast(ptr, ctypes.POINTER(ctypes.c_uint8)), shape=(in_count,))

        # ---- 输出: 每个输出一个 FP32 buffer ----
        n_out = ctypes.c_uint32()
        self._check(self._lib.vip_query_network(
            self._net, VIP_NETWORK_PROP_OUTPUT_COUNT, ctypes.byref(n_out)),
            "query OUTPUT_COUNT")
        self._output_bufs = []
        self._output_arrs = []
        self._output_shapes = []
        for i in range(n_out.value):
            o_dims, o_fmt, _, _, o_count = self._query_buf_info(
                self._lib.vip_query_output, i)
            if o_fmt != VIP_BUFFER_FORMAT_FP32:
                raise NpuYolov5Error(f"意外输出格式 {o_fmt}, 期望 fp32")
            buf = self._make_buffer(o_dims, o_fmt, VIP_BUFFER_QUANTIZE_NONE, 0.0, 0)
            self._check(self._lib.vip_set_output(self._net, i, buf), "vip_set_output")
            p = self._lib.vip_map_buffer(buf)
            arr = np.ctypeslib.as_array(
                ctypes.cast(p, ctypes.POINTER(ctypes.c_float)), shape=(o_count,))
            self._output_bufs.append(buf)
            self._output_arrs.append(arr)
            # 驱动声明序 dims = [C=85, W, H, A=3, 1]; 内存语义布局为 [A=3, H, W, C=85]
            filtered = tuple(d for d in o_dims if d != 1)   # (85, W, H, 3)
            if len(filtered) == 4 and filtered[0] == 85 and filtered[3] == 3:
                self._output_shapes.append(tuple(reversed(filtered)))  # (3,H,W,85)
            else:
                self._output_shapes.append(None)      # 未知布局, 跳过该层

    # ------------------------------------------------------------------ 推理
    @staticmethod
    def _letterbox_rgb_planar(bgr, size=640):
        """BGR 帧 -> RGB letterbox 640x640 -> NCHW uint8 平面; 返回 (planar, scale, pad_x, pad_y)"""
        h, w = bgr.shape[:2]
        s = min(size / w, size / h)
        nw, nh = int(round(w * s)), int(round(h * s))
        r = cv2_resize(bgr, nw, nh)
        canvas = np.zeros((size, size, 3), dtype=np.uint8)
        pad_x, pad_y = (size - nw) // 2, (size - nh) // 2
        canvas[pad_y:pad_y + nh, pad_x:pad_x + nw] = r
        rgb = canvas[:, :, ::-1]  # BGR->RGB (canvas 目前是 BGR)
        planar = np.ascontiguousarray(rgb.transpose(2, 0, 1))  # (3,640,640)
        return planar, s, pad_x, pad_y

    def infer(self, bgr):
        """输入 BGR ndarray, 返回检测列表 [(x1,y1,x2,y2,conf,cls_id,cls_name), ...] 原图坐标"""
        planar, s, pad_x, pad_y = self._letterbox_rgb_planar(bgr)
        with self._lock:
            self._input_arr[:] = planar.ravel()
            self._lib.vip_flush_buffer(self._input_buf, VIP_BUFFER_OPER_TYPE_FLUSH)
            self._check(self._lib.vip_run_network(self._net), "vip_run_network")
            for buf in self._output_bufs:
                self._lib.vip_flush_buffer(buf, VIP_BUFFER_OPER_TYPE_INVALIDATE)

            raw_boxes = []
            for arr, shape in zip(self._output_arrs, self._output_shapes):
                if shape is None:
                    continue
                raw_boxes.extend(self._decode_level(arr, shape[1]))

        boxes = self._nms(raw_boxes)
        # letterbox 坐标 -> 原图坐标
        out = []
        for x1, y1, x2, y2, conf, cls_id in boxes:
            out.append((
                (x1 - pad_x) / s, (y1 - pad_y) / s,
                (x2 - pad_x) / s, (y2 - pad_y) / s,
                conf, cls_id, COCO_CLASSES[cls_id],
            ))
        return out

    def _decode_level(self, arr, hh):
        """单层解码: 内存布局 [3, H, W, 85], 向量 v = a*H*W + y*W + x"""
        stride, anchors = ANCHORS[hh]
        V = arr.reshape(3 * hh * hh, 85)
        obj = _sigmoid(V[:, 4])
        cls = V[:, 5:85]
        cls_id = cls.argmax(1)
        cls_conf = _sigmoid(cls[np.arange(len(V)), cls_id])
        conf = obj * cls_conf
        cand = np.where(conf > self.conf_threshold)[0]

        boxes = []
        for v in cand:
            a, cell = divmod(int(v), hh * hh)
            gy, gx = divmod(cell, hh)
            t = V[v]
            bx = (2.0 * _sigmoid(t[0]) - 0.5 + gx) * stride
            by = (2.0 * _sigmoid(t[1]) - 0.5 + gy) * stride
            bw = (2.0 * _sigmoid(t[2])) ** 2 * anchors[a][0]
            bh = (2.0 * _sigmoid(t[3])) ** 2 * anchors[a][1]
            boxes.append((bx - bw / 2, by - bh / 2, bx + bw / 2, by + bh / 2,
                          float(conf[v]), int(cls_id[v])))
        return boxes

    def _nms(self, boxes):
        """按类别 NMS"""
        boxes = sorted(boxes, key=lambda b: -b[4])
        keep = []
        for b in boxes:
            ok = True
            for k in keep:
                if k[5] != b[5]:
                    continue
                ix = max(0.0, min(b[2], k[2]) - max(b[0], k[0]))
                iy = max(0.0, min(b[3], k[3]) - max(b[1], k[1]))
                inter = ix * iy
                uni = (b[2] - b[0]) * (b[3] - b[1]) + (k[2] - k[0]) * (k[3] - k[1]) - inter
                if uni > 0 and inter / uni > self.iou_threshold:
                    ok = False
                    break
            if ok:
                keep.append(b)
        return keep

    # ------------------------------------------------------------------ 清理
    def close(self):
        with self._lock:
            if self._net is not None:
                self._lib.vip_finish_network(self._net)
                self._lib.vip_destroy_network(self._net)
                self._net = None
            for buf in (self._output_bufs or []):
                self._lib.vip_destroy_buffer(buf)
            self._output_bufs = []
            if self._input_buf is not None:
                self._lib.vip_destroy_buffer(self._input_buf)
                self._input_buf = None
            self._lib.vip_destroy()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def cv2_resize(bgr, nw, nh):
    """独立小函数, 便于无 cv2 环境替换实现"""
    import cv2
    return cv2.resize(bgr, (nw, nh), interpolation=cv2.INTER_LINEAR)
