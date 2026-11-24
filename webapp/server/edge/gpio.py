"""Lớp bọc GPIO: pigpio -> RPi.GPIO -> giả lập.

pigpio được ưu tiên vì xung servo do phần cứng tạo, không bị giật khi CPU bận chạy AI.
Khi không chạy trên Pi (máy tính của nhóm lúc viết code) sẽ tự dùng bản giả lập,
in ra màn hình thay vì xuất xung, nhờ vậy chạy thử được toàn bộ luồng mà không cần phần cứng.
"""
import threading
import time

from . import config

_log = print


class _Base:
    name = "?"

    def servo(self, pin: int, pulse_us: int):
        """pulse_us = 0 nghĩa là NGỪNG phát xung (nhả servo)."""
        raise NotImplementedError

    def watch_input(self, pin: int, active_low: bool, callback):
        """Gọi callback() mỗi khi chân vào chuyển sang mức tích cực."""
        raise NotImplementedError

    def close(self):
        pass


class _Pigpio(_Base):
    name = "pigpio"

    def __init__(self):
        import pigpio
        self.pi = pigpio.pi()
        if not self.pi.connected:
            raise RuntimeError("pigpio daemon chưa chạy (sudo systemctl start pigpiod)")
        self._pigpio = pigpio

    def servo(self, pin, pulse_us):
        self.pi.set_servo_pulsewidth(pin, int(pulse_us))

    def watch_input(self, pin, active_low, callback):
        p = self._pigpio
        self.pi.set_mode(pin, p.INPUT)
        self.pi.set_pull_up_down(pin, p.PUD_UP if active_low else p.PUD_DOWN)
        edge = p.FALLING_EDGE if active_low else p.RISING_EDGE
        self.pi.set_glitch_filter(pin, int(config.C2_DEBOUNCE_S * 1_000_000))
        return self.pi.callback(pin, edge, lambda *_: callback())

    def close(self):
        for pin in config.PIN.values():
            try:
                self.pi.set_servo_pulsewidth(pin, 0)   # nhả servo = fail-open
            except Exception:
                pass
        self.pi.stop()


class _RpiGpio(_Base):
    name = "RPi.GPIO"

    def __init__(self):
        import RPi.GPIO as G
        self.G = G
        G.setmode(G.BCM)
        G.setwarnings(False)
        self._pwm = {}

    def servo(self, pin, pulse_us):
        if pulse_us <= 0:
            if pin in self._pwm:
                self._pwm.pop(pin).stop()
            return
        duty = pulse_us / 20000.0 * 100.0          # chu kỳ 20 ms = 50 Hz
        if pin not in self._pwm:
            self.G.setup(pin, self.G.OUT)
            pwm = self.G.PWM(pin, 50)
            pwm.start(duty)
            self._pwm[pin] = pwm
        else:
            self._pwm[pin].ChangeDutyCycle(duty)

    def watch_input(self, pin, active_low, callback):
        G = self.G
        G.setup(pin, G.IN, pull_up_down=G.PUD_UP if active_low else G.PUD_DOWN)
        G.add_event_detect(pin, G.FALLING if active_low else G.RISING,
                           callback=lambda *_: callback(), bouncetime=int(config.C2_DEBOUNCE_S * 1000))

    def close(self):
        for pin, pwm in list(self._pwm.items()):
            try:
                pwm.stop()
            except Exception:
                pass
        self._pwm.clear()
        try:
            self.G.cleanup()
        except Exception:
            pass


class _Mock(_Base):
    """Không có phần cứng: in trạng thái ra màn hình. Đủ để chạy thử toàn bộ luồng."""
    name = "mock"

    def __init__(self):
        self.state = {}
        self._handlers = {}

    def servo(self, pin, pulse_us):
        self.state[pin] = pulse_us
        _log(f"[gpio-mock] chân {pin}: xung {pulse_us} us" + ("  (nhả - thanh chắn tự mở)" if pulse_us == 0 else ""))

    def watch_input(self, pin, active_low, callback):
        self._handlers[pin] = callback

    def fire(self, pin):
        """Dùng trong kịch bản thử: giả lập cảm biến ở chân `pin` kích hoạt."""
        if pin in self._handlers:
            self._handlers[pin]()


_backend = None
_lock = threading.Lock()


def backend() -> _Base:
    global _backend
    with _lock:
        if _backend is not None:
            return _backend
        want = config.GPIO_BACKEND
        order = {"pigpio": [_Pigpio], "rpigpio": [_RpiGpio], "mock": [_Mock]}.get(want, [_Pigpio, _RpiGpio, _Mock])
        for cls in order:
            try:
                _backend = cls()
                _log(f"[gpio] dùng {_backend.name}")
                return _backend
            except Exception as e:
                _log(f"[gpio] {cls.name} không dùng được: {type(e).__name__}: {e}")
        _backend = _Mock()
        return _backend


def close():
    global _backend
    with _lock:
        if _backend is not None:
            _backend.close()
            _backend = None


def now() -> float:
    return time.monotonic()
