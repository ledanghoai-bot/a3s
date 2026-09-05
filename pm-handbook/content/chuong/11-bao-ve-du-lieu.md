# Chương 11. Bảo vệ dữ liệu từ lúc thiết kế

**Năng lực sau chương:** đặt yêu cầu quản lý dữ liệu rõ ràng, hiểu giới hạn của che thông tin và tránh tuyên bố tuân thủ quá mức.

## 11.1. Vẽ đường đi của dữ liệu trước

Một hội thoại có thể đi qua kênh nhắn tin, máy chủ ứng dụng, nhà cung cấp mô hình, cơ sở dữ liệu, log, công cụ theo dõi và bản sao lưu. Nếu chỉ hỏi “dữ liệu có mã hóa không”, manager có thể bỏ qua ai được xem, gửi đi đâu và giữ bao lâu.

**Data inventory**, danh mục dữ liệu, ghi loại dữ liệu, mục đích, nơi nhận, owner, thời gian giữ và cách xóa. **PII** thường được dùng để chỉ thông tin nhận diện cá nhân; ý nghĩa pháp lý cụ thể tùy phạm vi áp dụng. Trong cẩm nang, dùng khái niệm phổ thông là thông tin có thể nhận ra hoặc liên hệ tới một người, và tránh tự kết luận pháp lý từ tên trường.

Một nguyên tắc quản lý thực dụng là chỉ thu và truyền phần cần cho công việc. Bot cần biết địa chỉ giao hàng khi đặt đơn, nhưng chưa chắc cần gửi toàn bộ địa chỉ cho mô hình để trả lời cách pha. Câu hỏi “cần dữ liệu này để làm gì?” nên xuất hiện trước khi thiết kế nơi lưu.

## 11.2. Che thông tin không đồng nghĩa không còn rủi ro

**Masking**, che thông tin, thay phần nhạy cảm bằng ký hiệu hoặc giá trị đại diện. **Pseudonymization**, giả danh hóa, thay định danh nhưng có thể còn khả năng nối lại. **Anonymization**, ẩn danh hóa, đòi hỏi đánh giá khả năng nhận diện lại; không nên dùng từ này chỉ vì đã xóa tên.

Tình huống chuỗi số M4 cho thấy detector có thể nhầm ngữ nghĩa. Nếu bỏ sót số giấy tờ, thông tin nhạy cảm có thể đi tiếp. Nếu che mã đơn, nhân viên có thể không xử lý được yêu cầu. Manager cần yêu cầu kiểm cả bảo vệ dữ liệu và khả năng sử dụng sau che. [S09]

Không đưa dữ liệu khách thật vào bản test hoặc hồ sơ review chỉ vì “nội bộ”. Hãy tạo ví dụ giả có cấu trúc tương đương, hoặc dùng quy trình làm sạch đã được kiểm tra. Bằng chứng cần đủ để hiểu lỗi nhưng không cần sao chép mọi nội dung hội thoại.

## 11.3. Quyền truy cập và thời hạn

**Least privilege**, quyền tối thiểu, là chỉ cấp đủ quyền cho công việc. Quyền tạm thời cần thời điểm thu hồi và cách xác minh đã thu hồi. Danh sách tài khoản có thể nhìn ổn nhưng quyền hiệu lực qua vai trò vẫn còn; đây là điều đội kỹ thuật cần chứng minh bằng kiểm tra phù hợp.

Closure 175 ghi trạng thái cuối không còn người giữ vai trò M5 tạm và không còn quyền hiệu lực tương ứng. Với manager, giá trị không nằm ở việc nhớ tên quyền mà ở yêu cầu hoàn tất cả cấp, thực hiện, thu hồi và kiểm lại. [S19]

**Key management** là quản lý khóa dùng bảo vệ hoặc ký dữ liệu. **KMS** là dịch vụ quản lý khóa; **HSM** là thiết bị chuyên dụng bảo vệ thao tác mật mã. Chúng là công cụ kỹ thuật; manager cần biết ai sở hữu khóa, ai được dùng, khi người phụ trách nghỉ thì xử lý thế nào và có đường thu hồi khi lộ không. Không cần biến mọi cuộc thử thành nghi thức vận hành trưởng thành.

## 11.4. Giữ và xóa dữ liệu phải có mục đích

**Retention** là thời hạn và quy tắc lưu giữ. Giữ mọi thứ vô hạn tăng chi phí và phạm vi ảnh hưởng khi có sự cố. Xóa quá sớm có thể làm mất khả năng hỗ trợ, điều tra hoặc thực hiện nghĩa vụ. Owner nghiệp vụ cần nêu mục đích, còn chuyên gia phù hợp xác minh yêu cầu pháp lý hiện hành khi áp dụng.

M3 kích hoạt có giới hạn một executor, tức phần thực thi chính sách retention. Hồ sơ ghi hai chính sách được chạy với số ứng viên và số xóa bằng không, các cờ khác vẫn tắt. Điều đó chứng minh đường thực thi được kiểm trong điều kiện ấy; không chứng minh đã xóa thành công dữ liệu thực ở quy mô lớn. [S08]

Manager nên yêu cầu tách **dry run**, chạy xem dự kiến mà chưa thay dữ liệu, khỏi apply, thực thi thay đổi. Trước khi xóa cần biết đối tượng nào bị chọn, có ngoại lệ giữ lại không và kết quả được kiểm thế nào. Bản sao lưu cũng cần chính sách; xóa trong ứng dụng không tự làm dữ liệu biến mất khỏi mọi bản sao.

## 11.5. Nhà cung cấp và lời tuyên bố

Với nhà cung cấp mô hình hoặc kênh, cần biết dịch vụ nhận loại dữ liệu nào, dùng theo điều khoản nào, có nhà thầu phụ liên quan không và ai theo dõi thay đổi. Đây là câu hỏi quản lý nhà cung cấp, không phải khuyến nghị chọn một hãng cụ thể.

Một trang hướng dẫn Alpha3s được sửa theo hướng phổ thông và tránh câu hệ thống tự bảo đảm tuân thủ pháp luật. Bài học là mô tả đúng tác dụng: một kiểm soát có thể góp phần bảo vệ dữ liệu, nhưng một tính năng không tự tạo sự tuân thủ toàn tổ chức. [S23]

Cuốn sách không xác nhận Alpha3s đạt chứng nhận hay tuân thủ luật cụ thể. Khi ra quyết định có hậu quả pháp lý, cần xác minh theo thời điểm, nơi hoạt động, dữ liệu và mục đích thực tế. Các thuật ngữ trong chương giúp manager đặt câu hỏi đúng, không thay thế việc thẩm định.

**Bài tập:** chọn một trường dữ liệu khách hàng. Theo dõi nó qua kênh, mô hình, log, kho chính và backup. Điền mục đích, người xem và cách kết thúc vòng đời ở mỗi nơi. Khoảng trống lớn nhất thường là nơi không ai nghĩ mình là owner.

**Câu mang vào cuộc họp:** “Dữ liệu nào thực sự cần đi tới đây, ai được dùng và bao giờ hết cần giữ?”

[Nguồn và giới hạn diễn giải](../nguon/NGUON-VA-PHUONG-PHAP.md) · [Mục lục](../MUC-LUC.md)
