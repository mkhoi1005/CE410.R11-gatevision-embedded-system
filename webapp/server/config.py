"""Cấu hình đọc từ biến môi trường (đọc lúc dùng, để dễ thử nghiệm).
Không có cấu hình nào ở đây là bí mật; mật khẩu không bao giờ để trong file này."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def dev() -> bool:
    """GV_DEV=1: bật dữ liệu mẫu, tài khoản thử và công cụ mô phỏng. KHÔNG bật khi chạy thật."""
    return os.environ.get("GV_DEV") == "1"


def web_dir() -> Path:
    return Path(os.environ.get("GV_WEB_DIR", ROOT.parent / "web"))


def data_dir() -> Path:
    return Path(os.environ.get("GV_DATA_DIR", ROOT / "data"))


def hold_max_s() -> int:
    return int(os.environ.get("GV_HOLD_MAX_S", "120"))  # ĐỀ XUẤT - CẦN XÁC NHẬN (Q10)


MIN_CONF = 0.6              # dưới ngưỡng này coi như không đọc được biển. ĐỀ XUẤT - CẦN XÁC NHẬN
SESSION_TTL_S = 12 * 3600   # cookie đăng nhập sống 12 giờ. ĐỀ XUẤT
LOGIN_MAX_FAILS = 5         # sai quá 5 lần trong LOGIN_WINDOW_S thì khóa tạm. ĐỀ XUẤT
LOGIN_WINDOW_S = 300
OFFLINE_AFTER_S = 30        # không có heartbeat quá lâu thì coi thiết bị mất kết nối. ĐỀ XUẤT
COOKIE_NAME = "gv_session"
