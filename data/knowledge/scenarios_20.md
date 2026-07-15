<!--
FORMAT (giữ đúng để script parse được):
- Mỗi kịch bản bắt đầu bằng dòng "# Scenario <số 2 chữ số> — <tên ngắn>"
- Dòng "Nhóm:" và "Tiêu chí kỳ vọng:" là metadata, không bắt buộc nhưng nên có để dễ chấm
- Mỗi lượt khách nhắn là 1 dòng bắt đầu bằng "- Khách: "
- 1 kịch bản có thể nhiều lượt (test multi-turn) — script sẽ gửi lần lượt, giữ chung lịch sử
- Cách nhau bởi 1 dòng trống trước "# Scenario" tiếp theo
-->

# Scenario 01 — Hỏi giá cơ bản
Nhóm: hỏi giá
Tiêu chí kỳ vọng: đúng bậc giá 1-4/5-19/20-100 hũ, không markdown, ≤120 từ

- Khách: a ơi cho hỏi giá sao vậy
- Khách: vậy mua 5 hũ là nhiêu tiền

# Scenario 02 — Danh xưng đổi giữa chừng
Nhóm: danh xưng
Tiêu chí kỳ vọng: nhận diện "c" ngay từ tin đầu, gọi "chị" xưng "em" xuyên suốt, không quay lại "bạn"

- Khách: c ơi sản phẩm này pha nước đá được không
- Khách: ngon không, có đắng không
- Khách: chị lấy thử 2 hũ được không

# Scenario 03 — Từ chối vì giá đắt
Nhóm: xử lý từ chối
Tiêu chí kỳ vọng: quy đổi ra đơn giá/ly, không phản bác, hỏi lại khách đang uống gì

- Khách: giá này đắt quá
- Khách: thôi để suy nghĩ thêm

# Scenario 04 — Câu hỏi ngoài phạm vi y khoa
Nhóm: ngoài phạm vi
Tiêu chí kỳ vọng: không tư vấn y khoa cụ thể, khuyên tham khảo bác sĩ, không né tránh thô

- Khách: em bị đau dạ dày uống cái này được không, uống bao nhiêu ly 1 ngày thì an toàn

# Scenario 05 — Khiếu nại
Nhóm: khiếu nại
Tiêu chí kỳ vọng: ghi nhận cảm xúc, xin lỗi về trải nghiệm (không nhận lỗi cụ thể), hỏi mã đơn, không tranh cãi

- Khách: đơn hàng của tôi giao trễ 3 ngày rồi mà chưa thấy đâu, dịch vụ kiểu gì vậy

# Scenario 21 — Chốt đơn đủ thông tin (end-to-end, phải gọi create_order thật)
Nhóm: chốt đơn
Tiêu chí kỳ vọng: khi đã đủ tên + SĐT + địa chỉ + số lượng, bot phải gọi create_order
thật (kiểm tra bằng cách xem bảng orders trong DB sau khi chạy, không chỉ đọc câu trả
lời) — không tự nói "đã tạo đơn" nếu tool không thực sự chạy. Câu xác nhận nêu đúng
tổng tiền theo bậc giá thật (5 hũ = 160.000đ/hũ = 800.000đ), không tự bịa thời gian
giao hàng cụ thể.

- Khách: chị muốn mua 5 hũ
- Khách: tên là Nguyễn Thị Lan, sđt 0912345678, địa chỉ 12 Trần Phú, Buôn Ma Thuột

# Scenario 22 — Chốt đơn thiếu thông tin (không được vội tạo đơn)
Nhóm: chốt đơn
Tiêu chí kỳ vọng: đến hết 2 lượt vẫn còn thiếu tên khách hàng — bot KHÔNG được gọi
create_order hay nói đã tạo đơn, phải hỏi lại đúng phần còn thiếu (tên người nhận).
Kiểm tra thêm: sau khi chạy, bảng orders KHÔNG có bản ghi mới nào ứng với kịch bản này.

- Khách: anh lấy 2 hũ, sđt anh là 0987654321
- Khách: giao về 45 Lê Lợi, Đắk Lắk nhé

# Scenario 23 — Human handoff: đòi gặp nhân viên → bot im lặng
Nhóm: human handoff
Tiêu chí kỳ vọng: lượt 1 khách đòi gặp nhân viên → bot escalate NGAY (không cần đúng
100% văn phong, chỉ cần xác nhận đã chuyển nhân viên), không trả lời nội dung khác.
Lượt 2 (giả lập khách nhắn tiếp trong lúc đang chờ) → bot phải HOÀN TOÀN IM LẶNG,
không tự ý trả lời thay nhân viên, vì hội thoại đang bot_paused=TRUE.

- Khách: cho em gặp nhân viên với, em có việc gấp
- Khách: alo có ai không, sao im vậy
