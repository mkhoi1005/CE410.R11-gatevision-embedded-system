#!/usr/bin/env python3
"""Giả lập nút ESP32-CAM ở làn, để chạy thử toàn bộ một lượt xe khi CHƯA có phần cứng.

Đây là "script giả lập ESP32" mà README_SERVER.md ghi là còn thiếu.

Nó làm đúng những việc nút thật làm:
    1. gửi heartbeat đều đặn                -> POST /esp32/heartbeat
    2. C1 báo có xe                         -> POST /esp32/event  type=C1_TRIGGER
    3. gửi ảnh khung nét nhất               -> POST /esp32/capture
    4. chờ rồi báo xe đã qua thanh chắn     -> POST /esp32/event  type=C2_PASSED

Cách dùng
---------
    # một lượt vào, dùng một ảnh
    python3 -m server.edge.tools.sim_node --gate IN --image anh/bien1.jpg

    # một lượt gửi 3 khung, để thử phần bỏ phiếu giữa các khung
    python3 -m server.edge.tools.sim_node --gate IN --dir anh/ --frames 3

    # chạy cả thư mục ảnh, mỗi lượt cách nhau 3 giây (đo chỉ tiêu 30 lượt liên tục)
    python3 -m server.edge.tools.sim_node --gate IN --dir anh/ --gap 3

    # một lượt vào rồi một lượt ra cùng ảnh đó (kiểm tra khớp VÀO-RA)
    python3 -m server.edge.tools.sim_node --image anh/bien1.jpg --round-trip

    # cố tình KHÔNG báo C2, để xem hệ thống có giữ chắn mở và báo người trực không
    python3 -m server.edge.tools.sim_node --gate IN --image anh/bien1.jpg --no-c2

Chỉ cần thư viện chuẩn, không phải cài gì thêm trên Pi.
"""
import argparse
import json
import mimetypes
import os
import random
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

IMG_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


# ------------------------------------------------------------------ HTTP thủ công
def _post(url, fields, files=None, token=""):
    """POST multipart/form-data chỉ bằng thư viện chuẩn.

    files là danh sách (ten_truong, ten_tep, du_lieu) - cho phép NHIỀU phần cùng tên,
    đúng cách nút gửi nhiều khung của một lượt dưới cùng tên "image".
    """
    bound = "----gvsim" + uuid.uuid4().hex
    body = bytearray()
    for k, v in fields.items():
        body += f"--{bound}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode()
    for k, name, data in (files or []):
        ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
        body += (f"--{bound}\r\nContent-Disposition: form-data; name=\"{k}\";"
                 f" filename=\"{name}\"\r\nContent-Type: {ctype}\r\n\r\n").encode()
        body += data + b"\r\n"
    body += f"--{bound}--\r\n".encode()

    req = urllib.request.Request(url, data=bytes(body), method="POST")
    req.add_header("Content-Type", f"multipart/form-data; boundary={bound}")
    if token:
        req.add_header("X-Node-Token", token)
    return _send(req)


def _get(url, token=""):
    req = urllib.request.Request(url, method="GET")
    if token:
        req.add_header("X-Node-Token", token)
    return _send(req)


def _send(req):
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace")
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"raw": raw[:400]}
    except urllib.error.URLError as e:
        return 0, {"error": f"không nối được tới server: {e.reason}"}


# ------------------------------------------------------------------ một lượt xe
class Node:
    def __init__(self, base, gate, device_id, token):
        self.base, self.gate, self.device_id, self.token = base.rstrip("/"), gate, device_id, token

    def heartbeat(self, state="IDLE"):
        return _post(f"{self.base}/esp32/heartbeat",
                     {"device_id": self.device_id, "gate": self.gate, "state": state,
                      "rssi": str(random.randint(-72, -48))}, token=self.token)

    def c1(self):
        return _post(f"{self.base}/esp32/event",
                     {"gate": self.gate, "type": "C1_TRIGGER", "device_id": self.device_id},
                     token=self.token)

    def capture(self, paths, retries=3):
        """Gửi các khung của một lượt, khung nét nhất trước.

        Gửi lại tối đa `retries` lần khi không nhận được mã xác nhận - đúng bước 2 của
        báo cáo ("chờ mã xác nhận, nếu không có thì gửi lại, tối đa ba lần"). Mã 503 nghĩa
        là khối trung tâm đang đầy việc, cũng thuộc diện gửi lại.
        """
        if isinstance(paths, Path):
            paths = [paths]
        files = [("image", p.name, p.read_bytes()) for p in paths]
        for n in range(1, retries + 1):
            code, res = _post(f"{self.base}/esp32/capture",
                              {"gate": self.gate, "device_id": self.device_id,
                               "ts": f"{time.time():.3f}"}, files=files, token=self.token)
            if code == 200 or code in (401, 413, 422):
                return code, res
            if n < retries:
                print(f"  … không có mã xác nhận ({code}), gửi lại lần {n + 1}/{retries}")
                time.sleep(0.5 * n)
        return code, res

    def c2(self):
        return _post(f"{self.base}/esp32/event",
                     {"gate": self.gate, "type": "C2_PASSED", "device_id": self.device_id},
                     token=self.token)

    def status(self):
        return _get(f"{self.base}/esp32/status", token=self.token)


def one_pass(node: Node, imgs, *, wait_ai: float, c2_after: float, send_c2: bool, quiet=False):
    if isinstance(imgs, Path):
        imgs = [imgs]
    t0 = time.perf_counter()
    node.heartbeat("IDLE")
    node.c1()
    code, res = node.capture(imgs)
    if code != 200:
        print(f"  ✗ gửi ảnh thất bại ({code}): {res}")
        return False
    if not quiet:
        names = ", ".join(p.name for p in imgs)
        print(f"  → đã gửi {res.get('frames', 1)} khung ({names}, {res.get('bytes', 0)} byte), "
              f"hàng đợi {res.get('queued')}")

    # Nút thật không biết AI chạy xong lúc nào; nó chỉ chờ C2 của chính mình.
    # Ở đây chờ một chút cho server kịp nhận dạng rồi mới báo C2 để nhật ký đọc dễ hơn.
    time.sleep(wait_ai)
    if not send_c2:
        print("  ⚠ cố tình KHÔNG báo C2 - xem server có giữ chắn mở và tạo cảnh báo C2_TIMEOUT không")
        return True

    time.sleep(max(c2_after - wait_ai, 0))
    code, res = node.c2()
    if not quiet:
        ok = "✓" if code == 200 else "✗"
        print(f"  {ok} C2 báo xe đã qua ({code}) | cả lượt {time.perf_counter() - t0:.2f}s")
    node.heartbeat("IDLE")
    return code == 200


# ------------------------------------------------------------------ dòng lệnh
def main(argv=None):
    ap = argparse.ArgumentParser(description="Giả lập nút ESP32-CAM của GATE VISION")
    ap.add_argument("--base", default=os.environ.get("GV_SIM_BASE", "http://127.0.0.1:8000"),
                    help="địa chỉ server web (mặc định http://127.0.0.1:8000)")
    ap.add_argument("--gate", default="IN", help="IN | OUT")
    ap.add_argument("--device-id", default="", help="mặc định cam-a cho IN, cam-b cho OUT")
    ap.add_argument("--token", default=os.environ.get("GV_NODE_TOKEN", ""))
    ap.add_argument("--image", help="một tệp ảnh")
    ap.add_argument("--dir", help="cả thư mục ảnh, chạy lần lượt")
    ap.add_argument("--n", type=int, default=1, help="số lượt (dùng với --image)")
    ap.add_argument("--gap", type=float, default=3.0, help="giây giữa hai lượt")
    ap.add_argument("--wait-ai", type=float, default=1.2, help="giây chờ server nhận dạng")
    ap.add_argument("--c2-after", type=float, default=2.0, help="giây sau khi gửi ảnh thì C2 báo")
    ap.add_argument("--no-c2", action="store_true", help="không báo C2, để thử tình huống quá hạn")
    ap.add_argument("--round-trip", action="store_true", help="mỗi ảnh chạy một lượt VÀO rồi một lượt RA")
    ap.add_argument("--frames", type=int, default=1,
                    help="số khung gửi mỗi lượt (nút thật gửi khung nét nhất trước). "
                         "Với --dir, gom từng nhóm ngần này ảnh thành MỘT lượt")
    a = ap.parse_args(argv)

    if not a.image and not a.dir:
        ap.error("cần --image hoặc --dir")
    nf = max(a.frames, 1)
    if a.image:
        one = Path(a.image)
        passes = [[one] * nf] * a.n
    else:
        files = sorted(p for p in Path(a.dir).iterdir() if p.suffix.lower() in IMG_EXT)
        if not files:
            ap.error(f"thư mục {a.dir} không có ảnh nào")
        passes = [files[i:i + nf] for i in range(0, len(files), nf)] if nf > 1 else [[p] for p in files]
    missing = [p for grp in passes for p in grp if not p.exists()]
    if missing:
        ap.error(f"không thấy tệp: {missing[0]}")

    gates = ["IN", "OUT"] if a.round_trip else [a.gate.upper()]
    nodes = {g: Node(a.base, g, a.device_id or ("cam-a" if g == "IN" else "cam-b"), a.token)
             for g in gates}

    code, st = nodes[gates[0]].status()
    if code == 0:
        print(f"Không nối được tới {a.base}. Chạy server trước:"
              f"\n    uvicorn server.main:app --host 0.0.0.0 --port 8000")
        return 2
    if code == 200:
        print(f"Lớp biên: chế độ chắn={st.get('che_do_chan')}, nguồn C2={st.get('nguon_C2')}, "
              f"ngưỡng={st.get('nguong')}")
    elif code == 401:
        print("Server đòi mã thiết bị. Thêm --token hoặc đặt biến GV_NODE_TOKEN.")
        return 2

    ok = 0
    total = len(passes) * len(gates)
    t0 = time.perf_counter()
    for i, grp in enumerate(passes, 1):
        for g in gates:
            print(f"[{i}/{len(passes)}] cổng {g} - {grp[0].name}" + (f" (+{len(grp) - 1} khung)" if len(grp) > 1 else ""))
            if one_pass(nodes[g], grp, wait_ai=a.wait_ai, c2_after=a.c2_after,
                        send_c2=not a.no_c2):
                ok += 1
            if g != gates[-1]:
                time.sleep(a.gap)
        if i < len(passes):
            time.sleep(a.gap)

    dt = time.perf_counter() - t0
    print(f"\nXong {ok}/{total} lượt trong {dt:.1f}s.")
    code, st = nodes[gates[0]].status()
    if code == 200:
        print(f"Thống kê server: {st.get('thong_ke')}")
        print(f"Thanh chắn: {st.get('thanh_chan')}")
    return 0 if ok == total else 1


if __name__ == "__main__":
    sys.exit(main())
