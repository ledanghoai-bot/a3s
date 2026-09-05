# Chương 16. Quản lý chi phí, thời gian và giá trị thu được

**Năng lực sau chương:** lập mô hình chi phí đầy đủ, tránh tối ưu giá mô hình mà bỏ qua công sức con người và chất lượng.

## 16.1. Hóa đơn mô hình chỉ là một phần

**Total Cost of Ownership (TCO)** là tổng chi phí sở hữu và vận hành trong một khoảng thời gian. Với AI, nó gồm thiết lập, mô hình, hạ tầng, kênh, dữ liệu, đánh giá, xử lý ngoại lệ, hỗ trợ, sự cố và bảo trì. Một mô hình rẻ hơn có thể tạo nhiều ca chuyển hoặc lỗi hơn, làm tổng chi phí tăng.

**Token** là đơn vị mô hình dùng để xử lý văn bản; nó không đồng nhất với từ hay ký tự. Manager cần số đo chi phí trên công việc hoàn thành, không chỉ giá trên token. Cuộc hội thoại dài, tìm kiếm nhiều, thử lại và gọi công cụ đều có thể tăng chi phí.

Cuốn sách không sử dụng giá nhà cung cấp hiện hành hoặc ước tính lợi nhuận Alpha3s. Công thức và số minh họa bên dưới là bài tập quản lý, cần thay bằng dữ liệu hợp đồng và đo thực tế của bạn.

## 16.2. Lập mô hình theo đơn vị công việc

Một đơn vị hữu ích có thể là hội thoại được giải quyết đúng, đơn hợp lệ hoặc yêu cầu hỗ trợ hoàn tất. Chi phí trên đơn vị bằng tổng chi phí có liên quan chia số đơn vị đạt định nghĩa đó. Cần giữ cách định nghĩa nhất quán giữa các tháng.

**Ví dụ giả định:** một tháng có 1.000 yêu cầu, 600 được AI giải quyết đúng không cần người sửa, 400 chuyển nhân viên. Chi phí hệ thống là 1,2 triệu đồng; xử lý ngoại lệ là 1,6 triệu; bảo trì là 1 triệu. Tổng vận hành là 3,8 triệu trước chi phí xây ban đầu. Chỉ báo cáo 1,2 triệu sẽ bỏ phần lớn công sức liên quan.

Muốn so với cách làm cũ, cần cùng phạm vi: 1.000 yêu cầu tương đương, cùng mức chất lượng và cách tính thời gian. Nếu đội vẫn kiểm lại mọi câu AI trả lời, thời gian tiết kiệm có thể thấp hơn dự kiến. Phải tính việc mới phát sinh chứ không chỉ thời gian gõ câu trả lời.

## 16.3. Đo baseline trước khi tuyên bố tiết kiệm

**Baseline** ở đây là mức tham chiếu trước thay đổi: lượng yêu cầu, thời gian xử lý, tỷ lệ sửa lại, chất lượng và chi phí. Không có baseline thì kết luận “nhanh hơn” dễ dựa vào cảm giác.

Trong giai đoạn đầu, có thể lấy mẫu nhỏ có chủ đích để hiểu cấu trúc công việc, ghi rõ giới hạn. Khi dùng kết quả để quyết định đầu tư lớn, cần mẫu đại diện và cách phân tích chặt hơn. Không lấy một ngày nhàn so với một ngày cao điểm rồi quy toàn bộ khác biệt cho AI.

Với Alpha3s, hồ sơ đọc được chưa đủ để tính ROI đã thực hiện. **Return on Investment (ROI)** là tỷ suất lợi ích so với khoản đầu tư theo phương pháp đã chọn. Chương này đề xuất cách đo cho vòng sau, không điền doanh thu giả để làm câu chuyện trọn vẹn.

## 16.4. Theo dõi chi phí của chờ đợi và làm lại

**Lead time** là thời gian từ yêu cầu tới kết quả; **cycle time** thường là thời gian từ khi bắt đầu xử lý đến hoàn tất, tùy cách tổ chức định nghĩa. Hãy công bố mốc đo. Tách thời gian làm, chờ và sửa để biết nút thắt nằm ở đâu.

Memo 169 và Addendum 171 nhắm tới giảm vòng review và chốt tiêu chí trước khi làm. Để biết có hiệu quả, nên đo số vòng sửa do thay yêu cầu, thời gian chờ phản hồi và lỗi quan trọng lọt qua. Ít vòng hơn nhưng nhiều lỗi hơn chưa chắc là tiến bộ; nhiều tệp hơn cũng chưa chắc kiểm soát tốt hơn. [S17, S18]

## 16.5. Ngân sách đi cùng giới hạn hành vi

**Budget cap** là trần chi phí; cảnh báo giúp biết sắp chạm trần, còn cơ chế dừng giới hạn hậu quả. Nếu gửi lại một tin bị tính hai lần trong sổ ngân sách, bạn có thể dừng quá sớm; nếu thử lại không được tính đúng, bạn có thể vượt trần. Roadmap Alpha3s nêu nhu cầu kế toán chi phí kênh nhất quán với chống trùng. [S02]

Manager cần xác định kỳ ngân sách, owner nhận cảnh báo, hành động khi gần trần, phần được ưu tiên và cách tiếp tục phục vụ. Không chỉ ghi “có giám sát chi phí” mà chưa có ai quyết định khi vượt.

## 16.6. Khi nào mở rộng?

Mở rộng hợp lý khi hành trình nhỏ đã tạo giá trị, lỗi quan trọng được kiểm soát, người vận hành theo kịp và chi phí đơn vị có thể chấp nhận. Một kênh mới có thể đem thêm khách nhưng cũng thêm hỗ trợ, chính sách và điểm lỗi.

Thay vì hứa một ROI chắc chắn, trình bày ba kịch bản với các giả định khác nhau về lượng dùng, tỷ lệ cần người và chi phí phục vụ. **Sensitivity analysis**, phân tích độ nhạy, cho biết biến nào làm kết luận đổi mạnh nhất. Nếu tỷ lệ chuyển người quyết định chi phí, đầu tư vào chất lượng và quy trình handoff có thể đáng hơn tối ưu vài phần trăm token.

**Bài tập:** lập bảng chi phí tháng với ba mức lượng dùng. Tính lại khi tỷ lệ cần người tăng gấp đôi. Ghi rõ điều gì sẽ khiến bạn dừng mở rộng, điều gì đáng thử tiếp và dữ liệu nào còn thiếu.

**Câu mang vào cuộc họp:** “Chi phí cho một công việc được giải quyết đúng là bao nhiêu, kể cả phần con người phải sửa?”

[Nguồn và giới hạn diễn giải](../nguon/NGUON-VA-PHUONG-PHAP.md) · [Mục lục](../MUC-LUC.md)
