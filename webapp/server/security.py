"""Băm mật khẩu và mã phiên, chỉ dùng thư viện chuẩn của Python."""
import hashlib
import hmac
import secrets

_N, _R, _P = 2 ** 14, 8, 1


def hash_password(pw: str) -> str:
    salt = secrets.token_bytes(16)
    h = hashlib.scrypt(pw.encode(), salt=salt, n=_N, r=_R, p=_P)
    return f"scrypt${salt.hex()}${h.hex()}"


def verify_password(pw: str, stored: str) -> bool:
    try:
        _, salt, h = stored.split("$")
        calc = hashlib.scrypt(pw.encode(), salt=bytes.fromhex(salt), n=_N, r=_R, p=_P)
        return hmac.compare_digest(calc.hex(), h)
    except Exception:
        return False


DUMMY = hash_password("không-dùng-để-đăng-nhập")  # so sánh giả khi không có tài khoản, để thời gian trả lời không lộ thông tin


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
