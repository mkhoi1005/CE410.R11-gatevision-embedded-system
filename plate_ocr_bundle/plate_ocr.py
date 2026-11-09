"""plate_ocr.py - OCR biển số xe máy VN 2 dòng. Phụ thuộc: numpy, opencv, (onnxruntime khi chạy trên Pi)."""
import re
import numpy as np
import cv2

VOCAB = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ|"     # index CTC = vị trí + 1 ; 0 = blank
BLANK = 0
PLATE_W, PLATE_H = 128, 112       # crop biển được resize về cỡ này trước khi cắt dòng
LINE_W, LINE_H = 128, 32          # mỗi dòng -> 128x32 ; 2 dòng nối ngang -> 256x32
CROP_MARGIN = 0.06                # nới bbox của detector 6% mỗi phía khi crop


def make_line(img_bgr, split=0.5):
    """Crop biển (BGR/gray) -> ảnh 1 dòng 32x256 float32 đã chuẩn hoá [-1, 1]. split = vị trí cắt 2 dòng (tỉ lệ chiều cao)."""
    g = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY) if img_bgr.ndim == 3 else img_bgr
    g = cv2.resize(g, (PLATE_W, PLATE_H), interpolation=cv2.INTER_LINEAR)
    s = int(round(PLATE_H * split))
    top = cv2.resize(g[:s], (LINE_W, LINE_H), interpolation=cv2.INTER_LINEAR)
    bot = cv2.resize(g[s:], (LINE_W, LINE_H), interpolation=cv2.INTER_LINEAR)
    line = np.concatenate([top, bot], axis=1).astype(np.float32)
    lo, hi = np.percentile(line, 1), np.percentile(line, 99)
    line = np.clip((line - lo) / max(hi - lo, 20.0), 0.0, 1.0)     # chuẩn hoá tương phản theo từng ảnh (chịu sáng/tối)
    return (line - 0.5) / 0.5


def to_input(img_bgr, split=0.5):
    return make_line(img_bgr, split)[None, None].astype(np.float32)   # (1,1,32,256)


def encode(text):
    return [VOCAB.index(c) + 1 for c in text]


def ctc_greedy(logits):
    """logits (T, C) -> (chuỗi thô, độ tin cậy trung bình của các ký tự phát ra)."""
    e = np.exp(logits - logits.max(1, keepdims=True)); p = e / e.sum(1, keepdims=True)
    idx, mx = p.argmax(1), p.max(1)
    out, confs, prev = [], [], -1
    for i, m in zip(idx, mx):
        if i != prev and i != BLANK:
            out.append(VOCAB[i - 1]); confs.append(float(m))
        prev = i
    return "".join(out), (float(np.mean(confs)) if confs else 0.0)


def ctc_decode(logits):
    """Như ctc_greedy nhưng trả thêm độ tin cậy TỪNG ký tự: (raw, conf_trung_bình, [conf_ký_tự])."""
    e = np.exp(logits - logits.max(1, keepdims=True)); p = e / e.sum(1, keepdims=True)
    idx, mx = p.argmax(1), p.max(1)
    out, confs, prev = [], [], -1
    for i, m in zip(idx, mx):
        if i != prev and i != BLANK:
            out.append(VOCAB[i - 1]); confs.append(float(m))
        prev = i
    return "".join(out), (float(np.mean(confs)) if confs else 0.0), confs


def repair_raw(raw, confs):
    """Dòng dưới (sau '|') chỉ có 4-5 chữ số: nếu model đọc dư (6+), bỏ ký tự có độ tin cậy thấp nhất cho tới khi còn 5."""
    if raw.count("|") != 1:
        return raw
    k = raw.index("|")
    top, bot, bc = raw[:k], raw[k + 1:], list(confs[k + 1:])
    if len(bc) != len(bot):
        return raw
    while len(bot) > 5:
        j = int(np.argmin(bc)); bot = bot[:j] + bot[j + 1:]; bc.pop(j)
    return top + "|" + bot


# Sửa nhầm lẫn theo VỊ TRÍ (heuristic). Dòng trên = 2 số tỉnh + (chữ+số | 2 chữ) ; dòng dưới = 4-5 chữ số.
DIGIT_FIX = {"O": "0", "Q": "0", "D": "0", "I": "1", "L": "1", "Z": "2", "S": "5", "B": "8", "G": "6", "T": "7"}
LETTER_FIX = {"0": "D", "5": "S", "2": "Z", "8": "B"}


def format_plate(raw, conf=0.0):
    res = dict(raw=raw, conf=conf, valid=False, top="", bottom="", text=raw)
    parts = raw.split("|")
    if len(parts) != 2:
        return res
    top, bot = parts
    if len(top) in (3, 4):
        t = list(top)
        for i in (0, 1):
            t[i] = DIGIT_FIX.get(t[i], t[i])
        t[2] = LETTER_FIX.get(t[2], t[2])          # ký tự thứ 4 (số HOẶC chữ, vd "A1" / "FL") được giữ nguyên
        top = "".join(t)
    bot = "".join(DIGIT_FIX.get(c, c) for c in bot)
    # dòng trên: 2 số tỉnh + (1 chữ + 1 số | 2 chữ) ; dòng dưới: 4-5 chữ số
    ok = re.fullmatch(r"\d{2}(?:[A-Z]\d|[A-Z]{2})", top) is not None and re.fullmatch(r"\d{4,5}", bot) is not None
    top_f = top[:2] + "-" + top[2:] if len(top) >= 3 else top
    bot_f = bot[:3] + "." + bot[3:] if len(bot) == 5 else bot
    res.update(valid=ok, top=top_f, bottom=bot_f, text=f"{top_f} {bot_f}")
    return res


def text_to_target(s):
    """'59-P1 664.80' | '59P1|66480' -> '59P1|66480' (None nếu không tách được 2 dòng)."""
    toks = [t for t in re.split(r"[\s|/]+", str(s).strip().upper()) if t]
    if len(toks) != 2:
        return None
    a, b = (re.sub(r"[^0-9A-Z]", "", t) for t in toks)
    return f"{a}|{b}" if a and b else None


class OnnxOCR:
    def __init__(self, path, threads=4):
        import onnxruntime as ort
        so = ort.SessionOptions(); so.intra_op_num_threads = threads
        self.sess = ort.InferenceSession(str(path), so, providers=["CPUExecutionProvider"])
        self.inp = self.sess.get_inputs()[0].name

    def __call__(self, img_bgr, split=0.5, votes=3):
        """votes=3: đọc ở 3 vị trí cắt dòng (split-0.04, split, split+0.04) trong 1 batch rồi bỏ phiếu chuỗi thô."""
        splits = [split] if votes <= 1 else [split - 0.04, split, split + 0.04]
        x = np.concatenate([to_input(img_bgr, s) for s in splits])
        lg = self.sess.run(None, {self.inp: x})[0]
        cands = []
        for l in lg:
            raw, cf, ch = ctc_decode(l)
            cands.append((repair_raw(raw, ch), cf))
        cnt = {}
        for r, _ in cands:
            cnt[r] = cnt.get(r, 0) + 1
        top = max(cnt.values())
        best = max((c for c in cands if cnt[c[0]] == top), key=lambda c: c[1])
        res = format_plate(*best)
        res["agree"] = top / len(cands)            # 1.0 = mọi phiếu cùng kết quả
        return res
