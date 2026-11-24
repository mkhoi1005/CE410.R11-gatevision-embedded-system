"""Điều khiển thanh chắn của một cổng, kèm quy tắc an toàn của báo cáo W3-4.

Hai quy tắc bắt buộc, cài thẳng vào đây chứ không để người gọi tự nhớ:

1. CHỈ HẠ KHI CẢM BIẾN C2 BÁO XE ĐÃ QUA HẲN, không bao giờ hạ theo đồng hồ đếm ngược.
   Quá thời gian chờ mà C2 im lặng thì GIỮ NGUYÊN Ở VỊ TRÍ MỞ và báo người trực
   (mục 4.5 - rủi ro "thanh chắn hạ trúng xe đang qua").

2. HỎNG THÌ MỞ. Ở kiểu lắp fail_open, giữ chắn hạ cần phát xung liên tục, nên mọi đường
   thoát của chương trình (thoát bình thường, Ctrl-C, SIGTERM, lỗi không bắt được) đều
   ngừng xung -> lò xo kéo thanh chắn lên. Ở kiểu two_way thì phần cứng không làm được
   điều này, chương trình chỉ cố nâng lên trước khi tắt.
"""
import asyncio
import atexit
import signal
import threading

from . import config, gpio

_log = print
_PULSE_RELEASE = 0


class Barrier:
    def __init__(self, gate: str):
        self.gate = gate
        self.pin = config.PIN[gate]
        self.mode = config.BARRIER_MODE
        self.is_open = False
        self._lock = asyncio.Lock()          # mỗi cổng chỉ phục vụ một lượt tại một thời điểm
        self._c2 = asyncio.Event()
        self._loop = None
        self._late_task = None
        self._release_timer = None

    # ------------------------------------------------------------ mức thấp
    def _drive(self, pulse_us: int):
        # Huỷ hẹn nhả còn treo lại: lệnh mới luôn thắng lệnh cũ, tránh một hẹn nhả của
        # lượt trước cắt ngang xung của lượt sau.
        if self._release_timer is not None:
            self._release_timer.cancel()
            self._release_timer = None
        gpio.backend().servo(self.pin, pulse_us)

    def _release_after(self, delay: float):
        self._release_timer = threading.Timer(delay, lambda: self._drive(_PULSE_RELEASE))
        self._release_timer.daemon = True
        self._release_timer.start()

    def rest(self):
        """Đưa về trạng thái nghỉ lúc khởi động: thanh chắn hạ."""
        self._drive(config.PULSE_CLOSE)
        if self.mode != "fail_open":
            # kiểu two_way: quay xong thì nhả cho servo nguội. Kiểu fail_open phải giữ xung
            # liên tục, ngừng xung là lò xo kéo thanh chắn lên.
            self._release_after(config.SERVO_TRAVEL_S)
        self.is_open = False

    def release_fail_open(self):
        """Ngừng xung. Ở kiểu fail_open đây chính là MỞ thanh chắn."""
        self._drive(_PULSE_RELEASE)
        if self.mode == "fail_open":
            self.is_open = True

    # ------------------------------------------------------------ mở / hạ
    # is_open bật NGAY khi bắt đầu nâng và chỉ tắt KHI ĐÃ HẠ XONG, nên suốt lúc thanh chắn
    # còn chuyển động hoặc còn đang mở thì /esp32/command đều báo "đang mở" - nút làn không
    # bao giờ thấy trạng thái "đã hạ" trong khi thanh chắn còn dựng lên.
    async def open(self):
        self.is_open = True
        _log(f"[barrier:{self.gate}] MỞ")
        if self.mode == "fail_open":
            self._drive(_PULSE_RELEASE)          # nhả ra, lò xo nâng thanh chắn
        else:
            self._drive(config.PULSE_OPEN)
            await asyncio.sleep(config.SERVO_TRAVEL_S)
            self._drive(_PULSE_RELEASE)

    async def close(self):
        self._drive(config.PULSE_CLOSE)
        if self.mode != "fail_open":             # fail_open phải giữ xung mới ghìm được chắn
            await asyncio.sleep(config.SERVO_TRAVEL_S)
            self._drive(_PULSE_RELEASE)
        self.is_open = False
        _log(f"[barrier:{self.gate}] HẠ")

    # ------------------------------------------------------------ cảm biến C2
    def bind_loop(self, loop):
        self._loop = loop

    def c2_passed(self):
        """Gọi được từ bất kỳ luồng nào (callback GPIO) hoặc từ endpoint HTTP."""
        if self._loop is not None and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(self._c2.set)
        else:
            self._c2.set()

    async def _wait_c2(self, timeout: float) -> bool:
        try:
            await asyncio.wait_for(self._c2.wait(), timeout)
            return True
        except asyncio.TimeoutError:
            return False

    # ------------------------------------------------------------ một lượt xe
    async def pass_vehicle(self, on_timeout=None) -> str:
        """Mở chắn, chờ C2 báo xe đã qua rồi hạ.

        Trả về: "OK" (xe đã qua, đã hạ) | "C2_TIMEOUT" (giữ mở, đã báo người trực).
        """
        async with self._lock:
            self._c2.clear()
            await self.open()
            if await self._wait_c2(config.C2_TIMEOUT_S):
                await self.close()
                return "OK"

            _log(f"[barrier:{self.gate}] C2 không báo sau {config.C2_TIMEOUT_S:.0f}s -> GIỮ MỞ, báo người trực")
            if on_timeout:
                try:
                    on_timeout(self.gate)
                except Exception as e:
                    _log(f"[barrier:{self.gate}] lỗi khi tạo cảnh báo: {e}")
            # C2 có thể báo muộn (xe dừng lâu giữa cổng) - vẫn hạ khi nhận được, không bỏ cuộc.
            self._late_task = asyncio.create_task(self._close_when_c2())
            return "C2_TIMEOUT"

    async def _close_when_c2(self):
        await self._c2.wait()
        _log(f"[barrier:{self.gate}] C2 báo muộn -> hạ chắn")
        await self.close()


# ================================================================== quản lý chung
_barriers: dict = {}


def get(gate: str) -> Barrier:
    if gate not in _barriers:
        _barriers[gate] = Barrier(gate)
    return _barriers[gate]


def all_() -> dict:
    return _barriers


def start(loop, on_c2_gpio_ready=None):
    """Khởi tạo hai cổng, đưa thanh chắn về vị trí hạ, gắn cảm biến C2 nếu đọc bằng GPIO."""
    for gate in ("IN", "OUT"):
        b = get(gate)
        b.bind_loop(loop)
        b.rest()
    if config.C2_SOURCE in ("gpio", "both"):
        for gate in ("IN", "OUT"):
            pin = config.C2_PIN[gate]
            try:
                gpio.backend().watch_input(pin, config.C2_ACTIVE_LOW, get(gate).c2_passed)
                _log(f"[barrier:{gate}] đọc C2 trực tiếp ở chân GPIO {pin}")
            except Exception as e:
                _log(f"[barrier:{gate}] không gắn được C2 ở chân {pin}: {e}")
    if on_c2_gpio_ready:
        on_c2_gpio_ready()
    install_failopen_guard()


def panic_open():
    """Nhả toàn bộ servo. Ở kiểu fail_open là mở hết thanh chắn."""
    for gate, pin in config.PIN.items():
        try:
            if config.BARRIER_MODE == "fail_open":
                gpio.backend().servo(pin, _PULSE_RELEASE)
            else:
                gpio.backend().servo(pin, config.PULSE_OPEN)   # cố nâng lên trước khi tắt
        except Exception:
            pass
    _log("[barrier] đã nhả toàn bộ cơ cấu chắn (hỏng-thì-mở)")


_guard_done = False


def install_failopen_guard():
    global _guard_done
    if _guard_done:
        return
    _guard_done = True
    atexit.register(panic_open)
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            prev = signal.getsignal(sig)

            def handler(s, f, _prev=prev):
                panic_open()
                if callable(_prev):
                    _prev(s, f)
                else:
                    raise SystemExit(0)

            signal.signal(sig, handler)
        except (ValueError, OSError):
            pass      # không ở luồng chính thì bỏ qua, atexit vẫn còn
