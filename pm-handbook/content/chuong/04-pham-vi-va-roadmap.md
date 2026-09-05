# Chương 4. Giữ phạm vi và chọn thứ tự tạo giá trị

**Năng lực sau chương:** tổ chức roadmap theo kết quả và phụ thuộc, đồng thời trì hoãn hợp lý những việc chưa cần.

## 4.1. Bước lùi về thiết kế có thể là bước tiến về sản phẩm

Roadmap Alpha3s xác định lại Gateway thành Customer Terminal mỏng. Lớp này nhận, chuẩn hóa, chống trùng, giữ thứ tự, chuyển yêu cầu và giao phản hồi; ứng dụng hiện tại tiếp tục giữ tri thức và dữ liệu nghiệp vụ. Dự án tránh tạo thêm mô hình khách hàng, hội thoại và quyền quyết định trùng lặp. [S02]

Đó là bài học về **scope**, tức phạm vi công việc. Khi nhóm nói “nhân tiện xây một nền tảng dùng cho nhiều thương hiệu”, manager phải hỏi nhu cầu nào hiện tại cần nó. Có những khoản đầu tư nền tảng đáng làm, nhưng chúng cần lý do và điều kiện kích hoạt, không chỉ dựa vào việc kỹ thuật có thể thực hiện.

Phạm vi tốt không chỉ liệt kê tính năng làm. Nó còn mô tả người dùng, dữ liệu, môi trường, hành động và các phần phụ thuộc. Một công cụ thử nghiệm nội bộ khác đáng kể với cùng công cụ đó khi dùng thông tin khách thật và gửi thông báo ra ngoài.

## 4.2. Chia theo lát cắt sử dụng được

**Vertical slice**, hay lát cắt xuyên suốt, là một phần nhỏ nhưng đi trọn hành trình. Ví dụ, khách trên web hỏi sản phẩm, nhận câu trả lời đúng và được chuyển nhân viên thành công. Cách chia “làm hết cơ sở dữ liệu, rồi làm hết AI, rồi mới làm giao diện” khiến rủi ro tích hợp chỉ xuất hiện cuối kỳ.

Roadmap đặt các chặng hoàn tất core, hạ tầng, độ tin cậy, Messenger/Web, Zalo và tăng cường khi có bằng chứng. Những chặng nền được giải thích bằng việc chúng mở đường cho giá trị ở kênh khách. Đây là cách người quản lý giữ liên kết giữa đầu tư kỹ thuật và mục tiêu kinh doanh. [S02]

Một lát cắt vẫn có thể dành cho nền tảng nếu kết quả rõ: khôi phục được bản sao lưu trong diễn tập, không nhân đôi giao dịch khi gửi lại, hoặc nhân viên tiếp nhận được ca chuyển. “Nâng cấp kiến trúc” quá rộng; “chứng minh gửi lại không tạo đơn thứ hai” là kết quả có thể nghiệm thu.

## 4.3. Quản lý phụ thuộc trước khi chúng chặn đường

**Dependency**, hay phụ thuộc, là điều một công việc cần từ công việc khác hoặc bên ngoài. Tích hợp kênh có thể chờ tài khoản được xác minh. Đưa bot vào dùng có thể chờ nội dung sản phẩm. Bật dữ liệu địa chỉ có thể chờ quyền phù hợp trên môi trường thật.

Roadmap đặt việc chuẩn bị Zalo sớm do có thời gian chờ bên ngoài. Cẩm nang không dùng các cửa sổ tin nhắn hay số tin miễn phí trong roadmap làm chính sách hiện hành; những giá trị đó phải xác minh lại khi triển khai. Bài học ổn định là phân biệt thời gian đội ngũ làm với thời gian phải chờ nhà cung cấp. [S02]

Một bảng phụ thuộc tối thiểu có hạng mục, bên cung cấp, ngày cần, tình trạng và phương án nếu chậm. Nếu phụ thuộc có thể chuẩn bị sớm bằng một hành động nhỏ, hãy mở việc đó trước. Nếu chưa chắc có nhu cầu, đừng xây toàn bộ tích hợp chỉ để tránh khả năng phải chờ.

## 4.4. Backlog cần cả giá trị và rủi ro

**Backlog** là danh sách công việc được sắp thứ tự, không phải kho mong muốn vô hạn. Manager có thể nhìn mỗi hạng mục qua bốn câu: nó giúp ai; giảm rủi ro gì; mở khóa việc nào; chi phí dự kiến và độ không chắc chắn ra sao.

Đừng biến phép tính ưu tiên thành độ chính xác giả. Điểm số 8,3 so với 8,1 không có ý nghĩa nếu lợi ích đều là phỏng đoán. Với dữ liệu ít, phân nhóm “cần để học”, “cần để bảo vệ”, “cần để mở rộng” thường giúp cuộc thảo luận rõ hơn. Sau mỗi vòng, cập nhật bằng kết quả thật.

**Ví dụ giả định:** thêm giọng nói có thể hấp dẫn, nhưng giá hiện hành chưa được lấy đúng. Sửa đường giá phải đứng trước vì nó bảo vệ lòng tin và giao dịch đang thuộc phạm vi. Nếu khách chưa dùng giọng nói, việc đó có thể ghi là trì hoãn đến khi có tỷ lệ yêu cầu đủ đáng kể do PO xác định.

## 4.5. Ghi điều kiện mở lại việc đã hoãn

**Defer** là trì hoãn có chủ đích; **drop** là loại bỏ. Một việc được defer cần điều kiện xem lại, gọi là **trigger**. Ví dụ: cân nhắc thêm máy chủ khi số đo tài nguyên hoặc yêu cầu phục hồi vượt khả năng hiện tại; cân nhắc nhiều nhân viên vận hành khi tải công việc và nhu cầu phân quyền tăng.

Nếu không có trigger, việc hoãn dễ quay lại mỗi cuộc họp dưới một tên khác. Nếu trigger quá mơ hồ như “khi quy mô lớn”, không ai biết khi nào cần hành động. Hãy gắn với bằng chứng quan sát được và người theo dõi. Giá trị ngưỡng phải được chọn theo bối cảnh, không chép từ Alpha3s.

## 4.6. Xử lý yêu cầu thay đổi giữa đường

**Change request**, hay yêu cầu thay đổi, nên nói rõ điều mới, lý do, ảnh hưởng và lựa chọn. Nếu thêm kiểm tra địa chỉ làm chậm mục tiêu đặt hàng, manager cần biết có thể đưa vào vòng sau hay dùng xác nhận thủ công trước không. Đội ngũ cần được phép đưa ra phương án nhỏ hơn.

Một quyết định tốt có thể là làm ngay, hoãn, thử nhỏ hoặc từ chối. Điều quan trọng là ghi tác động tới điều kiện hoàn thành và kỳ vọng. Không âm thầm thêm tiêu chí vào giữa vòng sửa lỗi rồi đánh giá đội thực hiện là chậm.

**Bài tập:** chọn mười hạng mục đang mở. Mỗi hạng mục viết một kết quả sử dụng, một phụ thuộc và một lý do thứ tự. Chọn ba việc có thể hoãn kèm trigger. Kiểm tra liệu roadmap còn một hành trình nhỏ có thể hoàn tất trong vòng tới hay chỉ còn các mảnh kỹ thuật rời nhau.

**Câu mang vào cuộc họp:** “Việc này mở khóa kết quả nào, và dấu hiệu nào buộc chúng ta phải làm ngay?”

[Nguồn và giới hạn diễn giải](../nguon/NGUON-VA-PHUONG-PHAP.md) · [Mục lục](../MUC-LUC.md)
