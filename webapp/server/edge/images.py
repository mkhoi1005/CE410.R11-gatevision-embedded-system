"""Lưu ảnh bằng chứng thật (JPEG) thay cho ảnh giả SVG của chế độ thử.

Ghi vào đúng thư mục mà server đang phục vụ (`/media/...`) nên web hiện ảnh được ngay,
không phải sửa gì ở phía web.
"""
import cv2

from .. import config as server_config
from . import config


def saver(frame_bgr, crop_bgr=None, box=None):
    """Trả về hàm make_images(event_id, plate) đúng chữ ký mà logic.process_capture cần."""

    def make_images(event_id: int, plate):
        d = server_config.data_dir() / "media" / "events" / str(event_id)
        d.mkdir(parents=True, exist_ok=True)
        q = [int(cv2.IMWRITE_JPEG_QUALITY), config.JPEG_QUALITY]

        full = frame_bgr
        if box is not None:
            full = frame_bgr.copy()
            x1, y1, x2, y2 = (int(v) for v in box)
            cv2.rectangle(full, (x1, y1), (x2, y2), (40, 200, 90), 2)
        cv2.imwrite(str(d / "full.jpg"), full, q)
        img_url = f"/media/events/{event_id}/full.jpg"

        pimg_url = None
        if crop_bgr is not None and getattr(crop_bgr, "size", 0):
            cv2.imwrite(str(d / "plate.jpg"), crop_bgr, q)
            pimg_url = f"/media/events/{event_id}/plate.jpg"
        return img_url, pimg_url

    return make_images
