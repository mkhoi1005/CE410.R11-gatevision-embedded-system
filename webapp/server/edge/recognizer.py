"""Khối nhận dạng: ảnh thô -> biển số + độ tin cậy.

Gồm đúng bước 3, 4 và 5 của pipeline sáu bước trong báo cáo W3-4:
  3. phát hiện vùng biển số   - YOLO26n xuất NCNN
  4. đọc ký tự               - CRNN+CTC xuất ONNX (plate_ocr.OnnxOCR)
  5. hậu xử lý và kiểm tra hợp lệ - plate_ocr.format_plate + ba chốt chặn, và bỏ phiếu
     giữa các khung ở read_frames()

Model nạp một lần khi khởi động, không nạp lại mỗi lượt xe (đúng băng ③ của Hình 3).
KHÔNG đụng gì tới model và tiền xử lý: vẫn gọi plate_ocr.OnnxOCR với đúng CROP_MARGIN = 0,06
mà bộ OCR được đánh giá cùng, không nắn thẳng, không đổi kích thước đầu vào. Mọi thứ trong
tệp này nằm NGOÀI model: chọn box nào đem đi đọc, đọc bao nhiêu khung, và xử lý kết quả.

Hàm read()/read_frames() CHẠY TRONG LUỒNG RIÊNG, không gọi trực tiếp từ vòng lặp sự kiện.
"""
import time
from collections import Counter
from dataclasses import dataclass, field

import cv2
import numpy as np

from . import config

_log = print


@dataclass
class Reading:
    plate: str | None = None          # biển được NHẬN, hoặc None nếu trượt chốt chặn
    text: str = ""                    # chuỗi đọc được, giữ cả khi trượt (để bỏ phiếu và để người trực xem)
    conf: float = 0.0                 # độ tin cậy OCR
    det_conf: float = 0.0             # độ tin cậy của bộ phát hiện
    agree: float = 0.0                # độ đồng thuận giữa 3 phiếu cắt dòng trong MỘT khung
    valid: bool = False               # đúng khuôn biển Việt Nam
    readable: bool = False            # đã được nhận
    reason: str = ""                  # vì sao không đọc được
    box: tuple | None = None          # (x1, y1, x2, y2) trong ảnh gốc
    crop: np.ndarray | None = None    # ảnh biển đã cắt, để lưu làm bằng chứng
    frames_read: int = 0              # số khung đã thực sự đem đi nhận dạng
    boxes_tried: int = 0              # số box đã thử trong khung thắng
    decided_by: str = ""              # "1 khung" | "N khung đồng thuận"
    ms: dict = field(default_factory=dict)   # thời gian từng chặng


class Recognizer:
    def __init__(self):
        self._det = None
        self._ocr = None

    # ------------------------------------------------------------ nạp model
    def load(self):
        if self._det is not None:
            return
        t = time.perf_counter()
        from ultralytics import YOLO
        from plate_ocr import OnnxOCR

        det_path, ocr_path = config.det_model(), config.ocr_model()
        if not det_path.exists():
            raise FileNotFoundError(f"không thấy model phát hiện: {det_path}")
        if not ocr_path.exists():
            raise FileNotFoundError(f"không thấy model OCR: {ocr_path}")
        self._det = YOLO(str(det_path), task="detect")
        self._ocr = OnnxOCR(str(ocr_path), threads=config.AI_THREADS)
        # chạy không một lượt cho model ấm, tránh lượt xe đầu tiên bị chậm bất thường
        self._det.predict(np.zeros((config.DET_IMGSZ[0], config.DET_IMGSZ[1], 3), np.uint8),
                          imgsz=config.DET_IMGSZ, conf=config.DET_CONF, device="cpu", verbose=False)
        self._ocr(np.zeros((112, 128, 3), np.uint8), votes=1)
        _log(f"[ai] đã nạp model trong {time.perf_counter() - t:.1f}s "
             f"(det={det_path.name}, ocr={ocr_path.name}, imgsz={config.DET_IMGSZ}, conf={config.DET_CONF})")

    # ------------------------------------------------------------ cắt biển
    @staticmethod
    def _crop(img, xyxy, margin):
        h, w = img.shape[:2]
        x1, y1, x2, y2 = xyxy
        mx, my = (x2 - x1) * margin, (y2 - y1) * margin
        return img[int(max(y1 - my, 0)):int(min(y2 + my, h)),
                   int(max(x1 - mx, 0)):int(min(x2 + mx, w))]

    # ------------------------------------------------------------ bước 3
    def _detect(self, img_bgr):
        """Trả về danh sách (box, det_conf) đã xếp theo thứ tự sẽ đem đi OCR."""
        r = self._det.predict(img_bgr, imgsz=config.DET_IMGSZ, conf=config.DET_CONF,
                              device="cpu", verbose=False)[0]
        if not len(r.boxes):
            return []
        boxes = r.boxes.xyxy.cpu().numpy()
        confs = r.boxes.conf.cpu().numpy()
        if config.DET_PICK == "conf":
            order = np.argsort(-confs)
        else:   # "area": xe đang dừng sát thanh chắn thì biển của nó to nhất khung
            area = (boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1])
            order = np.argsort(-area)
        return [(tuple(float(v) for v in boxes[k]), float(confs[k])) for k in order]

    # ------------------------------------------------------------ bước 4 + 5 trên một box
    def _read_box(self, img_bgr, box, det_conf) -> Reading:
        from plate_ocr import CROP_MARGIN
        out = Reading(box=box, det_conf=det_conf)
        out.crop = self._crop(img_bgr, box, CROP_MARGIN)
        if out.crop.size == 0:
            out.reason = "vùng biển số cắt ra rỗng"
            return out

        res = self._ocr(out.crop, votes=config.OCR_VOTES)
        out.conf = float(res.get("conf", 0.0))
        out.agree = float(res.get("agree", 1.0))
        out.valid = bool(res.get("valid", False))
        out.text = res.get("text") or res.get("raw") or ""

        # Ba chốt chặn. Trượt là chuyển người trực, KHÔNG tự mở chắn.
        # Lưu ý của nhóm AI trong alpr_pipeline.py: điểm tin cậy cao KHÔNG bảo đảm đọc đúng
        # (từng sai với conf 0,999), nên `valid` và `agree` mới là hai chốt gánh chính.
        if config.OCR_REQUIRE_VALID and not out.valid:
            out.reason = f"chuỗi đọc được không đúng khuôn biển Việt Nam ({out.text!r})"
        elif out.conf < config.OCR_MIN_CONF:
            out.reason = f"độ tin cậy {out.conf:.2f} dưới ngưỡng {config.OCR_MIN_CONF:.2f}"
        elif out.agree < config.OCR_MIN_AGREE:
            out.reason = f"ba phiếu cắt dòng không thống nhất (agree={out.agree:.2f})"
        else:
            out.plate = out.text
            out.readable = True
        return out

    # ------------------------------------------------------------ một khung
    def read(self, img_bgr) -> Reading:
        """Đọc MỘT khung ảnh. Chạy đồng bộ, tốn CPU - gọi qua asyncio.to_thread.

        Thử lần lượt tối đa DET_MAX_BOXES box; box nào qua đủ ba chốt chặn thì lấy ngay.
        Không box nào qua thì trả về box có độ tin cậy cao nhất, kèm lý do, để người trực xem.
        """
        self.load()
        t0 = time.perf_counter()
        cands = self._detect(img_bgr)
        t1 = time.perf_counter()
        det_ms = round((t1 - t0) * 1000, 1)

        if not cands:
            out = Reading(reason="không thấy biển số trong khung ảnh", frames_read=1)
            out.ms = {"detect": det_ms, "ocr": 0.0}
            return out

        best = None
        for i, (box, dc) in enumerate(cands[:max(config.DET_MAX_BOXES, 1)], start=1):
            out = self._read_box(img_bgr, box, dc)
            out.boxes_tried = i
            if out.readable:
                best = out
                break
            if best is None or out.conf > best.conf:
                best = out
        best.frames_read = 1
        best.ms = {"detect": det_ms, "ocr": round((time.perf_counter() - t1) * 1000, 1)}
        return best

    # ------------------------------------------------------------ nhiều khung
    def read_frames(self, frames) -> tuple[Reading, "np.ndarray"]:
        """Bước 5, phần bỏ phiếu giữa các khung. Trả về (kết quả, khung đã quyết định).

        Nút làn gửi các khung với khung nét nhất đứng đầu. Quy tắc:
          1. Đọc khung đầu. Qua đủ ba chốt chặn thì DỪNG - y hệt hành vi một khung.
          2. Trượt thì đọc tiếp các khung còn lại.
          3. Chỉ nhận khi có ≥ VOTE_MIN_FRAMES khung cho CÙNG một biển hợp lệ, và khung tốt
             nhất trong nhóm đó đạt ngưỡng tin cậy.

        Nhờ bước 1, lượt nào hôm nay đã mở chắn thì đường đi không đổi. Nhờ bước 3, điều kiện
        nhận ở nhánh nhiều khung NGẶT HƠN một khung đơn (phải hai khung độc lập đồng thuận),
        nên tỉ lệ ghép nhầm không tăng - chỉ giảm số lượt phải gọi người trực.
        """
        frames = [f for f in frames if f is not None][:max(config.MAX_FRAMES, 1)]
        if not frames:
            return Reading(reason="không có khung ảnh nào giải mã được"), None

        r0 = self.read(frames[0])
        if r0.readable or not config.MULTIFRAME or len(frames) == 1:
            r0.decided_by = "1 khung"
            return r0, frames[0]

        reads = [r0]
        for f in frames[1:]:
            r = self.read(f)
            reads.append(r)
            if r.readable:
                # Một khung sau tự mình qua đủ ba chốt chặn: nhận luôn, không cần bỏ phiếu.
                r.decided_by = f"khung thứ {len(reads)}"
                r.frames_read = len(reads)
                r.ms = _sum_ms(reads)
                return r, f

        # Không khung nào tự qua được -> bỏ phiếu giữa các khung
        pairs = [(i, r) for i, r in enumerate(reads) if r.valid and r.text]
        winner, used, note = None, None, ""
        if pairs:
            text, n = Counter(r.text for _, r in pairs).most_common(1)[0]
            if n >= config.VOTE_MIN_FRAMES:
                i, cand = max(((i, r) for i, r in pairs if r.text == text), key=lambda p: p[1].conf)
                if cand.conf >= config.OCR_MIN_CONF:
                    cand.plate, cand.readable, cand.reason = text, True, ""
                    cand.decided_by = f"{n} khung đồng thuận"
                    winner, used = cand, frames[i]
                else:
                    note = (f"{n} khung đồng thuận ở {text!r} nhưng độ tin cậy cao nhất "
                            f"{cand.conf:.2f} vẫn dưới ngưỡng {config.OCR_MIN_CONF:.2f}")
            else:
                texts = sorted({r.text for _, r in pairs})
                note = "các khung đọc ra kết quả khác nhau: " + ", ".join(repr(t) for t in texts)

        if winner is None:
            winner = max(reads, key=lambda r: r.conf)
            used = frames[reads.index(winner)]
            if note:
                winner.reason = note
            winner.decided_by = f"{len(reads)} khung, không khung nào đạt"

        winner.frames_read = len(reads)
        winner.ms = _sum_ms(reads)
        return winner, used


def _sum_ms(reads) -> dict:
    return {"detect": round(sum(r.ms.get("detect", 0.0) for r in reads), 1),
            "ocr": round(sum(r.ms.get("ocr", 0.0) for r in reads), 1)}


recognizer = Recognizer()


def decode_jpeg(data: bytes):
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("không giải mã được ảnh JPEG")
    return img


def decode_files(paths):
    """Đọc các tệp ảnh đã ghi trong thư mục chờ. Tệp lỗi thì bỏ qua, không làm sập cả lượt."""
    out = []
    for p in paths:
        try:
            img = cv2.imread(str(p), cv2.IMREAD_COLOR)
            if img is None:
                raise ValueError("cv2.imread trả về None")
            out.append(img)
        except Exception as e:
            _log(f"[ai] bỏ qua khung {p}: {e}")
    return out
