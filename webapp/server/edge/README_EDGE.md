# Lớp biên GATE VISION trên Raspberry Pi 4

Mã nguồn vận hành **một lượt xe** từ lúc nút làn gửi ảnh về tới lúc thanh chắn hạ xuống.

Phần này **không viết lại luật nghiệp vụ**. Luật vào–ra vẫn nằm nguyên ở
`server/logic.py` như `README_SERVER.md` yêu cầu; lớp biên chỉ lo phần vật lý: nhận ảnh,
đọc biển số, điều khiển thanh chắn, đọc cảm biến C2.

---

## 1. Đặt mã vào đâu

Giải nén vào nhánh `web-interface`, thành một gói con của server:

```
webapp/
  server/
    main.py  db.py  logic.py  config.py  media.py  hub.py      (đã có)
    edge/                                                       ← thêm mới
      __init__.py      gắn router + nối lệnh "cho qua" của người trực vào thanh chắn
      config.py        toàn bộ tham số, đọc từ biến môi trường
      gpio.py          pigpio → RPi.GPIO → giả lập, tự chọn
      barrier.py       mở/hạ thanh chắn, quy tắc chờ C2 và hỏng-thì-mở
      recognizer.py    bước 3-4-5: YOLO (NCNN) → CRNN+CTC (ONNX) → kiểm tra hợp lệ
      images.py        lưu ảnh bằng chứng JPEG thật, thay ảnh giả SVG
      pipeline.py      hàng đợi mỗi cổng + trình tự một lượt xe
      routes.py        /esp32/capture, /event, /heartbeat, /command, /status
      tools/
        sim_node.py    giả lập nút ESP32-CAM, chạy thử khi chưa có phần cứng
        smoke_edge.py  tự kiểm tra 11 nhóm kịch bản, không cần model và không cần phần cứng
  models/
    plate_ncnn_model/          từ nhánh AI
    plate_ocr.onnx             từ nhánh AI
  plate_ocr.py                 từ nhánh AI (gói plate_ocr_bundle), để import được
```

Sửa `server/main.py` **đúng hai dòng**:

```python
from .edge import install          # thêm vào khối import

app = FastAPI(title="GATE VISION", lifespan=lifespan)
install(app)                       # thêm ngay sau khi tạo app
```

Không cần sửa `lifespan`: hàng đợi và model tự khởi động ở lượt ảnh đầu tiên. Nếu muốn
nạp model lúc bật máy để lượt xe đầu không bị chậm, thêm vào `lifespan` sau
`seed_first_run()`:

```python
from .edge import pipeline
await pipeline.start()
```

---

## 2. Một lượt xe chạy thế nào

```
C1 báo có xe  ──► ESP32-CAM chụp ──► POST /esp32/capture (1-3 khung JPEG, nét nhất trước)
                                          │
                     GHI XUỐNG ĐĨA  ──────┤  fsync + đổi tên nguyên tử
                     rồi mới trả 200 ─────┘  nút nhận 200 là ảnh đã an toàn, ngừng gửi lại
                                          │
                              pipeline: hàng đợi riêng của cổng (giữ đường dẫn, không giữ RAM)
                                          │
      bước 3  YOLO26n (NCNN)        tìm vùng biển; box đầu trượt thì thử box kế tiếp
      bước 4  CRNN+CTC (ONNX)       đọc ký tự, bỏ phiếu 3 vị trí cắt dòng
      bước 5  ba chốt chặn          đúng khuôn biển VN?  conf ≥ 0.60?  3 phiếu khớp?
              trượt ──► đọc tiếp khung 2, 3 ──► nhận nếu ≥2 khung cho cùng một biển
                                          │
      bước 6  logic.process_capture()     luật vào-ra của phần web (KHÔNG viết lại)
                                          │
              ┌───────────────────────────┴───────────────────────────┐
         decision = OPEN                                      decision = HOLD
         mở chắn → chờ C2 → hạ chắn            giữ chắn hạ, web báo người trực
                                                người trực bấm "cho qua"
                                                → logic.override → mở chắn
```

Hai cổng có hàng đợi và tiến trình riêng nên xe làn này không phải chờ làn kia. Riêng
phần suy luận AI dùng chung một giấy phép (`GV_AI_CONCURRENCY=1`) để hai làn không giành
nhau 4 nhân của Pi.

**Ba điểm đáng chú ý trong trình tự trên**, vì đều là chỗ dễ làm sai:

*Mã xác nhận chỉ trả sau khi ảnh đã nằm trên đĩa* (mục 3.6 của báo cáo). Ảnh được ghi vào
`data/spool/<cổng>/`, gọi `fsync`, đổi tên nguyên tử, rồi mới trả 200. Mất điện ngay sau đó
thì lúc khởi động lại, `_recover_spool()` đưa những lượt còn sót vào hàng đợi xử lý tiếp -
nên lượt nào đã được xác nhận thì không mất. Hàng đợi đầy thì trả **503** và **không** giữ
ảnh, để nút gửi lại theo đúng ba lần ở bước 2; tuyệt đối không âm thầm bỏ một ảnh đã xác nhận.

*Bỏ phiếu giữa các khung chạy theo bậc thang.* Khung nét nhất được đọc trước; qua đủ ba chốt
chặn là dừng, y hệt hành vi một khung, nên ngân sách thời gian ở Bảng 8 không bị ảnh hưởng ở
lượt bình thường. Chỉ khi khung đó trượt mới đọc tiếp, và điều kiện nhận lúc đó **ngặt hơn**
một khung đơn (phải hai khung độc lập cho cùng một biển hợp lệ). Vì vậy tỉ lệ ghép nhầm
không tăng, chỉ giảm số lượt phải gọi người trực.

*Nhiều box trong một khung thì thử lần lượt.* Mục 3.3.3 nói giữ box có conf cao nhất,
`alpr_pipeline.py` của nhóm AI thì OCR mọi box. Ở đây box đầu trượt ba chốt chặn thì còn thử
box kế tiếp, nên thứ tự (`GV_DET_PICK`) không quyết định kết quả - đổi `area` sang `conf`
chỉ đổi box nào được thử trước.

**Ba chốt chặn ở bước 5** quyết định một lượt là "đọc được" hay không. Không đạt thì
`recognizer` trả `plate=None`, `logic.process_capture` cho ra `UNREADABLE/HOLD`, thanh chắn
**không mở**. Không có đường nào để một lượt đọc sai mà vẫn tự mở chắn.

---

## 3. Hai quy tắc an toàn cài sẵn trong `barrier.py`

**Chỉ hạ khi C2 báo xe đã qua hẳn, không bao giờ hạ theo đồng hồ đếm ngược.**
Quá `GV_C2_TIMEOUT_S` (mặc định 20 giây) mà C2 im lặng thì **giữ nguyên ở vị trí mở**, tạo
cảnh báo `C2_TIMEOUT` cho người trực, và vẫn tiếp tục chờ — C2 báo muộn thì hạ. Đây là cách
chặn rủi ro "thanh chắn hạ trúng xe đang qua" ở mục 4.5 của báo cáo.

**Hỏng thì mở.** Nhóm chốt là mất điện hoặc mất mạng thì thanh chắn về trạng thái mở. Mã
hỗ trợ cả hai kiểu lắp, chọn bằng `GV_BARRIER_MODE`:

| | `two_way` (mặc định) | `fail_open` |
|---|---|---|
| Cơ cấu | servo quay tới góc mở / góc hạ rồi nhả | lò xo hoặc đối trọng luôn kéo thanh chắn **lên**; servo phải phát xung liên tục mới ghìm được chắn hạ |
| Mất điện | thanh chắn **đứng yên** tại chỗ | thanh chắn **tự mở** — đúng quy tắc, không cần mã can thiệp |
| Chương trình thoát / Ctrl-C / SIGTERM / lỗi nặng | mã cố nâng lên trước khi tắt | ngừng xung → tự mở |

Khuyến nghị dùng `fail_open` cho bản báo cáo vì quy tắc hỏng-thì-mở do **phần cứng** bảo
đảm, không phụ thuộc chương trình còn sống hay không. Hiện chưa lắp cơ cấu nên để
`two_way`; khi lắp xong chỉ cần đổi một biến môi trường, không sửa mã.

Hàm `panic_open()` được gắn vào `atexit`, `SIGINT` và `SIGTERM` nên mọi đường thoát đều nhả
servo.

---

## 4. Cảm biến C2 — chọn bằng cấu hình

| `GV_C2_SOURCE` | Đường đi của tín hiệu |
|---|---|
| `http` (mặc định) | C2 nối vào ESP32 của làn, nút gửi `POST /esp32/event type=C2_PASSED` — đúng đường W1/W2 trong Bảng 5 |
| `gpio` | C2 kéo dây thẳng về chân GPIO của Pi (`GV_C2_PIN_IN`, `GV_C2_PIN_OUT`), có lọc nhiễu tiếp xúc |
| `both` | nhận cả hai, bên nào báo trước thì tính |

Dùng `both` khi chạy thử để so hai đường cho nhau; chốt một đường khi lắp thật.

---

## 5. Biến môi trường

Toàn bộ tham số nằm ở `edge/config.py`, không có số nào viết cứng trong logic.

### Mô hình AI
| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `GV_DET_MODEL` | `models/plate_ncnn_model` | thư mục NCNN của bộ phát hiện |
| `GV_OCR_MODEL` | `models/plate_ocr.onnx` | mô hình đọc ký tự |
| `GV_DET_H` / `GV_DET_W` | `320` / `480` | phải khớp `export_imgsz` lúc xuất model |
| `GV_DET_CONF` | `0.60` | theo `conf_threshold` trong `model_info.json` |
| `GV_OCR_VOTES` | `3` | số vị trí cắt dòng đem bỏ phiếu |
| `GV_OCR_MIN_CONF` | `0.60` | chốt chặn độ tin cậy |
| `GV_OCR_MIN_AGREE` | `0.99` | `1.0` = ba phiếu phải cùng kết quả |
| `GV_OCR_REQUIRE_VALID` | `1` | bắt buộc đúng khuôn biển Việt Nam |
| `GV_AI_THREADS` | `4` | số nhân cho ONNX Runtime |

### Thanh chắn
| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `GV_BARRIER_MODE` | `two_way` | `two_way` \| `fail_open` |
| `GV_PIN_IN` / `GV_PIN_OUT` | `18` / `19` | chân GPIO (đánh số BCM) |
| `GV_PULSE_OPEN` / `GV_PULSE_CLOSE` | `1900` / `1000` | độ rộng xung (µs) — **đo lại trên servo thật rồi chỉnh** |
| `GV_SERVO_TRAVEL_S` | `0.6` | thời gian quay hết hành trình |
| `GV_GPIO` | `auto` | `auto` \| `pigpio` \| `rpigpio` \| `mock` |

### Cảm biến C2
| Biến | Mặc định |
|---|---|
| `GV_C2_SOURCE` | `http` |
| `GV_C2_PIN_IN` / `GV_C2_PIN_OUT` | `23` / `24` |
| `GV_C2_ACTIVE_LOW` | `1` (ngõ ra NPN của E18-D80NK: có vật cản = mức thấp) |
| `GV_C2_TIMEOUT_S` | `20.0` |
| `GV_C2_DEBOUNCE_S` | `0.05` |

### Vận hành
| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `GV_QUEUE_MAX` | `16` | hàng đợi mỗi cổng; đầy thì trả **503** cho nút gửi lại |
| `GV_SPOOL_DIR` | `<data>/spool` | nơi ghi ảnh trước khi trả mã xác nhận |
| `GV_MULTIFRAME` | `1` | bật bỏ phiếu giữa các khung |
| `GV_MAX_FRAMES` | `3` | số khung tối đa nhận mỗi lượt |
| `GV_VOTE_MIN_FRAMES` | `2` | cần mấy khung đồng thuận mới nhận |
| `GV_DET_PICK` | `area` | thứ tự thử box: `area` (box to nhất trước) hoặc `conf` |
| `GV_DET_MAX_BOXES` | `2` | số box tối đa đem đi OCR trong một khung |
| `GV_AI_CONCURRENCY` | `1` | số lượt suy luận AI chạy song song |
| `GV_TIMING_CSV` | *(trống)* | đặt đường dẫn để ghi số đo từng chặng — dùng cho phần đo ở tuần 9 |
| `GV_JPEG_QUALITY` | `85` | chất lượng ảnh bằng chứng |
| `GV_NODE_TOKEN` | *(trống)* | mã chia sẻ cho các endpoint `/esp32/*`; để trống là bỏ kiểm tra |

---

## 6. Các endpoint mới

Đây là phần "v2 mục 6.1" mà `README_SERVER.md` ghi là **chưa làm**. Không đụng tới endpoint
của web (mục 6.3). Tất cả nhận mã thiết bị qua header `X-Node-Token`.

| Phương thức | Đường dẫn | Tham số | Dùng để |
|---|---|---|---|
| `POST` | `/esp32/capture` | `image` (1-3 phần cùng tên, mỗi phần một khung JPEG, **nét nhất trước**), `gate`, `device_id`, `ts` | nút gửi ảnh khi C1 báo có xe. Trả 200 sau khi ảnh **đã ghi xuống đĩa**, chưa chờ nhận dạng. Hàng đợi đầy thì **503**, nút gửi lại |
| `POST` | `/esp32/event` | `gate`, `type`, `device_id` | `type=C2_PASSED` cho phép hạ chắn; `type=C1_TRIGGER` chỉ để ghi nhận |
| `POST` | `/esp32/heartbeat` | `device_id`, `gate`, `state`, `rssi` | nút báo còn sống, khuyến nghị 10 giây/lần |
| `GET` | `/esp32/command` | `device_id` | nút hỏi trạng thái thanh chắn để hiện đèn. Thanh chắn do **Pi** giữ, nút không tự điều khiển |
| `GET` | `/esp32/status` | — | xem nhanh cấu hình, hàng đợi, trạng thái chắn, thống kê |

`gate` nhận cả `IN`/`VAO`/`A` và `OUT`/`RA`/`B`. Ảnh tối đa 2 MB. Mốc thời gian của nút chỉ
được dùng nếu lệch dưới 5 phút so với giờ Pi, tránh đồng hồ ESP32 chưa đồng bộ làm sai nhật ký.

---

## 7. Chạy thử khi chưa có phần cứng

Không cần Pi, không cần servo, không cần ESP32. `gpio.py` tự chuyển sang bản giả lập và in
trạng thái thanh chắn ra màn hình.

### 7.1 Tự kiểm tra một lệnh (không cần cả model AI)

```bash
cd webapp
python3 server/edge/tools/smoke_edge.py
```

Chạy 18 nhóm kịch bản trên cơ sở dữ liệu tạm và in ra từng mục đạt/không đạt. Trong đó
**8 trong 10 kịch bản của Bảng 9** được kiểm tra tự động:

| Bảng 9 | Trong bộ tự kiểm tra |
|---|---|
| 1 xe vào bình thường | [3] |
| 2 xe ra bình thường | [5] |
| 3 biển hơi mờ nhưng trên ngưỡng | [9] - đúng cơ chế, cần ảnh thật mới đo được số |
| 4 biển bị che, không đọc được | [6] |
| 5 xe ra không khớp phiên nào | [8] |
| 6 người trực mở thủ công | [7] |
| 7 hai làn chạy cùng lúc | [13] |
| 8 mất kết nối không dây | thuộc firmware ESP32; `sim_node` có phần gửi lại ba lần |
| 9 mất điện khối trung tâm | [15] + [12] (ảnh đã xác nhận không mất) |
| 10 ba mươi lượt liên tục | [14] |

Cộng thêm: vào trùng, mã làn sai, ảnh rỗng, C2 quá hạn rồi báo muộn, hai khung đồng thuận
cứu được lượt, các khung đọc khác nhau thì vẫn giữ chắn, mã xác nhận chỉ trả sau khi ghi
đĩa, thử box thứ hai khi box đầu trượt, heartbeat, mã thiết bị, tệp số đo.

Chỉ phần **đọc một khung** bị thay bằng hàm giả để chạy được trên máy tính không có model;
`read_frames`, hàng đợi, spool, nghiệp vụ, thanh chắn và C2 đều là mã thật. Hàm giả nhận
kịch bản mã hoá ngay trong ảnh, nên test điều khiển được từng khung một mà không phải vá
thêm gì vào mã thật.

Bộ này đã chạy đạt ở năm cấu hình: mặc định, `GV_MULTIFRAME=0`, `GV_DET_PICK=conf`,
`GV_BARRIER_MODE=fail_open`, `GV_C2_SOURCE=both`.

### 7.2 Giả lập nút làn, có model AI thật

```bash
# cửa sổ 1 — server
cd webapp
GV_GPIO=mock GV_TIMING_CSV=/tmp/gv_timing.csv \
  uvicorn server.main:app --host 0.0.0.0 --port 8000

# cửa sổ 2 — giả lập nút làn
python3 -m server.edge.tools.sim_node --gate IN --image anh/bien1.jpg
```

Các kịch bản nên chạy đủ (ứng với Bảng 9 — thiết kế kiểm tra):

```bash
# 1. lượt vào bình thường
python3 -m server.edge.tools.sim_node --gate IN  --image anh/bien1.jpg

# 2. vào rồi ra cùng một biển -> phải khớp phiên, đóng phiên
python3 -m server.edge.tools.sim_node --image anh/bien1.jpg --round-trip

# 3. vào hai lần cùng biển -> DUPLICATE_IN / HOLD
python3 -m server.edge.tools.sim_node --gate IN --image anh/bien1.jpg --n 2

# 4. ra mà chưa từng vào -> MISMATCH / HOLD
python3 -m server.edge.tools.sim_node --gate OUT --image anh/la.jpg

# 5. ảnh mờ, không đọc được -> UNREADABLE / HOLD, chắn không mở
python3 -m server.edge.tools.sim_node --gate IN --image anh/mo.jpg

# 6. C2 không báo -> giữ chắn MỞ + cảnh báo C2_TIMEOUT
python3 -m server.edge.tools.sim_node --gate IN --image anh/bien1.jpg --no-c2

# 7. 30 lượt liên tục, mỗi lượt cách 3 giây -> đo chỉ tiêu thông suốt
python3 -m server.edge.tools.sim_node --gate IN --dir anh/ --gap 3

# 8. mỗi lượt gửi 3 khung -> thử phần bỏ phiếu giữa các khung
python3 -m server.edge.tools.sim_node --gate IN --dir anh/ --frames 3
```

Mở `http://127.0.0.1:8000` để xem nhật ký lượt, ảnh bằng chứng và các lượt đang giữ, đúng
như khi chạy thật.

---

## 8. Đo số liệu cho báo cáo

Đặt `GV_TIMING_CSV` rồi mỗi lượt sẽ ghi một dòng:

```
thoi_diem, event_id, cong, bien_so, ocr_conf, det_conf, agree,
quyet_dinh, trang_thai, detect_ms, ocr_ms, nghiep_vu_ms, tong_tren_pi_ms
```

`tong_tren_pi_ms` là phần Pi chịu trách nhiệm (từ lúc ảnh tới tới lúc có quyết định), chính
là con số đem so với ngân sách thời gian ở Bảng 8. Phần chụp ảnh và truyền Wi-Fi của ESP32
nằm ngoài, phải đo riêng ở phía nút.

---

## 9. Những chỗ hồ sơ W3-4 cần sửa cho khớp mã

Mã đã chạy đúng; mấy chỗ dưới đây là **tài liệu** nói khác thực tế, cần sửa một hai câu.

| Mục trong báo cáo | Tài liệu viết | Thực tế |
|---|---|---|
| 3.3.3 lọc khung chứa | giữ box có điểm tin cậy cao nhất | thử lần lượt tối đa 2 box, mặc định box to nhất trước (`GV_DET_PICK`) |
| 3.3.4 đọc ký tự | "nắn thẳng nếu biển bị nghiêng" | **không có** phép nắn thẳng. CRNN train trên crop không nắn, thêm vào lúc suy luận là đổi phân phối đầu vào nên dễ làm tệ hơn. Đề nghị bỏ câu này, hoặc để tuần sau train lại kèm augment xoay |
| 3.3.5 so điểm tin cậy | ngụ ý conf là chốt chặn chính | ghi chú trong `alpr_pipeline.py`: *conf cao KHÔNG bảo đảm đúng (từng sai với conf 0,999)*. Gánh chính là `valid` và `agree` |
| 2.3 mô hình | OCR PP-OCRv3 rút gọn, YOLO nano INT8, cả hai chạy ONNX Runtime | CRNN+CTC tự train; YOLO26n FP32; detector chạy **NCNN**, OCR chạy ONNX |
| 3.5 cơ sở dữ liệu | bảng `phan_quyet` riêng, `su_kien.barie_da_mo`, `nguon_lenh_mo` | `events.decision` + `events.resolution` (JSON) - tương đương chức năng, khác lược đồ |
| 3.6 máy chủ web | Flask | **FastAPI** |
| 4.2 dữ liệu thử | 1.000-1.500 ảnh tự thu, bốn điều kiện ánh sáng | hiện đo trên GreenParking công khai. **Đây là khoảng trống lớn nhất**, không phải lỗi mã |
| Bảng 8 | sáu chặng | ba chặng trên Pi đã ghi vào CSV; **ba chặng của nút (0,1 + 0,4 + 0,5 s) chưa ai đo** - cần firmware gửi thêm mốc C1 và mốc chụp xong |

Ngoài ra, hai chỗ lệch **trong nhánh AI** nên chốt một số: `--conf 0.35` ở
`alpr_pipeline.py` so với `0.60` ở `model_info.json` và `pi_infer.py` (mã này dùng 0,60), và
`CROP_MARGIN` 0,08 ở `pi_infer.py` so với 0,06 ở `plate_ocr.py` (mã này dùng 0,06 - con số
bộ OCR được đánh giá cùng, **không nên đổi**).

---

## 10. Cần làm khi lắp lên phần cứng thật

1. Chép `plate_ncnn_model/` và `plate_ocr.onnx` từ nhánh AI vào `webapp/models/`, chép
   `plate_ocr.py` vào chỗ Python import được.
2. Cài trên Pi: `pip install ultralytics onnxruntime opencv-python-headless pigpio`,
   rồi `sudo systemctl enable --now pigpiod`.
3. Đo `GV_PULSE_OPEN` / `GV_PULSE_CLOSE` trên servo thật — hai số mặc định chỉ là điểm bắt đầu.
4. Chọn `GV_BARRIER_MODE` theo cơ cấu đã lắp, và `GV_C2_SOURCE` theo cách nối cảm biến.
5. Đặt `GV_NODE_TOKEN` và nạp cùng mã đó vào firmware ESP32.
6. Chạy lại cả 7 kịch bản ở mục 7 bằng xe thật, ghi `GV_TIMING_CSV` để lấy số cho tuần 9.
