"""Cấu hình lớp biên (Raspberry Pi): mô hình AI, cơ cấu chắn, cảm biến C2.

Mọi giá trị đọc từ biến môi trường để đổi được khi chạy thật mà không sửa mã.
Tên biến môi trường đều bắt đầu bằng GV_ cho đồng bộ với server/config.py.
"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _f(name, default):
    return float(os.environ.get(name, default))


def _i(name, default):
    return int(os.environ.get(name, default))


def _b(name, default="0"):
    return os.environ.get(name, default) == "1"


# ---------------------------------------------------------------- mô hình AI
def det_model() -> Path:
    """Thư mục NCNN của detector (plate_ncnn_model) hoặc tệp .onnx/.pt."""
    return Path(os.environ.get("GV_DET_MODEL", ROOT.parent / "models" / "plate_ncnn_model"))


def ocr_model() -> Path:
    return Path(os.environ.get("GV_OCR_MODEL", ROOT.parent / "models" / "plate_ocr.onnx"))


# imgsz phải khớp lúc xuất model: detector xuất ở [cao, rộng] = [320, 480]
DET_IMGSZ = [_i("GV_DET_H", 320), _i("GV_DET_W", 480)]
DET_CONF = _f("GV_DET_CONF", 0.60)      # model_info.json của detector: conf_threshold = 0.6
OCR_VOTES = _i("GV_OCR_VOTES", 3)       # bỏ phiếu 3 vị trí cắt dòng
AI_THREADS = _i("GV_AI_THREADS", 4)     # Pi 4 có 4 nhân

# Một lượt chỉ được coi là ĐỌC ĐƯỢC khi đủ cả ba điều kiện dưới đây.
# Đúng bằng điều kiện `sure` trong alpr_pipeline.py của nhóm AI, không tự đặt thêm.
# server/config.MIN_CONF vẫn là chốt chặn cuối ở phía nghiệp vụ; đây là chốt chặn sớm ở phía biên.
OCR_MIN_CONF = _f("GV_OCR_MIN_CONF", 0.60)
OCR_MIN_AGREE = _f("GV_OCR_MIN_AGREE", 0.99)   # 1.0 = ba phiếu cắt dòng cùng kết quả
OCR_REQUIRE_VALID = _b("GV_OCR_REQUIRE_VALID", "1")  # phải đúng khuôn biển VN

# Nhiều box trong một khung: thử lần lượt chứ không chọn cứng một box.
#   "area" - thử box to nhất trước (xe đang dừng sát thanh chắn thì biển to nhất)
#   "conf" - thử box có điểm tin cậy cao nhất trước (đúng câu chữ mục 3.3.3 của báo cáo)
# Vì box đầu trượt ba chốt chặn thì còn thử box kế tiếp, thứ tự này không quyết định kết quả.
DET_PICK = os.environ.get("GV_DET_PICK", "area")
DET_MAX_BOXES = _i("GV_DET_MAX_BOXES", 2)      # số box tối đa đem đi OCR trong một khung

# Bỏ phiếu GIỮA CÁC KHUNG (mục 3.3.5 của báo cáo; alpr_pipeline.py còn ghi TODO).
# Nút làn gửi tối đa MAX_FRAMES khung, khung nét nhất đứng đầu. Khối trung tâm đọc khung đầu
# trước; chỉ khi khung đó TRƯỢT mới đọc tiếp các khung sau, và chỉ nhận khi có ít nhất
# VOTE_MIN_FRAMES khung cho cùng một biển hợp lệ. Nhờ vậy lượt nào hôm nay đã mở chắn thì
# đường đi không đổi, chỉ những lượt đang rơi vào "chưa rõ" mới có thêm cơ hội.
MULTIFRAME = _b("GV_MULTIFRAME", "1")
MAX_FRAMES = _i("GV_MAX_FRAMES", 3)
VOTE_MIN_FRAMES = _i("GV_VOTE_MIN_FRAMES", 2)

# ---------------------------------------------------------------- cơ cấu chắn
# Hai kiểu lắp, chọn đúng kiểu đang có trên mô hình:
#   "two_way"   - servo quay tới góc mở / góc hạ rồi nhả. Mất điện thì thanh chắn đứng yên.
#   "fail_open" - lò xo/đối trọng luôn kéo thanh chắn LÊN; servo phải phát xung liên tục
#                 mới giữ được chắn hạ. Ngừng xung (mất điện, treo máy, thoát chương trình)
#                 là thanh chắn tự mở - đúng quy tắc hỏng-thì-mở trong báo cáo W3-4.
BARRIER_MODE = os.environ.get("GV_BARRIER_MODE", "two_way")

# Chân GPIO (đánh số BCM) nối tới bộ điều khiển cơ cấu chắn của từng cổng.
PIN = {"IN": _i("GV_PIN_IN", 18), "OUT": _i("GV_PIN_OUT", 19)}

# Độ rộng xung (micro giây) ứng với hai vị trí. Đo lại trên servo thật rồi chỉnh.
PULSE_OPEN = _i("GV_PULSE_OPEN", 1900)
PULSE_CLOSE = _i("GV_PULSE_CLOSE", 1000)
SERVO_TRAVEL_S = _f("GV_SERVO_TRAVEL_S", 0.6)   # thời gian servo quay hết hành trình
GPIO_BACKEND = os.environ.get("GV_GPIO", "auto")  # auto | pigpio | rpigpio | mock

# ---------------------------------------------------------------- cảm biến C2
# C2 nằm SAU thanh chắn, báo xe đã qua hẳn thì mới được hạ chắn.
#   "http" - C2 nối vào ESP32 của làn, nút gửi POST /esp32/event (đúng Bảng 5 của báo cáo)
#   "gpio" - C2 kéo dây thẳng về chân GPIO của Pi
#   "both" - nhận cả hai đường, bên nào báo trước thì tính
C2_SOURCE = os.environ.get("GV_C2_SOURCE", "http")
C2_PIN = {"IN": _i("GV_C2_PIN_IN", 23), "OUT": _i("GV_C2_PIN_OUT", 24)}
C2_ACTIVE_LOW = _b("GV_C2_ACTIVE_LOW", "1")     # E18-D80NK ngõ ra NPN: có vật cản = mức thấp

# Chờ C2 tối đa bao lâu. Quá hạn mà C2 không báo: GIỮ CHẮN Ở VỊ TRÍ MỞ và báo người trực,
# tuyệt đối không hạ theo đồng hồ (rủi ro "thanh chắn hạ trúng xe đang qua" ở mục 4.5).
C2_TIMEOUT_S = _f("GV_C2_TIMEOUT_S", 20.0)
C2_DEBOUNCE_S = _f("GV_C2_DEBOUNCE_S", 0.05)

# ---------------------------------------------------------------- vận hành
# Ảnh được ghi xuống đây TRƯỚC KHI trả mã xác nhận cho nút làn, đúng mục 3.6 của báo cáo:
# "mã xác nhận chỉ được trả về sau khi ảnh đã ghi xuống bộ nhớ". Nhờ vậy mất điện ngay sau
# khi nút nhận được mã 200 thì ảnh vẫn còn, và lúc khởi động lại sẽ được xử lý tiếp.
def spool_dir() -> Path:
    from .. import config as server_config
    return Path(os.environ.get("GV_SPOOL_DIR", server_config.data_dir() / "spool"))


QUEUE_MAX = _i("GV_QUEUE_MAX", 16)      # hàng đợi mỗi cổng; đầy thì trả 503 cho nút gửi lại
AI_CONCURRENCY = _i("GV_AI_CONCURRENCY", 1)   # chạy tuần tự để hai làn không giành 4 nhân
TIMING_CSV = os.environ.get("GV_TIMING_CSV", "")  # đặt đường dẫn để ghi số đo từng chặng
JPEG_QUALITY = _i("GV_JPEG_QUALITY", 85)

# Ánh xạ mã làn mà nút gửi lên -> cổng trong cơ sở dữ liệu của web.
GATE_ALIAS = {"IN": "IN", "VAO": "IN", "A": "IN", "OUT": "OUT", "RA": "OUT", "B": "OUT"}


def gate_of(value) -> str:
    g = str(value or "").strip().upper()
    if g not in GATE_ALIAS:
        raise ValueError(f"mã làn không hợp lệ: {value!r} (chấp nhận: {sorted(GATE_ALIAS)})")
    return GATE_ALIAS[g]
