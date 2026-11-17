# Server GATE VISION (phần phục vụ web)

Làm gì: phục vụ web tĩnh, API cho người trực (`web/API_CONTRACT_WEB.md`), WebSocket `/ws/events`, ảnh `/media/...`, dữ liệu SQLite.
CHƯA làm: nhận ảnh từ ESP32 (v2 mục 6.1: capture, heartbeat, command), module AI đọc biển, gửi lệnh mở cổng xuống ESP32, khóa chéo hai cổng (Q5), `audit_log` (Q9). Hàm `logic.process_capture(...)` là chỗ sau này endpoint ESP32 sẽ gọi.

## Cách nhanh nhất
Windows: bấm đúp `chay_web.bat` (ở thư mục `gatevision`). Linux/Mac/Pi: `bash chay_web.sh`. Script tự cài thư viện ở lần đầu, bật chế độ thử, rồi mở trình duyệt (bản Windows).

## Chạy thủ công (máy cá nhân, Python 3.10 trở lên)

```bash
cd gatevision                 # thư mục chứa cả web/ và server/
python3 -m pip install -r server/requirements.txt
GV_DEV=1 python3 -m uvicorn server.main:app --port 8000      # Windows PowerShell (dùng py nếu máy bạn gõ py):  $env:GV_DEV="1"; py -m uvicorn server.main:app --port 8000
```
Mở http://localhost:8000. Với `GV_DEV=1`: có dữ liệu mẫu, tài khoản `truc1`/`truc1234` và `admin`/`admin123` (buộc đổi mật khẩu), và mục "Công cụ thử" trên trang Giám sát. Web tự dùng server thật (server đưa `js/config.js` với `USE_MOCK:false`), không cần sửa file nào.

Chạy thật (không có `GV_DEV`): không có dữ liệu mẫu, không có công cụ thử; tài khoản `admin` có mật khẩu ngẫu nhiên in ra **một lần** ở màn hình lần chạy đầu.
Chạy trên Raspberry Pi để máy khác trong mạng LAN truy cập: thêm `--host 0.0.0.0`. Hiện chỉ có HTTP (không mã hóa); chỉ dùng trong mạng LAN riêng.

## Biến môi trường
| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `GV_DEV` | tắt | `1` = dữ liệu mẫu + công cụ thử. Không bật khi chạy thật |
| `GV_DATA_DIR` | `server/data` | nơi lưu `gatevision.db` và `media/` |
| `GV_HOLD_MAX_S` | 120 | giây giữ tối đa trước khi hết hạn (ĐỀ XUẤT, Q10) |
| `GV_WEB_DIR` | `../web` | thư mục web |

## Kiểm thử
```bash
python3 -m pip install pytest httpx
python3 -m pytest server/tests -q
```

## Hành vi an toàn đã làm
- Lượt `HOLD` hết hạn thành `EXPIRED`, cổng không tự mở; kể cả khi server tắt rồi bật lại giữa chừng, lượt quá hạn bị đánh dấu hết hạn ngay lúc khởi động.
- Lệnh xử lý chỉ có tác dụng với đúng `event_id` đang `HOLD` ở đúng cổng, dùng một lần.
- Mật khẩu băm scrypt; cookie `HttpOnly`, `SameSite=Lax`; sai 5 lần/5 phút thì khóa tạm theo IP; tài khoản bị buộc đổi mật khẩu thì mọi API khác trả 403 cho đến khi đổi.
- Ảnh cần đăng nhập, chặn `../`; WebSocket cần đăng nhập và kiểm tra `Origin`.

## Sao lưu và khôi phục

Toàn bộ dữ liệu (cơ sở dữ liệu SQLite và ảnh) nằm trong thư mục `data/` cạnh `server/` (đổi bằng biến môi trường `GV_DATA_DIR`).
- Sao lưu: tắt server (Ctrl+C), chép cả thư mục `data/` sang nơi khác (USB, ổ khác). Khôi phục: chép lại đúng chỗ rồi chạy lại.
- Xuất bảng lịch sử để mở bằng Excel: trang Lịch sử, nút "Tải CSV (theo bộ lọc)" (tối đa 5000 dòng mỗi lần, UTF-8 có BOM nên Excel đọc đúng tiếng Việt).

## Chạy cho máy khác trong mạng LAN

Windows: bấm đúp `chay_web_LAN.bat` (hiện địa chỉ IPv4 của máy). Linux/Pi: `HOST=0.0.0.0 bash chay_web.sh`. Trên máy khác mở `http://<IPv4>:8000`. Đã thử: đăng nhập, WebSocket và từ chối Origin lạ đều đúng khi truy cập bằng IP. Windows có thể hỏi Firewall, chọn cho phép mạng riêng. Chỉ dùng trong mạng riêng (HTTP, không mã hóa).
