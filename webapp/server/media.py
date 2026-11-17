"""Ảnh giả (hình học) cho chế độ thử. Ảnh thật từ ESP32 sẽ là .jpg do endpoint chụp ghi vào cùng thư mục."""
from html import escape

from . import config

MONO = 'font-family="Consolas,Menlo,monospace" font-weight="700" text-anchor="middle" fill="#1d2a30"'


def _parts(plate: str):
    m = str(plate).split("-")
    b = "".join(m[1:])
    if len(b) == 5 and b.isdigit():
        b = b[:3] + "." + b[3:]
    return m[0], b


def _plate_group(plate: str, x=0, y=0) -> str:
    a, b = _parts(plate)
    return (f'<g transform="translate({x},{y})"><rect x="3" y="3" width="184" height="134" rx="10" fill="#fff" stroke="#1d2a30" stroke-width="5"/>'
            f'<text x="95" y="62" font-size="46" {MONO}>{escape(a)}</text><text x="95" y="118" font-size="50" {MONO}>{escape(b)}</text></g>')


def plate_svg(plate: str) -> str:
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 190 140">{_plate_group(plate)}</svg>'


def frame_svg(plate, seed: int) -> str:
    h = 190 + (seed * 37) % 50
    if plate == "IDLE":
        body = '<text x="320" y="250" text-anchor="middle" font-size="22" fill="#9fb0b8" font-family="Segoe UI,Arial,sans-serif">Chưa có xe</text>'
    elif plate:
        body = _plate_group(plate, 225, 215)
    else:
        body = ('<g transform="translate(225,215)"><rect x="3" y="3" width="184" height="134" rx="10" fill="#c9d1d5" opacity=".55" stroke="#8fa0a8" stroke-width="5"/>'
                '<text x="95" y="92" text-anchor="middle" font-size="44" fill="#6b7780" font-family="Segoe UI,Arial,sans-serif">?</text></g>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 480"><defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1">'
            f'<stop offset="0" stop-color="hsl({h},14%,30%)"/><stop offset="1" stop-color="hsl({h},14%,17%)"/></linearGradient></defs>'
            f'<rect width="640" height="480" fill="url(#g)"/><rect y="360" width="640" height="120" fill="#0f1a1e" opacity=".5"/>{body}</svg>')


def write_idle():
    p = config.data_dir() / "media" / "idle.svg"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(frame_svg("IDLE", 0), encoding="utf-8")


def fake_images(event_id: int, plate):
    """Tạo ảnh giả cho một lượt chụp, trả (image_url, plate_image_url)."""
    d = config.data_dir() / "media" / "events" / str(event_id)
    d.mkdir(parents=True, exist_ok=True)
    (d / "full.svg").write_text(frame_svg(plate, event_id), encoding="utf-8")
    img = f"/media/events/{event_id}/full.svg"
    pimg = None
    if plate:
        (d / "plate.svg").write_text(plate_svg(plate), encoding="utf-8")
        pimg = f"/media/events/{event_id}/plate.svg"
    return img, pimg
