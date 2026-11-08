"""pi_infer.py - phát hiện biển số trên Raspberry Pi 4 (Raspberry Pi OS 64-bit, Python 3.9+).

Cài đặt:   pip install ultralytics ncnn opencv-python-headless
Chạy thử:  python pi_infer.py --model plate_ncnn_model --source ./anh_thu --save-crops ./crops
           python pi_infer.py --model plate_ncnn_model --source http://<IP_ESP32_CAM>:81/stream --save-crops ./crops
"""
import argparse, time
from pathlib import Path
import cv2
from ultralytics import YOLO

CONF_DEFAULT = 0.60          # ngưỡng tối ưu theo F1 trên tập val
IMGSZ = [320, 480]               # [cao, rong] hoac so nguyen; phai khop voi luc xuat model
CROP_MARGIN = 0.08              # nới box 8% mỗi phía để OCR không bị cắt mất ký tự sát mép
IMG_EXTS = {".jpg", ".jpeg", ".png", ".bmp"}


def crop_with_margin(img, xyxy, margin=CROP_MARGIN):
    h, w = img.shape[:2]
    x1, y1, x2, y2 = xyxy
    mx, my = (x2 - x1) * margin, (y2 - y1) * margin
    x1, y1, x2, y2 = int(max(x1 - mx, 0)), int(max(y1 - my, 0)), int(min(x2 + mx, w)), int(min(y2 + my, h))
    return img[y1:y2, x1:x2]


def read_plate_text(crop):
    # TODO: chưa cài OCR. Dataset GreenParking không có nhãn ký tự nên notebook này chỉ train bộ PHÁT HIỆN biển.
    # Gắn bộ OCR nhẹ (chạy trên ảnh crop) vào đây, ví dụ model OCR biển số đã train riêng hoặc OCR chạy CPU.
    return None


def frames(source):
    p = Path(source)
    if p.is_dir() or p.suffix.lower() in IMG_EXTS:
        files = sorted(q for q in p.iterdir() if q.suffix.lower() in IMG_EXTS) if p.is_dir() else [p]
        for f in files:
            yield f.name, cv2.imread(str(f))
    else:                                    # luồng video / MJPEG của ESP32-CAM / webcam
        cap = cv2.VideoCapture(int(source) if source.isdigit() else source)
        i = 0
        while cap.isOpened():
            ok, frm = cap.read()
            if not ok:
                break
            yield f"frame_{i:06d}", frm; i += 1
        cap.release()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--source", required=True)
    ap.add_argument("--conf", type=float, default=CONF_DEFAULT)
    ap.add_argument("--save-crops", default="")
    a = ap.parse_args()

    model = YOLO(a.model, task="detect")
    if a.save_crops:
        Path(a.save_crops).mkdir(parents=True, exist_ok=True)
    for name, img in frames(a.source):
        if img is None:
            continue
        t = time.perf_counter()
        r = model.predict(img, imgsz=IMGSZ, conf=a.conf, device="cpu", verbose=False)[0]
        ms = (time.perf_counter() - t) * 1000
        for k, b in enumerate(r.boxes.xyxy.cpu().numpy().tolist()):
            crop = crop_with_margin(img, b)
            text = read_plate_text(crop)
            conf = float(r.boxes.conf[k])
            print(f"{name}: plate#{k} conf={conf:.2f} box={[round(v) for v in b]} text={text} ({ms:.0f} ms)")
            if a.save_crops and crop.size:
                cv2.imwrite(str(Path(a.save_crops) / f"{Path(name).stem}_{k}.jpg"), crop)
        if not len(r.boxes):
            print(f"{name}: không thấy biển ({ms:.0f} ms)")


if __name__ == "__main__":
    main()
