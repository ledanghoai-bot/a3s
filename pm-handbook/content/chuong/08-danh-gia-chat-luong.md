# Chương 8. Đánh giá AI bằng bằng chứng có ý nghĩa

**Năng lực sau chương:** đọc báo cáo chất lượng, hiểu mẫu thử và không để điểm tổng che lỗi nghiêm trọng.

## 8.1. “Nghe hay” chưa phải “làm đúng”

Khung EV-001 của Alpha3s chia đánh giá thành nguồn tri thức, tìm kiếm, chọn đường xử lý, chất lượng câu trả lời, an toàn, hội thoại và sẵn sàng kinh doanh. Cách chia này giúp biết cần sửa phần nào. Một câu lịch sự nhưng trả giá cũ vẫn là lỗi. Một câu ngắn nhưng bỏ qua khiếu nại cũng không đạt mục tiêu. [S10]

**Evaluation**, đánh giá, là một hoạt động có câu hỏi, dữ liệu, cách chấm và kết luận giới hạn. Nó không chỉ là chạy một danh sách câu hỏi. Manager cần biết bộ thử được chọn thế nào, ai xác định đáp án và bản hệ thống nào được kiểm.

## 8.2. Ba nhóm kiểm tra bổ sung cho nhau

Kiểm tra bằng quy tắc phù hợp với mã, số, quyền và trạng thái. Người đánh giá phù hợp với độ dễ hiểu, hữu ích và cách xử lý tình huống mơ hồ. AI hỗ trợ chấm có thể mở rộng số lượng nhưng cần được đối chiếu với người chấm và không làm trọng tài duy nhất cho kết luận quan trọng.

**Ground truth**, đáp án tham chiếu, là kết quả được xác định đúng để so sánh. Nó có thể là một hành vi như “phải chuyển người” chứ không phải đoạn văn cố định. Nếu người nghiệp vụ chưa thống nhất đáp án, điểm số của hệ thống khó có ý nghĩa.

**Rubric**, thang chấm có mô tả, giúp người chấm nhất quán. EV-004 dùng các mức từ phản hồi đúng, có nguồn và tự nhiên tới lỗi nghiêm trọng. Điểm an toàn được phân loại riêng, tránh để nhiều câu tốt bù cho một giao dịch sai. [S11]

## 8.3. Hiểu precision và recall qua tình huống che dữ liệu

**Precision**, độ chính xác trong những trường hợp hệ thống đã đánh dấu, trả lời: trong những đoạn bị xem là dữ liệu nhạy cảm, bao nhiêu đoạn thực sự nhạy cảm? **Recall**, khả năng bắt đủ, trả lời: trong toàn bộ dữ liệu nhạy cảm cần phát hiện, hệ thống bắt được bao nhiêu?

**Ví dụ giả định:** có 100 đoạn nhạy cảm; hệ thống phát hiện đúng 90 và đánh dấu nhầm 10 đoạn khác. Recall là 90/100 = 90%; precision là 90/(90+10) = 90%. Nếu giảm đánh dấu để câu trả lời bớt bị che nhưng bỏ sót nhiều hơn, precision có thể tăng trong khi recall giảm. Hai tỷ lệ cần đọc cùng hậu quả.

Tình huống M4 về chuỗi 12 chữ số cho thấy một dãy số có thể là tài khoản ngân hàng, giấy tờ hoặc mã đơn. Review yêu cầu xét ngữ cảnh và kiểm thử trường hợp xung đột, thay vì né các ca làm điểm xấu. Đó là ví dụ rõ của việc cân bằng bắt đủ và tránh nhận nhầm. [S09]

## 8.4. Bộ thử phải có ca khó và ca sát biên

**Positive case** là trường hợp cần chấp nhận; **negative case** là trường hợp cần từ chối hoặc chuyển tuyến; **edge case** là trường hợp ở rìa điều kiện. Một bộ chỉ có câu dễ rất có thể đạt điểm cao nhưng không giúp quyết định an toàn.

Với ngưỡng 0,80 và 0,95 trong thiết kế M5, cần kiểm các giá trị ngay dưới, đúng bằng và ngay trên ngưỡng; đồng thời có trường hợp điểm cao nhưng vi phạm quy tắc cứng. Đừng coi các ngưỡng này là khuyến nghị mặc định cho dự án khác. Chúng là chính sách của tình huống học. [S20]

**Regression test**, kiểm thử hồi quy, giữ các lỗi đã sửa không quay lại. Mỗi lỗi quan trọng nên trở thành một ca thử rõ nguyên nhân, đầu vào, kỳ vọng và phạm vi. Nếu bộ thử chỉ tăng số lượng mà không giúp phát hiện lỗi thực, chi phí duy trì sẽ tăng vô ích.

## 8.5. Mẫu nội bộ và thực tế trả lời hai câu hỏi khác nhau

Dữ liệu **synthetic**, tức dữ liệu tạo riêng để thử, giúp kiểm tra trường hợp hiếm hoặc nhạy cảm mà không dùng thông tin khách. Nhưng nó thường gọn và có cấu trúc hơn ngôn ngữ thật. Chạy tốt trên dữ liệu giả chưa chứng minh tỷ lệ thành công khi khách viết sai, trộn nhiều ý hoặc gửi tin thiếu ngữ cảnh.

Manager nên yêu cầu báo cáo tách kết quả kỹ thuật có kiểm soát và kết quả quan sát thực tế. Nếu chưa có mẫu đại diện, hãy nói “chưa đo” và lập kế hoạch đo phù hợp ở giai đoạn sau. Không lấp chỗ trống bằng một điểm benchmark khác bối cảnh.

Ngay cả không thấy lỗi trong mẫu cũng không chứng minh không có lỗi. Kích thước mẫu, cách lấy mẫu, nhóm người dùng và độ độc lập đều ảnh hưởng kết luận. Không cần đưa công thức thống kê vào mọi cuộc họp, nhưng cần người có năng lực phân tích khi kết quả được dùng để mở tự động hóa có hậu quả lớn.

## 8.6. So sánh hai phiên bản công bằng

Giữ bộ câu hỏi, nguồn truy xuất và kết quả công cụ tương đương khi muốn đo riêng tác động của mô hình hoặc prompt. Nếu nhiều thành phần đổi cùng lúc, báo cáo phải nói đó là so sánh toàn hệ thống. Có thể ẩn tên phiên bản với người chấm để giảm thiên kiến. [S11]

Một báo cáo manager dùng được có năm phần: mục tiêu, phiên bản và mẫu, lỗi theo mức độ, thay đổi so baseline, và giới hạn kết luận. Kèm vài ví dụ đại diện tốt hơn hàng trăm dòng “PASS” không có ngữ cảnh.

**Bài tập:** trước một báo cáo “98% đạt”, hãy viết năm câu hỏi: mẫu bao nhiêu; chọn từ đâu; ca nào thất bại; thất bại gây gì; điều kiện nào chưa thử. Chỉ quyết định sau khi hiểu phần 2% còn lại.

**Câu mang vào cuộc họp:** “Những lỗi nào không được phép bị điểm trung bình che đi?”

[Nguồn và giới hạn diễn giải](../nguon/NGUON-VA-PHUONG-PHAP.md) · [Mục lục](../MUC-LUC.md)
