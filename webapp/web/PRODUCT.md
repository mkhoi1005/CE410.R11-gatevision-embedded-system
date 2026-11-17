# Product

<!-- impeccable:product-schema 1 -->

Nguồn: prompt v2 (mục 1, 4, 6, 7, 8, 11), 00_PROJECT_STATE.md (17/11/2026), báo cáo W3–4.
Dòng ghi `[SUY RA]` là suy luận chưa được nhóm xác nhận. Dòng ghi `[CHƯA CHỐT]` phụ thuộc quyết định của nhóm (mã D/Q trong STATE).

## Platform

web

## Users

- **Người trực (`staff`)**: ngồi tại quầy/máy tính gần cổng, theo dõi hai cổng (A = VÀO, B = RA), xử lý các lượt xe bị giữ lại (`HOLD`): bấm "Cho qua" hoặc "Từ chối", nhập tay biển số khi không đọc được. Việc phải làm nhanh, có thể đang vừa nhìn xe thật vừa nhìn màn hình.
- **Quản trị (`admin`)**: quản lý người dùng, xem thiết bị, thống kê, lịch sử.
- **Người xem demo/chấm điểm** [SUY RA]: giảng viên hướng dẫn và nhóm, xem hệ thống chạy trong buổi demo.
- Thiết bị: chủ yếu máy tính (v2 mục 1); báo cáo W3–4 nói thêm điện thoại [CHƯA CHỐT]. Giao diện vẫn phải responsive (v2 mục 7).

## Product Purpose

Giao diện nội bộ để người trực thấy ngay chuyện gì đang xảy ra ở hai cổng và xử lý được các tình huống hệ thống không tự quyết. Thành công khi: (1) lượt xe bị giữ được nhìn thấy và xử lý trong vài thao tác, không bấm nhầm; (2) trạng thái từng camera, thiết bị và kết nối luôn rõ ràng; (3) mọi can thiệp thủ công đều được ghi lại kèm người thực hiện.

## Operating Context

- Chạy trong mạng cục bộ (LAN), không cloud, giai đoạn 1. Raspberry Pi 4 là máy chủ duy nhất, phục vụ cả API lẫn file web tĩnh.
- Mạng: Pi làm AP (báo cáo W3–4) hay router có sẵn + IP tĩnh (v2) [CHƯA CHỐT, D7]. Web phải truy cập được bằng IP, không phụ thuộc hostname `gatevision.local`.
- Phải chạy được khi mất Internet: không dùng CDN, phông chữ và thư viện tải sẵn về.
- Nguyên tắc an toàn xuyên suốt của dự án: mọi lỗi dẫn tới cổng đóng, không tự mở (v2 mục 1) [báo cáo W3–4 chọn ngược lại, D10 CHƯA CHỐT]. Hệ quả cho web: web không tự mở cổng; lệnh "Cho qua" gắn với đúng một sự kiện, dùng một lần.

## Capabilities and Constraints

Chức năng (v2 mục 7):
- Đăng nhập; vai trò `admin`/`staff`; trang thông tin cá nhân (sửa tên, đổi mật khẩu); admin quản lý người dùng; lần chạy đầu bắt buộc đổi mật khẩu admin mặc định.
- Dashboard: hai khung camera (A: VÀO, B: RA) có nhãn và trạng thái kết nối; dưới mỗi khung là biển số vừa phân tích (ảnh biển cắt, độ tin cậy, thời gian, trạng thái, màu OK/cảnh báo); vùng cảnh báo có "Cho qua"/"Từ chối" khi `HOLD`, kèm ô nhập biển tay khi `UNREADABLE`.
- Trang Lịch sử (lọc biển/ngày/trạng thái, xem ảnh), Xe đang trong bãi, Thiết bị (trạng thái 2 ESP32, RSSI, lần cuối online), Thống kê cơ bản.

Ràng buộc:
- Tiếng Việt toàn bộ. Thời gian lưu UTC, hiển thị múi giờ Asia/Ho_Chi_Minh.
- WebSocket tự kết nối lại; có trạng thái rỗng, lỗi, đang tải rõ ràng.
- "Cho qua"/"Từ chối" cần xác nhận và ghi `operator_id`. Cảnh báo âm thanh tùy chọn.
- Chỉ ban ngày, không đèn bổ trợ (báo cáo W3–4): không ảnh hưởng web, nhưng ảnh có thể tối/loá nên khung ảnh phải xem phóng to được.
- Không đưa mã số sinh viên, số điện thoại, email, địa chỉ vào giao diện hay dữ liệu mẫu.
- Biển số xe là dữ liệu cá nhân ở mức nhẹ; chính sách giữ ảnh chưa chốt (Q10).

## Stack

Giao cho Claude đề xuất (người dùng chưa từng làm web). ĐỀ XUẤT - CẦN XÁC NHẬN: HTML + CSS + JavaScript thuần, thêm Alpine.js (một file chép vào thư mục), không có bước build, không Node, không CDN. Pi phục vụ thư mục `web/` như file tĩnh. Server dự kiến FastAPI + WebSocket (v2); báo cáo W3–4 ghi Flask [CHƯA CHỐT].

## Brand Commitments

Chưa có logo hay màu nhóm. Tên hiển thị: GATE VISION. Giọng văn: ngắn, rõ, tiếng Việt, không thuật ngữ thừa; nhãn trạng thái dùng đúng bộ giá trị của hợp đồng (`OK`, `DUPLICATE_IN`, `MISMATCH`, `UNREADABLE`, `FUZZY`) kèm tên tiếng Việt dễ hiểu.

## Open items (ảnh hưởng web)

| Mã | Vấn đề | Ảnh hưởng |
|---|---|---|
| Q3 | `request_id`, `DENY`, `event_id`/TTL | Nút Từ chối, lệnh dùng một lần |
| Q4 | Nhập tay biển, `UNKNOWN-<id>` | Ô nhập biển ở vùng cảnh báo |
| Q8 | Stream từ ESP32 hay qua proxy Pi | Nguồn hình trong khung camera |
| Q9 | Bảng `audit_log` | Có trang xem nhật ký thao tác hay không |
| Q10 | `HOLD_MAX_S`, chính sách xóa ảnh | Đếm ngược của cảnh báo, ảnh cũ có thể mất |
| D3 | Có RFID/Gate Controller không | Thêm trường UID nếu giữ |
| D7 | Pi là AP hay router | Cách truy cập web |
| D8–D10 | Số làn, ai điều khiển servo, mất điện thì mở/đóng | Bố cục dashboard, nhãn trạng thái cổng |
