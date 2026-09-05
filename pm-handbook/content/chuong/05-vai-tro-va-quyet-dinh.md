# Chương 5. Ai quyết định, ai làm, ai chịu trách nhiệm?

**Năng lực sau chương:** thiết kế trách nhiệm thực tế cho đội nhỏ, kể cả khi dùng AI hỗ trợ phân tích và phát triển.

## 5.1. Trách nhiệm không thể giao cho một tên vai trò trống

Trong Alpha3s, PO quyết định phạm vi kinh doanh và chấp nhận rủi ro còn lại; CA đóng vai trò tư vấn kiến trúc và phản biện; Dev triển khai và báo cáo. CA là tên vai trò trong dự án, không phải một chức danh bắt buộc của mọi tổ chức. Trong đội của bạn, trách nhiệm phản biện có thể thuộc technical lead, chuyên gia an toàn hoặc người am hiểu nghiệp vụ. [S17]

Điều quan trọng là một con người có thẩm quyền chịu trách nhiệm cho quyết định ảnh hưởng doanh nghiệp. Nếu một trợ lý AI soạn khuyến nghị hay review, văn bản đó là đầu vào giúp quyết định. Việc AI viết “APPROVED” không tự tạo quyền ngân sách, quyền truy cập hay sự chấp nhận của khách hàng.

Trong đội nhỏ, một người có thể kiêm nhiều vai. Manager cần làm sự kiêm nhiệm nhìn thấy được và thêm điểm kiểm phù hợp ở chỗ có hậu quả lớn. Viết ba chức danh khác nhau vào tài liệu không tạo ra ba góc nhìn độc lập.

## 5.2. RACI vừa đủ dùng

**RACI** là bảng phân công: Responsible là người thực hiện; Accountable là người chịu trách nhiệm cuối cùng; Consulted là người được tham vấn; Informed là người cần được thông báo. Đây là công cụ giao tiếp, không phải bảng để điền mọi người vào mọi ô.

| Quyết định/công việc | Người quyết định cuối | Người thực hiện | Người cần tham vấn |
|---|---|---|---|
| AI được phép hứa gì với khách | PO hoặc owner nghiệp vụ | Người quản lý nội dung | CSKH, chuyên gia phù hợp |
| Thiết kế và kiểm thử tính năng | Người chịu trách nhiệm kỹ thuật | Đội phát triển | PO, QA |
| Chấp nhận chất lượng trải nghiệm | PO | QA và người dùng thử | Nhân viên tuyến đầu |
| Mở chức năng cho khách thật | Owner được tổ chức giao quyền | Người vận hành | Kỹ thuật, nghiệp vụ, an toàn |
| Dừng tính năng khi sự cố | Người trực được giao quyền | Người vận hành | PO và owner bị ảnh hưởng |

Đây là mẫu đề xuất, không phải cơ cấu nhân sự đã được xác minh của Alpha3s. Với đội nhỏ, bảng nên ghi tên thực tế, người thay thế và cách liên hệ. “Ops xử lý” không có ích nếu dự án chưa có Ops.

## 5.3. Tình huống tài khoản có trên giấy

Một lần thực hiện Gate A của M5 dừng ở bước kiểm tra trước chạy vì các danh tính được yêu cầu không tồn tại trên môi trường. Hồ sơ cũng ghi khác biệt giữa mô tả cấp quyền theo người dùng và cơ chế triển khai theo vai trò. Chưa có thao tác ghi nào được thực hiện trong lần dừng đó. [S15]

Bài học không chỉ là kiểm tra tài khoản. Kế hoạch đã giả định một mô hình tổ chức và quyền chưa khớp thực tế. Manager nên yêu cầu kiểm tra danh tính và quyền từ giai đoạn chuẩn bị, trước khi đặt lịch phối hợp. Một placeholder, tức tên điền tạm, phải được đánh dấu và có owner thay bằng giá trị thật.

## 5.4. Phân tách nhiệm vụ theo hậu quả

**Segregation of Duties (SoD)** là phân tách nhiệm vụ để giảm khả năng một người tự tạo và tự xác nhận một hành động nhạy cảm. Với điều chỉnh tồn kho hoặc giao dịch tiền, sự kiểm tra độc lập có giá trị rõ. Trong thử nghiệm nội bộ có dữ liệu giả, yêu cầu nhiều người thật có thể vượt khả năng đội ngũ mà không giảm tương ứng rủi ro.

Memo 169 cho phép dùng trình tự logic, review, danh tính thử riêng hoặc điểm xác nhận PO phù hợp trong development. Khi chuyển sang người vận hành độc lập hay khách thật, các kiểm soát cần được xem lại. Đây là quyết định theo bối cảnh của Alpha3s, không phải lý do chung để bỏ phân quyền. [S17]

Hỏi “ai có thể làm sai hoặc nhầm, và ai phát hiện?” giúp thiết kế SoD thiết thực. Nếu hai tài khoản vẫn do cùng một người dùng, đừng mô tả đó là kiểm tra độc lập giữa hai người. Nó có thể kiểm thử cơ chế phân quyền, nhưng giới hạn của bằng chứng phải được ghi rõ.

## 5.5. Sổ quyết định giúp giảm lệ thuộc trí nhớ

**Decision log** là sổ quyết định. Một bản ghi đủ dùng gồm câu hỏi, các lựa chọn thực tế, quyết định, lý do, người quyết, ngày, phạm vi và điều kiện xem lại. Không cần chép toàn bộ cuộc tranh luận. Điều cần giữ là tại sao lựa chọn hợp lý với thông tin lúc đó.

Ví dụ M2 ghi rõ cách xử lý khi giữ tồn hết hạn, khi hủy trước hoặc sau hoàn tất, và ai phê duyệt điều chỉnh lớn. Những quyết định này là chính sách nghiệp vụ trước khi trở thành đặc tả kỹ thuật. Nếu PO chỉ nói “làm theo chuẩn bán hàng”, đội phát triển phải tự đoán các ngoại lệ. [S22]

## 5.6. Giao việc cho AI mà không đánh mất kiểm soát

Một yêu cầu tốt cho AI hỗ trợ quản lý có mục tiêu, nguồn, giới hạn, dạng đầu ra và điều kiện dừng. Ví dụ: “Từ ba báo cáo này, đối chiếu điểm chưa thống nhất; phân biệt thông tin có nguồn với suy luận; đề xuất câu hỏi cho PO; chưa thay đổi hệ thống.” Với nhiệm vụ tạo tài liệu, không cần yêu cầu AI thực hiện các bước vận hành đang được kể lại trong tài liệu.

Khi AI đưa kết luận, yêu cầu dẫn tới bằng chứng và nêu phần chưa kiểm tra. Hai AI cùng nói “đạt” vẫn có thể cùng dựa vào một báo cáo sai. Sự độc lập đến từ cách kiểm tra và nguồn, không đến từ số lượng tác nhân hay văn phong khác nhau.

**Bài tập:** lấy một quyết định đang treo. Điền người quyết, người làm, người kiểm, người nhận kết quả. Sau đó giả định người quyết vắng mặt hai ngày. Nếu nhóm không biết việc nào tiếp tục được và việc nào phải dừng, hãy bổ sung quyền ủy nhiệm theo phạm vi.

**Câu mang vào cuộc họp:** “Ai thực sự nhận trách nhiệm cho quyết định này, và họ đã có đủ thông tin chưa?”

[Nguồn và giới hạn diễn giải](../nguon/NGUON-VA-PHUONG-PHAP.md) · [Mục lục](../MUC-LUC.md)
