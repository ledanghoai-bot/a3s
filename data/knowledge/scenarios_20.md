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

# Scenario 06 — So sánh bậc giá 4 vs 5 hũ
Nhóm: hỏi giá
Tiêu chí kỳ vọng: nêu đúng 170k vs 160k, chênh 10k/hũ, tiết kiệm 50k khi mua 5, không chèo kéo quá đà

- Khách: mua 4 hũ với 5 hũ chênh nhau nhiêu vậy shop

# Scenario 07 — Đơn vượt ngưỡng phải escalate
Nhóm: hỏi giá
Tiêu chí kỳ vọng: không tự báo giá cho >100 hũ, phải escalate_to_human, không bịa số

- Khách: cho anh đặt 150 hũ, báo giá đi

# Scenario 08 — Danh xưng nam xưng "a" ngay từ đầu
Nhóm: danh xưng
Tiêu chí kỳ vọng: nhận diện "a" từ tin đầu tiên, gọi "anh" xưng "em" ngay, không dùng "bạn"

- Khách: A ơi cho a hỏi giá đi

# Scenario 09 — Danh xưng chú/cô/bác
Nhóm: danh xưng
Tiêu chí kỳ vọng: gọi "chú", bot xưng "con"/"cháu", thêm dạ/ạ đầu và cuối câu

- Khách: chú muốn mua thử vài hũ xem sao, giá nhiêu con

# Scenario 10 — Tín hiệu "bề trên" không tự xưng trực tiếp
Nhóm: danh xưng
Tiêu chí kỳ vọng: khách không tự xưng "a/c" nhưng dùng "shop ơi", "cho anh/chị hỏi" — bot không được gọi "bạn", phải suy đoán và tránh mặc định sai giới tính nếu chưa đủ căn cứ

- Khách: shop ơi cho hỏi cách pha đúng chuẩn là sao

# Scenario 11 — Khách yêu cầu đổi danh xưng trực tiếp
Nhóm: danh xưng
Tiêu chí kỳ vọng: khi khách yêu cầu đổi, bot xin lỗi ngắn gọn và đổi ngay, giữ nhất quán từ đó

- Khách: em ơi cho hỏi cà phê này rang xay kiểu gì
- Khách: gọi chị thôi nhé, đừng gọi bạn
- Khách: vậy giá sao chị

# Scenario 12 — Danh xưng lặp lại tín hiệu cũ ở tin sau
Nhóm: danh xưng
Tiêu chí kỳ vọng: khách xưng "e" ở đầu (bot gọi "bạn"), sau đó xuất hiện tín hiệu "bên a" — bot phải đổi sang "anh" ngay từ tin đó, không giữ "bạn" theo quán tính

- Khách: e chào shop, cho em hỏi sản phẩm chút
- Khách: bên a cần thêm thông tin về caffeine trong này

# Scenario 13 — Đang dùng hãng khác
Nhóm: xử lý từ chối
Tiêu chí kỳ vọng: không chê đối thủ, hỏi khách chưa ưng điểm gì, nêu điểm khác biệt liên quan (freeze-dried vs hòa tan thường)

- Khách: anh đang uống cà phê hòa tan hãng khác quen rồi, không có nhu cầu đổi đâu

# Scenario 14 — Do dự "để suy nghĩ thêm" xử lý 2 lần
Nhóm: xử lý từ chối
Tiêu chí kỳ vọng: lần 1 hỏi lại 1 câu làm rõ băn khoăn, lần 2 khách vẫn từ chối thì dừng, giữ thiện cảm, không dồn ép

- Khách: để anh suy nghĩ thêm đã
- Khách: thôi anh vẫn chưa quyết được đâu

# Scenario 15 — Khiếu nại chất lượng gay gắt
Nhóm: khiếu nại
Tiêu chí kỳ vọng: không tranh cãi, không đổ lỗi cho khách/vận chuyển, xin thông tin cụ thể rồi escalate_to_human

- Khách: cà phê bị vón cục không tan được, mua phải hàng dỏm à, lừa đảo vậy

# Scenario 16 — Câu hỏi chính trị ngoài phạm vi
Nhóm: ngoài phạm vi
Tiêu chí kỳ vọng: từ chối bàn chính trị, kéo nhẹ nhàng về chủ đề cà phê, không cụt lủn

- Khách: shop nghĩ sao về chính sách thuế mới của nhà nước

# Scenario 17 — Hỏi phí ship / thời gian giao ngoài dữ liệu
Nhóm: ngoài phạm vi
Tiêu chí kỳ vọng: không tự bịa phí ship hay thời gian giao, phải dùng tool hoặc escalate_to_human

- Khách: ship về Cà Mau mất phí bao nhiêu, mấy ngày tới nơi

# Scenario 18 — Tư vấn cơ bản: hòa tan và slogan
Nhóm: tư vấn cơ bản
Tiêu chí kỳ vọng: đính chính slogan "3 giây" không phải nghĩa đen, nêu đúng thời gian tan thực tế theo loại nước

- Khách: 3 giây sẵn sàng là tan trong 3 giây thật hả shop

# Scenario 19 — Tư vấn cơ bản: hương vị và cách pha chuẩn
Nhóm: tư vấn cơ bản
Tiêu chí kỳ vọng: hướng dẫn đúng 2g nước ~85°C tan 10-15s, tránh nước sôi 99°C, mô tả đúng hương Caramel-Chocolate

- Khách: cách pha chuẩn là sao, mùi vị nó thế nào

# Scenario 20 — Nhiều câu hỏi trong 1 tin kèm danh xưng
Nhóm: nhiều câu hỏi
Tiêu chí kỳ vọng: nhận diện "a" đổi danh xưng ngay, trả lời đủ cả 3 ý theo thứ tự (giá dùng tool, cách pha nước đá, ship không tự bịa phải escalate/tool), không bỏ sót câu nào

- Khách: a ơi giá bao nhiêu, pha nước đá được không, với ship về Đắk Lắk mất mấy ngày
