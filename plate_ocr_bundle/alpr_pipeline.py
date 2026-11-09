"""alpr_pipeline.py - Raspberry Pi 4: YOLO26 (NCNN) phát hiện biển -> crop -> OCR ONNX.

Cài:   pip install ultralytics ncnn onnxruntime opencv-python-headless
Chạy:  python alpr_pipeline.py --det plate_ncnn_model --ocr plate_ocr.onnx --source ./anh_thu --csv ket_qua.csv
       python alpr_pipeline.py --det plate_ncnn_model --ocr plate_ocr.onnx --source http://<IP_ESP32_CAM>:81/stream
"""
import argparse, csv, time
from pathlib import Path
import cv2
from ultralytics import YOLO
from plate_ocr import OnnxOCR, CROP_MARGIN

IMG_EXTS = {".jpg", ".jpeg", ".png", ".bmp"}


def crop(img, xyxy, margin=CROP_MARGIN):
    h, w = img.shape[:2]
    x1, y1, x2, y2 = xyxy
    mx, my = (x2 - x1) * margin, (y2 - y1) * margin
    return img[int(max(y1 - my, 0)):int(min(y2 + my, h)), int(max(x1 - mx, 0)):int(min(x2 + mx, w))]


def frames(source):
    p = Path(source)
    if p.is_dir() or p.suffix.lower() in IMG_EXTS:
        for f in (sorted(q for q in p.iterdir() if q.suffix.lower() in IMG_EXTS) if p.is_dir() else [p]):
            yield f.name, cv2.imread(str(f))
    else:
        cap = cv2.VideoCapture(int(source) if source.isdigit() else source); i = 0
        while cap.isOpened():
            ok, frm = cap.read()
            if not ok:
                break
            yield f"frame_{i:06d}", frm; i += 1
        cap.release()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--det", required=True); ap.add_argument("--ocr", required=True); ap.add_argument("--source", required=True)
    ap.add_argument("--imgsz", default="320,480"); ap.add_argument("--conf", type=float, default=0.35)
    ap.add_argument("--min-ocr-conf", type=float, default=0.6); ap.add_argument("--csv", default="")
    a = ap.parse_args()
    imgsz = [int(v) for v in a.imgsz.split(",")] if "," in a.imgsz else int(a.imgsz)
    det = YOLO(a.det, task="detect"); ocr = OnnxOCR(a.ocr)
    w = csv.writer(open(a.csv, "w", newline="", encoding="utf-8")) if a.csv else None
    if w:
        w.writerow(["source", "text", "det_conf", "ocr_conf", "valid"])
    for name, img in frames(a.source):
        if img is None:
            continue
        t = time.perf_counter()
        r = det.predict(img, imgsz=imgsz, conf=a.conf, device="cpu", verbose=False)[0]
        for k, b in enumerate(r.boxes.xyxy.cpu().numpy().tolist()):
            res = ocr(crop(img, b))
            sure = res["valid"] and res["conf"] >= a.min_ocr_conf and res.get("agree", 1.0) >= 0.99
            flag = "" if sure else "  [KHÔNG CHẮC - cần kiểm tra]"      # lưu ý: conf cao KHÔNG đảm bảo đúng (từng sai với conf 0.999)
            print(f"{name}: {res['text']}  det={float(r.boxes.conf[k]):.2f} ocr={res['conf']:.2f}{flag}")
            if w:
                w.writerow([name, res["text"], f"{float(r.boxes.conf[k]):.3f}", f"{res['conf']:.3f}", res["valid"]])
        if not len(r.boxes):
            print(f"{name}: không thấy biển")
        # TODO: bỏ phiếu nhiều khung hình liên tiếp của cùng một xe để tăng độ tin cậy (chưa làm).


if __name__ == "__main__":
    main()
