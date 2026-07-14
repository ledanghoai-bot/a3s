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
