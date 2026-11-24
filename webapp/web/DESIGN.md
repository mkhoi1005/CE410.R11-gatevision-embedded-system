# DESIGN v3 (23/11/2026): "vé gửi xe" truyện tranh, trẻ trung

Thay cho v2 (tông giấy sổ trực, bị nhận xét là chung chung, trông như AI làm). Phúc cung cấp một trang tham khảo (không chép hình, logo, chữ hay nhân vật của trang đó) và chọn hướng: mỗi lượt vào/ra là một tấm vé gửi xe; thích màu, bố cục, chữ, cảm giác chung.

## Hướng
- Sản phẩm: màn hình cho nhân viên trực cổng bãi xe máy theo dõi xe vào/ra và quyết định những lượt camera không chắc
- Tính cách: trẻ trung, vui mắt nhưng rõ ràng; lượt cần quyết phải nổi nhất màn hình
- Điểm nhấn riêng: mỗi lượt là một tấm vé có cuống (A xanh nhạt là vào, B vàng là ra), đường xé răng cưa, số vé `Vé #0001`, thẻ biển số, con dấu mực nghiêng (ĐÃ VÀO, ĐÃ RA, CHỜ DUYỆT, TỪ CHỐI, HẾT HẠN)
- Lượt cần duyệt: khung hồng, băng keo giấy, bong bóng "Ê khoan!", biển số vẽ như biển nhôm nghiêng, lời giải thích trong bong bóng thoại, nút lớn "Từ chối" / "Cho qua"
- Khi yên: khung xanh bạc hà, chữ hiệu ứng "Yên ắng~"

## Quy tắc
- Nền kem `--paper #fff7ec` có hoa văn khung truyện rất mờ (SVG nhúng trong CSS); thẻ `--card #fffdf9`; chữ và viền `--ink #1c1917`
- Màu nhấn đỏ `--red #d7263d` cho hành động chính, số đếm, đồng hồ; màu nền phụ: hồng `--pink` (cần duyệt, bộ lọc), bạc hà `--mint` (yên), xanh nhạt `--sky` (cổng A), bơ `--butter` (cổng B, tiêu đề bảng). Hợp lệ `#1d8a57`, lỗi `#c2410c`, mất kết nối = xám nâu
- Viền mực 2px, bóng đổ cứng không mờ (`4px 4px 0`), nút bấm thì lún xuống; bo góc nhỏ 4–10px
- Chữ: chỉ MỘT họ Mali (OFL, chép sẵn trong `fonts/`, weight 400/500/600/700, không CDN) cho mọi thứ: tiêu đề, nút, chữ thường, giờ, số vé, biển số. Bỏ Baloo 2, Be Vietnam Pro và Space Mono vì trộn nhiều họ chữ trông thiếu đồng nhất và giống giao diện do AI làm. Số dùng `tabular-nums` khi cần thẳng cột
- Nhãn đen chữ trắng hơi nghiêng (`.tag`, tối đa -2 độ), con dấu mực nghiêng 8 độ; mọi thứ nghiêng đều nhỏ để không khó đọc
- Menu nằm trên cùng, mục đang chọn gạch đỏ; trên điện thoại gập thành nút menu
- Xe trong bãi: mỗi phiên gửi là một tấm vé (cuống A "Vào", số phiên, giờ vào, thẻ biển, thời gian đã gửi, ảnh nhỏ, con dấu ĐANG GỬI / CHƯA XÁC NHẬN). Lịch sử vẫn là bảng trên máy tính vì cần lọc và so sánh; từ 760 px trở xuống chuyển sang danh sách vé
- Chuyển động: một đường cong `cubic-bezier(.22, 1, .36, 1)`; chỉ bàn xử lý và hộp thoại "rơi" xuống khi hiện; tôn trọng `prefers-reduced-motion`
- Không dùng hình nhân vật, logo hay chữ nước ngoài; chữ hiệu ứng là tiếng Việt
