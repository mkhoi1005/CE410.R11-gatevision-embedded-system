# Web GATE VISION: chức năng hiện có và cách kiểm chứng

Cập nhật: 17/11/2026 (bản 2: thêm tải CSV, màn hình nhỏ, chạy qua LAN). Phạm vi: phần web (giao diện người trực) và server FastAPI phục vụ web. Phần ESP32 và Raspberry Pi chưa nằm trong tài liệu này (xem mục 6).

## 1. Đã làm được

**Giao diện (thư mục `web/`)**
- Đăng nhập, đăng xuất, đổi mật khẩu bắt buộc ở lần đầu (tài khoản `must_change_password`).
- Giám sát: hai màn hình camera (A = VÀO, B = RA), bàn xử lý lượt đang giữ (HOLD), hàng chờ khi có nhiều lượt giữ, nhật ký lượt gần nhất. Cập nhật tức thời qua WebSocket.
- Xử lý lượt giữ: Cho qua / Từ chối, có hộp xác nhận. Cổng VÀO không đọc được biển: nhập tay biển (có thể để trống thì tạo phiên `UNKNOWN-<id>`). Cổng RA biển gần giống hoặc không khớp: chọn xe trong bãi để đóng phiên.
- Lượt giữ có hạn (mặc định 120 giây). Hết hạn thì chuyển `EXPIRED`, cổng không tự mở.
- Lịch sử: lọc theo biển, cổng, trạng thái, khoảng thời gian; phân trang "Tải thêm"; bấm dòng (hoặc Enter) xem chi tiết kèm ảnh. Nút "Tải CSV (theo bộ lọc)" xuất bảng ra file mở được bằng Excel (UTF-8 có BOM, tối đa 5000 dòng mỗi lần).
- Xe trong bãi, Thiết bị (trạng thái, IP, RSSI, uptime), Thống kê trong ngày, Hồ sơ cá nhân, Quản lý người dùng (chỉ admin).
- Mất kết nối trực tiếp: hiện biểu ngữ, khóa nút "Cho qua", tự kết nối lại rồi tải lại dữ liệu để không sót.
- Dùng được trên điện thoại và máy tính bảng (đã kiểm tra ở 390 px và 768 px, không tràn ngang). Trên màn hình dưới 560 px bảng Lịch sử chỉ hiện 4 cột chính, chi tiết xem khi bấm dòng.
- Phím Esc đóng hộp thoại, focus chuyển vào hộp thoại khi mở và trả về nút cũ khi đóng.
- Giao diện hướng A "Sổ trực": nền xanh đậm, ảnh nền chìm, chữ Be Vietnam Pro, trạng thái bằng chữ + chấm màu.

**Server (thư mục `server/`)**
- Đăng nhập cookie `gv_session` (HttpOnly, SameSite=Lax), băm mật khẩu scrypt, chặn thử mật khẩu (5 lần sai trong 5 phút thì 429).
- Đủ endpoint theo `web/API_CONTRACT_WEB.md`, WebSocket `/ws/events` có kiểm tra Origin, `/media` cần đăng nhập và chặn path traversal.
- Vòng kiểm tra hết hạn HOLD, giám sát thiết bị (30 giây không heartbeat thì báo `DEVICE_OFFLINE`).
- Công cụ thử `POST /dev/sim/{kind}` chỉ tồn tại khi `GV_DEV=1`.
- 22 bài kiểm thử tự động (`server/tests/test_api.py`).

## 2. Cách chạy

Windows (PowerShell, dùng `py`):
```powershell
py -m pip install -r server\requirements.txt
$env:GV_DEV="1"
py -m uvicorn server.main:app --port 8000
```
Hoặc bấm đúp `chay_web.bat`. Linux/Mac: `chay_web.sh`. Mở http://localhost:8000.

Cho máy khác trong mạng LAN (điện thoại, máy khác): bấm đúp `chay_web_LAN.bat` (hiện địa chỉ IPv4), hoặc `HOST=0.0.0.0 bash chay_web.sh`; trên máy kia mở `http://<IPv4>:8000`. Windows có thể hỏi Firewall: cho phép mạng riêng. Chỉ dùng trong mạng riêng (HTTP không mã hóa).

Tài khoản chế độ thử: người trực `truc1` / `truc1234`; quản trị `admin` / `admin123` (bị buộc đổi mật khẩu ngay lần đầu).

Chạy không cần server (dữ liệu giả trong trình duyệt): `cd web` rồi `py -m http.server 8080`, mở http://localhost:8080. Hai chế độ cho cùng kết quả ở mọi kịch bản dưới đây.

Chạy tự động: `py -m pytest server/tests -q` (cần `pip install pytest httpx`).

## 3. Kiểm chứng bằng tay (dùng mục "Công cụ thử" ở trang Giám sát)

Mở "Công cụ thử" rồi làm lần lượt. Mỗi dòng: thao tác, kết quả mong đợi.

| # | Thao tác | Kết quả mong đợi |
|---|---|---|
| 1 | Đăng nhập sai mật khẩu | Báo lỗi tiếng Việt, không vào được. Sai 5 lần liên tiếp thì báo thử lại sau |
| 2 | Đăng nhập `admin` / `admin123` | Bị chuyển sang trang đổi mật khẩu, chưa vào được trang khác cho đến khi đổi |
| 3 | "Xe vào hợp lệ" | Lượt mới ở nhật ký, trạng thái "Hợp lệ, đã mở cổng"; trang "Xe trong bãi" thêm 1 xe |
| 4 | "Xe ra khớp" | Lượt RA hợp lệ; xe đó rời trang "Xe trong bãi" |
| 5 | "Biển trùng lúc vào" | Cổng giữ, có cảnh báo; bấm Từ chối: lượt ghi "Từ chối bởi <tên bạn>", không thêm xe vào bãi |
| 6 | "Vào, không đọc được" rồi Cho qua, để trống biển | Mở cổng, bãi có phiên biển `UNKNOWN-<số>` được đánh dấu cần xử lý |
| 7 | Như 6 nhưng nhập `59X1-12345` | Phiên mang biển đã nhập. Nhập biển sai định dạng thì báo lỗi, không mở. Nhập biển đang có trong bãi thì báo trùng |
| 8 | "Ra, biển gần giống" | Bắt buộc chọn xe trong danh sách mới được Cho qua; chọn xong thì phiên đó đóng |
| 9 | "Ra, không khớp" | Cổng giữ; Cho qua mà không chọn phiên thì mở cổng nhưng không đóng phiên nào; Từ chối thì giữ nguyên |
| 10 | "Ra, không đọc được" | Giữ cổng, chọn phiên tùy chọn |
| 11 | "3 lượt giữ cùng lúc" | Có hàng chờ, số lượt đang giữ hiện cạnh mục Giám sát; xử lý từng lượt, lượt tiếp theo lên bàn xử lý |
| 12 | "Lượt giữ chỉ 15 giây", đợi hơn 15 giây | Lượt chuyển "Hết hạn", nút bị khóa, cổng không mở; lịch sử ghi hết hạn |
| 13 | "Camera A ngắt/nối" | Màn hình A hiện "Mất kết nối", có cảnh báo thiết bị; nối lại thì cảnh báo tự đóng |
| 14 | "Camera B ngắt/nối" | Tương tự cho B |
| 15 | "Ngắt/nối kết nối trực tiếp" | Hiện biểu ngữ mất kết nối, nút "Cho qua" bị khóa; nối lại thì tự mở khóa |
| 16 | "Thêm 30 xe vào + ra", sang Lịch sử | 25 dòng đầu, có nút "Tải thêm"; bấm thì thêm dòng. Số xe trong bãi không đổi |
| 17 | Lịch sử: lọc theo biển, cổng, trạng thái | Danh sách lọc đúng; "Xóa lọc" trả lại đầy đủ |
| 18 | Bấm một dòng (hoặc Tab tới dòng rồi Enter) | Hộp chi tiết có ảnh; Esc đóng, focus về dòng cũ |
| 19 | Mở hộp Cho qua rồi Esc | Hộp đóng, không mở cổng |
| 20 | Đăng nhập `truc1`, vào "Người dùng" bằng địa chỉ `#users` | Bị đưa về trang Giám sát; mục "Người dùng" không hiện với người trực (server cũng trả 403 nếu gọi API trực tiếp) |
| 21 | "Xóa lượt xe, nạp lại dữ liệu mẫu" | Trở về dữ liệu ban đầu, vẫn đăng nhập |
| 22 | Lịch sử: bấm "Tải CSV (theo bộ lọc)" (sau "Thêm 30 xe vào + ra") | Tải file `.csv`; mở bằng Excel thấy đủ dòng, tiếng Việt đúng. Lọc cổng A rồi tải lại thì file chỉ có các dòng "A vào" |
| 23 | Mở web bằng điện thoại cùng Wi-Fi qua `chay_web_LAN.bat` | Đăng nhập được; bấm "Xe vào hợp lệ" trên máy tính thì điện thoại thấy lượt mới ngay (WebSocket qua IP) |
| 24 | Thu hẹp cửa sổ trình duyệt xuống khoảng 390 px (hoặc dùng điện thoại) | Không có thanh cuộn ngang; bảng Lịch sử còn cột Thời gian, Cổng, Biển số, Trạng thái; bộ lọc xếp 2 cột; hộp thoại xử lý vẫn đủ nút |

Lưu ý: trong trang xem trước (artifact) nút "Tải CSV" không tải được vì khung xem trước chặn tải xuống; hãy thử CSV khi chạy server trên máy bạn.

Kiểm chứng riêng cho chế độ server thật:
- Mở http://localhost:8000/media/idle.svg khi chưa đăng nhập: bị từ chối. Đăng nhập rồi mở: thấy ảnh.
- Dừng server khi đang mở web: biểu ngữ mất kết nối hiện ra; chạy lại server: web tự nối lại.
- Chạy không đặt `GV_DEV`: không có "Công cụ thử", mật khẩu admin ngẫu nhiên in ra một lần ở cửa sổ lệnh.

## 4. Đối chiếu với kiểm thử tự động

| Nội dung | Hàm kiểm thử |
|---|---|
| Đăng nhập, cookie, chặn thử mật khẩu, đổi mật khẩu bắt buộc | `test_auth_required_and_login`, `test_cookie_flags`, `test_rate_limit`, `test_forced_password_change` |
| Phân quyền người dùng | `test_users_admin_only` |
| Lọc, phân trang lịch sử | `test_events_seed_filters_pagination` |
| Xe vào/ra, mở và đóng phiên | `test_in_ok_opens_session_and_out_closes` |
| Nhập tay biển, phiên `UNKNOWN` | `test_unreadable_in_manual_plate`, `test_unreadable_in_without_plate_flagged` |
| Biển trùng, Từ chối | `test_duplicate_and_deny` |
| Biển gần giống phải chọn phiên | `test_fuzzy_requires_choice` |
| Sai cổng, lượt không tồn tại | `test_wrong_gate_and_unknown_event` |
| Hết hạn HOLD, cổng không tự mở | `test_expired_hold_fail_safe`, `test_expire_task_marks_short_hold` |
| Cảnh báo, thiết bị, thống kê | `test_alerts_devices_stats` |
| Ảnh cần đăng nhập, path traversal | `test_media_auth_and_traversal` |
| WebSocket, Origin lạ | `test_websocket_events`, `test_websocket_rejects_foreign_origin` |
| Đường dẫn API lạ, web phục vụ cấu hình server, bản chạy thật không có công cụ thử | `test_unknown_api_path_json`, `test_web_served_with_server_config`, `test_no_dev_tools_in_production` |
| Các kịch bản mới (giữ ngắn, nhiều lượt, camera A, 30 xe, đặt lại) | `test_dev_scenarios_new` |

## 5. Giới hạn đã biết

- Ảnh nền `img/bg.jpg` chưa xác minh giấy phép sử dụng: cần nhóm xác nhận nguồn trước khi nộp.
- Ảnh camera trong chế độ thử là ảnh giả (SVG), không phải ảnh thật.
- Chưa thử trên Raspberry Pi 4 (chỉ chạy trên máy dev). Đã thử truy cập qua IP LAN trên máy dev (đăng nhập, WebSocket, từ chối Origin lạ đều đúng), chưa thử trên điện thoại thật.
- Kiểm tra màn hình nhỏ chỉ bằng trình duyệt giả lập kích thước (390 px, 768 px), chưa thử trên thiết bị thật.
- Sao lưu: tắt server rồi chép thư mục `data/` (xem `server/README_SERVER.md`); chưa có nút sao lưu trong web.
- Lệnh Cho qua không tự thử lại khi mất mạng, cố ý để người trực quyết định.

## 6. Chưa làm (chờ nhóm quyết)

- Endpoint ESP32 → server (`capture`, `heartbeat`, `command`) và script giả lập ESP32: để nhóm thống nhất với phần Pi/ESP32 (Q1, D3).
- Nguồn luồng video (Q8): ESP32 trực tiếp hay qua Pi. Web đã đọc `stream_url` từ API nên đổi nguồn không phải sửa web.
- Q3, Q4, Q5, Q9, Q10 trong `00_PROJECT_STATE.md`: web đang theo đề xuất trong hợp đồng, nếu nhóm đổi thì sửa hợp đồng trước.
