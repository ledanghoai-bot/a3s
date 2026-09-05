# Chương 18. Xây nhịp quản lý của riêng bạn

**Năng lực sau chương:** kết hợp các bài học thành một cách làm gọn, có thể lặp lại và cải tiến.

## 18.1. Mang nguyên tắc đi, điều chỉnh thủ tục

Alpha3s cung cấp nhiều bài học có thể chuyển sang dự án khác: bắt đầu từ giá trị; quản lý nguồn; tách đề xuất và hành động; kiểm cả ca khó; gắn bằng chứng với phiên bản; phân loại rủi ro; và giữ điểm kết thúc công việc. Số lượng cổng, tên vai trò và ngưỡng kỹ thuật phải được điều chỉnh.

Một cửa hàng nhỏ, một công ty tài chính và một đội nghiên cứu nội bộ không nên dùng cùng một độ nặng quy trình. Điều cần giống là khả năng giải thích vì sao kiểm soát phù hợp với dữ liệu, người dùng và hậu quả.

## 18.2. Sáu hồ sơ cốt lõi

Bạn có thể bắt đầu bằng sáu tài liệu sống. Một trang mục tiêu và phạm vi; danh mục nguồn tri thức; backlog theo kết quả; thỏa thuận DoD cho việc quan trọng; bảng chất lượng/rủi ro; và sổ quyết định/trạng thái phát hành. Biểu mẫu cuối sách hỗ trợ tạo chúng.

“Tài liệu sống” có nghĩa có owner, ngày cập nhật và cơ chế sửa. Nó không có nghĩa ghi đè mọi phiên bản. Bản đã làm căn cứ quyết định phải còn truy được; trang hiện hành dẫn tới bản đó và cho biết điều nào đã thay.

Nếu đội ngũ đã dùng công cụ quản lý công việc, có thể đặt các trường ngay trong ticket. Đừng tạo thêm repo tài liệu chỉ để sao chép nội dung không ai giữ đồng bộ. Cẩm nang này là sản phẩm học tập riêng; quy trình dự án của bạn cần chọn nơi thuận tiện nhất cho người dùng thực tế.

## 18.3. Một nhịp tuần đề xuất

Đầu tuần chốt một hoặc vài kết quả gần, giải quyết quyết định đang chặn và xác nhận phụ thuộc. Giữa tuần xem bằng chứng sớm, nhất là ca khó và giả định rủi ro. Cuối tuần nghiệm thu phần đã đạt, ghi trạng thái cuối và nhìn lại việc làm lại hoặc chờ đợi.

Cuộc họp không cần dài nếu hồ sơ tốt. Một bản cập nhật sáu dòng có thể nêu mục tiêu, đã chứng minh gì, chưa biết gì, blocker thực, quyết định cần và bước tiếp theo. Tránh dùng số tệp hoặc số commit làm thước đo chính.

Nhịp tuần là gợi ý biên tập, không phải lịch vận hành đã được xác nhận của Alpha3s. Có đội cần nhịp nhanh hơn cho sự cố, có đội chỉ cần rà định kỳ khi hệ thống ổn định.

## 18.4. Lộ trình thực hành 30 ngày

| Thời gian | Trọng tâm | Sản phẩm đầu ra |
|---|---|---|
| Ngày 1–5 | Hiểu vấn đề, khách và phạm vi | Đề bài một trang, sơ đồ hành trình |
| Ngày 6–10 | Làm sạch nguồn và chốt hành vi | Danh mục fact, DoD, test quan trọng |
| Ngày 11–15 | Thử một lát cắt và đánh giá | Báo cáo lỗi theo lớp, bản sửa có nguồn |
| Ngày 16–20 | Kiểm hành động, rủi ro, phục hồi | Invariant, bảng quyền, đường dừng |
| Ngày 21–25 | Chuẩn bị người dùng và bàn giao | Runbook, diễn tập, kênh phản hồi |
| Ngày 26–30 | Quyết định bước tiếp | Go/No-Go theo phạm vi, backlog và retrospective |

Đây là kế hoạch học và áp dụng, không cam kết mọi dự án có thể ra mắt trong 30 ngày. Nếu cần xác minh nhà cung cấp, pháp lý, dữ liệu hoặc tích hợp lâu hơn, kết quả tháng đầu có thể là một thử nghiệm nội bộ đáng tin cùng quyết định đầu tư tiếp.

## 18.5. Tự đánh giá năng lực manager

Với mỗi năng lực, tự chấm 0 nếu chưa làm được, 1 nếu làm có trợ giúp, 2 nếu làm độc lập và 3 nếu có thể hướng dẫn người khác. Bảy năng lực là: viết kết quả; xác định nguồn; chốt ranh giới tự động; đọc đánh giá; phân loại rủi ro; nghiệm thu bằng bằng chứng; tổ chức người nhận vận hành.

Không cộng điểm để che một điểm yếu nghiêm trọng. Nếu chưa đọc được bằng chứng giao dịch mà đang mở tự động tạo đơn, hãy bổ sung người có chuyên môn hỗ trợ trước. Điểm số giúp tìm nhu cầu học, không chứng nhận bạn đủ năng lực cho mọi mức rủi ro.

Sau mỗi vòng, chọn một năng lực để cải thiện bằng hành động cụ thể. Ví dụ, tuần tới yêu cầu mọi lỗi có một test trước khi sửa; hoặc chuyển bảng trạng thái từ “đã xong 90%” sang phiên bản, dữ liệu, người dùng và chức năng đang bật.

## 18.6. Khi nào nên dừng hoặc đổi hướng?

Dừng là một quyết định có thể tạo giá trị nếu bằng chứng cho thấy nhu cầu yếu, chi phí không phù hợp hoặc rủi ro vượt khả năng. Có thể giữ tri thức và quy trình đã học để hỗ trợ nhân viên, dù chưa mở bot tự động. Có thể thu hẹp use case hoặc trì hoãn kênh mới để hoàn thiện hành trình chính.

Manager nên nêu điều kiện dừng trước khi đội đã đầu tư quá nhiều và khó rút lui về cảm xúc. **Sunk cost**, chi phí đã bỏ ra không thu hồi được, không nên là lý do duy nhất để chi tiếp. Quyết định vòng sau dựa vào lợi ích và chi phí còn phía trước.

Alpha3s ở mốc hồ sơ của cuốn sách vẫn có phần cần kiểm chứng tiếp. Cách kết thúc trung thực là xác nhận điều đã đạt, giữ rõ điều chưa biết và đặt bước học tiếp có thể kiểm. Đó cũng là cách một manager dẫn dắt dự án AI qua nhiều vòng bất định.

**Bài tập kết chương:** dùng bộ biểu mẫu để lập một gói quyết định cho dự án của bạn: mục tiêu, phạm vi, nguồn, DoD, rủi ro, bằng chứng và bước tiếp. Nhờ một người ngoài dự án đọc và nói lại điều được phép làm. Nếu họ hiểu khác, sửa gói trước khi hành động.

**Câu mang vào cuộc họp:** “Bước tiếp theo nhỏ nhất nào giúp chúng ta học được điều quan trọng mà vẫn kiểm soát được hậu quả?”

[Nguồn và giới hạn diễn giải](../nguon/NGUON-VA-PHUONG-PHAP.md) · [Mục lục](../MUC-LUC.md)
