# Chương 1. Bắt đầu bằng một việc đáng giải quyết

**Năng lực sau chương:** viết được đề bài AI gắn với một kết quả mà người dùng và doanh nghiệp nhận thấy.

## 1.1. Câu hỏi đầu tiên không phải chọn mô hình nào

Một buổi trình diễn AI thường tạo cảm giác tiến bộ rất nhanh. Bạn nhập câu hỏi, hệ thống trả lời tự nhiên, cả nhóm nhìn thấy khả năng mới. Nhưng khả năng trả lời chưa xác định ai sẽ dùng, vấn đề nào được giải quyết và doanh nghiệp chấp nhận sai đến đâu. Nếu khởi đầu bằng danh sách công nghệ, dự án dễ hoàn thành nhiều hạng mục mà chưa làm công việc của khách hàng đơn giản hơn.

Foundation của Alpha3s đặt mục tiêu gần là hỗ trợ những đơn cà phê đầu tiên. Vai trò được mô tả bằng hành vi: trả lời câu khách hỏi, khám phá nhu cầu vừa đủ, tư vấn từ thông tin đã duyệt, hỗ trợ giao dịch qua công cụ và chuyển cho người thật khi cần. Hồ sơ cũng ghi thành công không được đo bằng số tin nhắn hay số tệp tri thức. Đó là một điểm xuất phát tốt để quản lý phạm vi. [S01](../nguon/NGUON-VA-PHUONG-PHAP.md)

Người quản lý nên chuyển mục tiêu rộng thành một tình huống hẹp. “Ứng dụng AI vào kinh doanh” chưa giúp đội ngũ chọn việc. “Giúp khách lần đầu hiểu sản phẩm, nhận thông tin giá hiện hành và biết bước đặt hàng tiếp theo” đã gợi được trải nghiệm, dữ liệu cần có và cách kiểm tra. Bạn vẫn có thể đặt tầm nhìn lớn, nhưng ngân sách vòng đầu cần gắn với một nhu cầu quan sát được.

## 1.2. Ba lớp kết quả cần tách

**Output**, hay đầu ra công việc, là thứ đội ngũ tạo ra: bot, dashboard, tài liệu, kết nối kênh. **Outcome**, hay kết quả sử dụng, là thay đổi trong cách người dùng hoàn thành việc: ít phải hỏi lại, nhận câu trả lời đúng, biết ai đang hỗ trợ. **Impact**, hay tác động kinh doanh, là lợi ích rộng hơn: giảm chi phí phục vụ, tăng đơn hợp lệ, giữ khách hoặc giảm sai sót.

Ba lớp có quan hệ nhưng không thay thế nhau. Bot có thể hoạt động mà khách không dùng. Khách có thể dùng nhiều vì bot trả lời vòng vo. Doanh số có thể tăng vì chương trình khuyến mãi thay vì AI. Một manager tốt yêu cầu đội ngũ ghi rõ đang chứng minh lớp nào và còn thiếu gì để suy ra lớp tiếp theo.

| Câu báo cáo | Câu hỏi cần hỏi tiếp |
|---|---|
| Đã có chatbot | Khách hoàn thành được việc nào? |
| Có nhiều hội thoại | Bao nhiêu hội thoại được giải quyết đúng? |
| Tỷ lệ trả lời tự động cao | Có bỏ sót trường hợp phải chuyển người không? |
| Có thêm đơn hàng | Đơn có hợp lệ, giao được và không trùng không? |
| Test đều đạt | Bộ test đại diện cho những tình huống nào? |

## 1.3. Viết đề bài trong một trang

Một đề bài hữu ích trả lời sáu câu. Ai gặp khó khăn? Họ đang làm gì? Vướng mắc gây tốn thời gian, mất cơ hội hay rủi ro gì? AI dự kiến giúp phần nào? Dấu hiệu nào cho biết tình hình tốt hơn? Khi AI không làm được thì ai tiếp nhận?

**Ví dụ giả định:** một cửa hàng nhận nhiều câu hỏi ngoài giờ về cách pha và mức giá. Nhân viên sáng hôm sau mất thời gian đọc lại từng chuỗi tin. Vòng đầu cho AI trả lời cách pha từ tài liệu đã duyệt, lấy giá từ hệ thống bán hàng, thu nhu cầu tối thiểu và chuyển ca khó. Chưa cho AI tự hứa giảm giá, xử lý hoàn tiền hay tư vấn cá nhân về sức khỏe. Kết quả kỳ vọng là khách biết bước tiếp theo và nhân viên không phải hỏi lại từ đầu.

Mẫu này giúp phát hiện điều kiện tiên quyết. Nếu chưa có bảng giá đáng tin, vấn đề đầu tiên là dữ liệu giá. Nếu chưa có người nhận ca chuyển, hứa “có nhân viên hỗ trợ” là một khoảng trống vận hành. AI có thể làm phần nổi bật hơn nhưng không tự bổ sung những phần tổ chức đang thiếu.

## 1.4. Khi nào nên dùng AI?

AI tạo sinh phù hợp để diễn đạt, tổng hợp và xử lý nhiều cách hỏi khác nhau. Một quy tắc cố định thường phù hợp hơn cho phép tính, quyền truy cập, điều kiện giá và trạng thái thanh toán. Một con người phù hợp hơn cho ngoại lệ có hậu quả lớn hoặc cần hiểu bối cảnh chưa đủ dữ liệu.

Không cần phân loại cả sản phẩm vào một ô. Một hành trình có thể dùng cả ba: AI hiểu câu hỏi, hệ thống tính giá, nhân viên giải quyết ngoại lệ. Quyết định đầu tư nên dựa vào chất lượng toàn hành trình. Bạn có thể chọn thử nghiệm quy trình thủ công có hỗ trợ trước khi mở tự động, nếu cách đó giúp hiểu nhu cầu nhanh hơn và giảm chi phí học sai.

Khi đề xuất mới xuất hiện, hãy hỏi: nếu dùng biểu mẫu, tìm kiếm đơn giản hoặc một trang hướng dẫn thì đã giải quyết được bao nhiêu? Câu trả lời không làm giảm giá trị AI. Nó giúp dành AI cho phần cần tính linh hoạt và giữ phần cần chính xác trong những cơ chế dễ kiểm soát.

## 1.5. Đặt điểm dừng từ đầu

Foundation nêu nguyên tắc dừng xây khi nền tảng đủ để chạy và chỉ mở thêm tính năng khi dữ liệu thực tế cho thấy lợi ích. Bài học quản lý là phải có **stop rule**, tức điều kiện dừng hoặc không tiếp tục đầu tư. Một dự án thiếu điều kiện này dễ mở thêm kênh, thêm vai trò và thêm bảng điều khiển để trì hoãn câu hỏi sản phẩm có hữu ích không. [S01]

Bạn có thể đặt ba điểm dừng: dừng thử nghiệm nếu nhu cầu không xuất hiện; dừng tự động nếu lỗi gây hậu quả vượt mức chấp nhận; dừng mở rộng nếu người dùng chưa hoàn thành tốt hành trình cốt lõi. Các điểm dừng cần đi cùng người có quyền quyết định và dữ liệu tối thiểu. “Thấy chưa ổn thì dừng” không đủ để đội ngũ hành động nhất quán.

## 1.6. Thực hành cho manager

Trong 20 phút, viết một đề bài cho chức năng AI bạn muốn triển khai. Chỉ dùng một nhóm người dùng và một công việc chính. Gạch chân mọi từ như “thông minh”, “tối ưu”, “toàn diện”; thay bằng hành vi quan sát được. Sau đó nhờ một đồng nghiệp diễn giải lại kết quả mong muốn mà không đọc tên công nghệ.

**Sản phẩm cần có:** một trang với vấn đề, người dùng, kết quả, ranh giới tự động, đường chuyển người và cách đo. **Tự đánh giá:** nếu hai người đọc trang đó vẫn hình dung hai sản phẩm khác nhau, đề bài cần làm rõ trước khi giao việc.

**Câu mang vào cuộc họp:** “Sau vòng này, người dùng sẽ làm được việc gì tốt hơn, và bằng chứng nào cho thấy điều đó?”

[Nguồn và giới hạn diễn giải](../nguon/NGUON-VA-PHUONG-PHAP.md) · [Mục lục](../MUC-LUC.md)
