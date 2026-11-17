# Hợp đồng API cho web: bản nháp v0

Phạm vi: các endpoint mà trình duyệt gọi (v2 mục 6.3). Phần ESP32 ↔ Server (v2 mục 6.1) giữ nguyên, không nằm ở đây.
Nhãn: **[v2]** = có trong prompt v2. **[ĐỀ XUẤT]** = mình thêm, CẦN XÁC NHẬN. **[Q3/Q4/Q8/Q9]** = phụ thuộc quyết định chưa chốt.
Chỉ thêm trường, không đổi trường cũ. Tiền tố `/api/v1`.

## Quy ước chung

- Thời gian: chuỗi ISO 8601 UTC, ví dụ `"2026-11-17T04:12:09Z"`. Web hiển thị theo Asia/Ho_Chi_Minh. [v2 mục 3]
- Xác thực: cookie phiên `HttpOnly` sau `POST /auth/login`. WebSocket dùng cùng cookie. [v2 mục 11; JWT hay cookie vẫn để ngỏ ở mục 6.3, đề xuất cookie]
- Lỗi: HTTP 4xx/5xx kèm `{"error": {"code": "STRING", "message": "tiếng Việt"}}`. [ĐỀ XUẤT]
- Ảnh: đường dẫn tương đối dưới `/media/...`, cần đăng nhập, server chặn path traversal. Đuôi file tùy nguồn (ảnh thật `.jpg`, ảnh giả của chế độ thử `.svg`). [v2 mục 8]
- Tài khoản có `must_change_password = true`: mọi endpoint trừ `/auth/*`, `GET /users/me`, `POST /users/me/password` trả 403 `PASSWORD_CHANGE_REQUIRED` cho đến khi đổi mật khẩu. [ĐỀ XUẤT]
- Phân trang danh sách: `?limit=50&cursor=<id>`, trả `{"items": [...], "next_cursor": "..."|null}`. [ĐỀ XUẤT]

## Kiểu dữ liệu

**Event** (một lần camera gửi ảnh)
```json
{
  "event_id": 1021,
  "time": "2026-11-17T04:12:09Z",
  "gate": "IN",
  "device_id": "cam-a",
  "plate": "59X1-12345",
  "confidence": 0.87,
  "decision": "OPEN",
  "status": "OK",
  "image_url": "/media/events/1021/full.jpg",
  "plate_image_url": "/media/events/1021/plate.jpg",
  "session_id": 311,
  "fuzzy_candidates": [],
  "resolution": null
}
```
- `gate`: `IN` | `OUT`. `decision`: `OPEN` | `HOLD`. `status`: `OK` | `DUPLICATE_IN` | `MISMATCH` | `UNREADABLE` | `FUZZY`. [v2 mục 6.1]
- `plate`, `plate_image_url`, `confidence` có thể `null` khi `UNREADABLE`. [v2]
- `fuzzy_candidates`: danh sách `{"session_id": 12, "plate": "59X1-12346"}`, có khi `status = FUZZY`. [v2 mục 4]
- `resolution`: `null` khi chưa xử lý; sau khi xử lý: `{"action": "PASS"|"DENY"|"EXPIRED", "operator_id": 3, "operator_name": "...", "time": "...", "manual_plate": "..."|null}`. `EXPIRED` khi hết `HOLD_MAX_S` (không có `operator_id`). `operator_name` để web hiển thị tên người xử lý. [Q3, Q4, ĐỀ XUẤT]
- `hold_expires_at`: thời điểm `HOLD` hết hạn (từ `HOLD_MAX_S`), chỉ có khi đang `HOLD`. [ĐỀ XUẤT, Q10]

**Session** (một lượt xe trong bãi)
```json
{
  "id": 311, "plate": "59X1-12345",
  "time_in": "2026-11-17T04:12:09Z", "image_in_url": "/media/...", "confidence_in": 0.87,
  "time_out": null, "image_out_url": null, "confidence_out": null,
  "status": "IN", "flagged": false
}
```
- `status`: `IN` | `OUT`. [v2 mục 8: có `IN`; giá trị đóng phiên mình gọi `OUT`, ĐỀ XUẤT]
- `flagged`: true khi biển là `UNKNOWN-<event_id>` cần xử lý khi xe ra. [Q4]

**Alert**
```json
{"id": 77, "type": "MISMATCH", "event_id": 1025, "time": "...", "status": "OPEN", "message": "Biển ra không khớp phiên nào đang mở"}
```
- `type`: `DUPLICATE_IN` | `MISMATCH` | `UNREADABLE` | `FUZZY` | `DEVICE_OFFLINE`. [v2 mục 8]
- `status`: `OPEN` | `RESOLVED`. [ĐỀ XUẤT]
- `DEVICE_OFFLINE` không có `event_id`, có `device_id`. [ĐỀ XUẤT]

**Device**
```json
{"device_id": "cam-a", "gate": "IN", "ip": "192.168.4.11", "rssi": -61, "uptime": 86400,
 "state": "IDLE", "last_seen": "...", "online": true, "stream_url": "http://192.168.4.11:81/stream"}
```
- Các trường `device_id, ip, rssi, uptime, state` lấy từ heartbeat. [v2 mục 6.1]
- `stream_url`: địa chỉ ESP32 (mặc định) hoặc đường dẫn proxy trên Pi. [Q8]
- `state`: một trong các trạng thái máy trạng thái ESP32 (`IDLE`, `DETECTED`, `CAPTURING`, `WAITING_SERVER`, `GATE_OPENING`, `GATE_OPEN`, `GATE_CLOSING`, `COOLDOWN`, `HOLD`, `ERROR_RETRY`, `OFFLINE`). [v2 mục 4]

**User**: `{"id": 3, "username": "...", "display_name": "...", "role": "admin"|"staff", "must_change_password": false}`. [ĐỀ XUẤT trường]

## Endpoint

| Phương thức, đường dẫn | Vai trò | Mô tả |
|---|---|---|
| `POST /auth/login` | công khai | Body `{username, password}` → 200 trả thẳng đối tượng `User` + đặt cookie. Sai: 401. Quá nhiều lần thử: 429. [v2] |
| `POST /auth/logout` | đăng nhập | Xóa cookie. [v2] |
| `GET /users/me` | đăng nhập | Trả `User`. [v2] |
| `PATCH /users/me` | đăng nhập | Body `{display_name}`. [ĐỀ XUẤT] |
| `POST /users/me/password` | đăng nhập | Body `{old_password, new_password}`. [ĐỀ XUẤT] |
| `GET/POST /users`, `PATCH /users/{id}` | admin | Quản lý người dùng. [ĐỀ XUẤT; v2 chỉ nêu "admin quản lý người dùng"] |
| `GET /events` | đăng nhập | Lọc: `plate`, `gate`, `status`, `from`, `to`, phân trang. [v2] |
| `GET /events/{id}` | đăng nhập | Chi tiết một Event. [ĐỀ XUẤT] |
| `GET /sessions` | đăng nhập | Lọc: `status`, `plate`. "Xe đang trong bãi" = `status=IN`. [v2] |
| `GET /alerts` | đăng nhập | Lọc: `status=OPEN`. [v2] |
| `POST /gate/{gate}/override` | đăng nhập | Xử lý lượt `HOLD`, xem bên dưới. [v2, Q3, Q4] |
| `GET /devices` | đăng nhập | Danh sách `Device`. [v2] |
| `GET /stats` | đăng nhập | Thống kê cơ bản, xem bên dưới. [v2] |
| `GET /healthz` | công khai | `{"status": "ok"}`, không lộ chi tiết. [v2] |
| `WS /ws/events` | đăng nhập | Đẩy thông điệp thời gian thực. [v2] |

### `POST /gate/{gate}/override`

Body:
```json
{"event_id": 1025, "action": "PASS", "manual_plate": null, "session_id": null}
```
- `action`: `PASS` (Cho qua, mở cổng) | `DENY` (Từ chối). `DENY` cần Q3. [Q3]
- `manual_plate`: chỉ dùng khi `PASS` ở cổng VÀO với `status = UNREADABLE`. Để trống thì server tạo phiên `UNKNOWN-<event_id>`. [Q4]
- `session_id`: phiên cần đóng khi `PASS` ở cổng RA. Bắt buộc khi `status = FUZZY` (phải thuộc `fuzzy_candidates`), tùy chọn khi `MISMATCH`/`UNREADABLE`. [ĐỀ XUẤT, v2 mục 4 nói người trực chọn trong danh sách nhưng chưa có trường]
- Chỉ có tác dụng với đúng `event_id` đang `HOLD` ở đúng `gate`. Lệnh dùng một lần.

Phản hồi: 200 `{"event": Event}` với `resolution` đã điền. Lỗi:
- 404 `EVENT_NOT_FOUND`; 409 `ALREADY_RESOLVED` hoặc `EXPIRED` (đã hết `HOLD_MAX_S`); 409 `GATE_BUSY` nếu bật khóa chéo (Q5); 409 `DUPLICATE_IN` nếu biển nhập tay đã có trong bãi; 422 `INVALID_PLATE` (biển nhập tay sai định dạng), `CHOOSE_SESSION` (thiếu `session_id` khi FUZZY), `INVALID_SESSION`.
- Web không tự thử lại lệnh này khi lỗi mạng: hiển thị lỗi và để người trực tự quyết, để tránh mở nhầm. [ĐỀ XUẤT]
- Server ghi `operator_id` và, nếu Q9 được duyệt, ghi `audit_log`.

### `GET /stats` [ĐỀ XUẤT, v2 chưa định nghĩa]
```json
{"inside_now": 12, "in_today": 40, "out_today": 28, "hold_today": 3, "unreadable_today": 2}
```

## WebSocket `/ws/events`

Thông điệp dạng `{"type": "...", "data": {...}}`: [v2: ba loại đầu]

| `type` | `data` | Khi nào |
|---|---|---|
| `event_created` | Event | Có lượt chụp mới |
| `event_updated` | Event | Lượt `HOLD` được xử lý hoặc hết hạn [ĐỀ XUẤT] |
| `alert` | Alert | Cảnh báo mới hoặc đổi trạng thái |
| `device_status` | Device | Heartbeat đổi trạng thái hoặc mất/có lại kết nối |

Hành vi của web: tự kết nối lại (chờ tăng dần, tối đa vài giây). Khi kết nối lại, tải lại `GET /events` và `GET /alerts?status=OPEN` để không sót thông điệp trong lúc mất kết nối. Trong lúc mất kết nối, hiện biểu ngữ và khóa nút "Cho qua". [ĐỀ XUẤT]

## Việc cần nhóm xác nhận

1. Cookie phiên hay JWT (v2 để ngỏ).
2. Q3 (`DENY`, TTL), Q4 (nhập tay biển), Q8 (nguồn stream), Q9 (`audit_log`), Q10 (hết hạn `HOLD`).
3. Có thêm `event_updated`, `/users` đầy đủ, `/stats` như trên không.
4. Nếu giữ RFID (D3): thêm `uid` vào Event và Session.
5. Quyền hạn: `staff` có được "Cho qua" không, hay chỉ `admin`? v2 chưa nói, đề xuất cả hai.
