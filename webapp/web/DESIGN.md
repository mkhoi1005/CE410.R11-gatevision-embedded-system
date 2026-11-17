# DESIGN v1 (hướng A "Sổ trực", tông xanh theo ảnh nền)

## Chế độ
Công cụ làm việc cho người trực, nền tối xanh. Ảnh nền `img/bg.jpg` cố định, phủ lớp tối (`--dim` .80); mọi khối đặc, không kính mờ.

## Màu (khai báo ở :root trong css/app.css)
| Vai trò | Giá trị |
|---|---|
| Nền trang / thanh bên | `#06111F` / `#050D1A` |
| Khối / khối nổi | `#0B1D33` / `#102845` |
| Viền / viền nhấn | `#1D3D61` / `#3A689C` |
| Chữ / chữ phụ | `#E9F2FB` / `#A3BBD1` |
| Nhấn (nút, mục chọn) | `#4CC3F5`, chữ trên nút `#04121F` |
| Hợp lệ / Đang giữ / Lỗi / Tắt | `#5ED6A0` / `#F6B84C` / `#FF8F86` / `#98AEC0` |
Mọi cặp chữ-nền đã tính tỉ lệ tương phản, tối thiểu 4.5:1 (số đếm đỏ 5.33, viền ô nhập 3.67).

## Chữ
Be Vietnam Pro (OFL-1.1, nhúng sẵn trong `fonts/`, có dấu tiếng Việt), biển số và giờ dùng chữ đơn cách hệ thống.

## Bố cục Giám sát
Cột chính: bàn xử lý (ảnh bằng chứng lớn, biển to, lý do, đếm ngược, Từ chối cách xa Cho qua, hàng chờ) rồi Sổ trực. Cột phải: hai ô giám sát cổng A/B. Mục lục chỉ có chữ. Trạng thái = chữ + vạch màu nhỏ bên trái chữ, không dùng viên thuốc; trong danh sách/bảng dùng chấm màu đầu dòng (không dùng vạch dày bên cạnh thẻ).

## Các trang còn lại
Lịch sử và Xe trong bãi: bảng có chấm trạng thái đầu dòng, biển số chữ đơn cách đậm, ảnh nhỏ ở cuối dòng; Thiết bị: mỗi camera một thẻ với trạng thái lớn và thanh sóng Wi-Fi; Thống kê: hai khối "Trong bãi lúc này" và "Hôm nay" kèm chú thích; Tài khoản/Người dùng: biểu mẫu hẹp, đánh dấu "(bạn)".

## Nét riêng
Biển số giữ nền trắng, tỉ lệ 190x140 như biển thật để đối chiếu.

## Điều khiển nguy hiểm
Từ chối và Cho qua nằm xa nhau; luôn có hộp xác nhận; nút khóa khi mất kết nối trực tiếp hoặc lượt đã hết hạn.
