# Web GATE VISION (giao diện người trực)

Thư mục này là một trang web tĩnh: không cần cài Node, không build, không CDN.
Thư viện duy nhất là Alpine.js (giấy phép MIT), đã chép sẵn ở `js/alpine.min.js`.

## Chạy thử ngay (dữ liệu giả, chưa cần server)

```bash
cd web
python3 -m http.server 8080
```
Mở http://localhost:8080 trong trình duyệt.
- Người trực: `truc1` / `truc1234`
- Quản trị: `admin` / `admin123` (bắt buộc đổi mật khẩu lần đầu)

Ở trang "Giám sát" có mục "Công cụ thử": bấm để tạo xe vào/ra, biển trùng, biển không đọc được, biển gần giống, ngắt kết nối... rồi thử bấm "Cho qua"/"Từ chối".

Ở chế độ dữ liệu giả, bấm đúp vào `index.html` cũng chạy được (đã thử). Khi nối server thật thì phải phục vụ qua server như mục dưới.

Chức năng, cách kiểm chứng từng bước: `CHUC_NANG_VA_KIEM_CHUNG.md`. Prompt gửi AI của các bạn trong nhóm: `PROMPT_WEB_CHO_NHOM.md`.

Đổi độ chìm của ảnh nền: sửa `--dim` trong `css/app.css` (0 = rõ hết, 1 = đen hẳn; hiện .80). Ảnh nền ở `img/bg.jpg`.

## Nối với server thật

Đã có server FastAPI trong thư mục `server/` (xem `server/README_SERVER.md`). Chạy `GV_DEV=1 python3 -m uvicorn server.main:app --port 8000` rồi mở http://localhost:8000; server tự báo cho web biết dùng API thật, không cần sửa `js/config.js`.
Nếu dùng server khác: server phải phục vụ thư mục `web/` như file tĩnh, trả API đúng `API_CONTRACT_WEB.md` tại `/api/v1/...`, WebSocket tại `/ws/events`, ảnh tại `/media/...`, và web với API phải cùng địa chỉ (cùng IP, cùng cổng) vì dùng cookie phiên.
