# Chương 3. Hiểu hệ thống AI đủ để quản lý

**Năng lực sau chương:** giải thích đường đi từ câu hỏi đến hành động và nhận ra vị trí cần kiểm soát.

## 3.1. Đừng quản lý mọi thứ như một chiếc hộp AI

Một trợ lý bán hàng gồm nhiều phần. Kênh nhận tin chuyển yêu cầu vào hệ thống. Thành phần hiểu ngôn ngữ đoán khách muốn gì. Bộ tìm kiếm lấy thông tin liên quan. Mô hình soạn lời đáp. Công cụ nghiệp vụ đọc hoặc thay đổi dữ liệu. Hàng đợi chuyển việc và gửi tin. Nhân viên xử lý phần cần phán đoán.

Khi câu trả lời sai, nguyên nhân có thể nằm ở bất kỳ đoạn nào. Đổi mô hình trong khi nguồn giá sai chỉ làm câu sai trở nên trôi chảy hơn. Viết thêm hướng dẫn trong prompt, tức chỉ dẫn đưa cho mô hình, không thay cho việc hệ thống kiểm quyền tạo đơn. Manager cần bản đồ này để yêu cầu điều tra đúng chỗ.

```text
Khách đặt câu hỏi
    → xác định nhu cầu
    → chọn tri thức / công cụ / người thật
    → lấy dữ liệu và kiểm điều kiện
    → soạn phản hồi hoặc thực hiện hành động được phép
    → gửi kết quả và ghi nhận trạng thái
    → theo dõi, tiếp nhận sửa sai
```

Đây là sơ đồ khái niệm phục vụ quản lý; kiến trúc triển khai có thể khác. Điểm cần giữ là đường đi của thông tin, quyền và trách nhiệm.

## 3.2. RAG bằng ngôn ngữ đời thường

**Retrieval-Augmented Generation (RAG)** là cách cho mô hình tìm và dùng tài liệu liên quan khi trả lời. Hãy hình dung một nhân viên được đưa đúng trang sổ tay trước khi nói với khách. **Retrieval** là bước tìm trang; **generation** là bước diễn đạt câu trả lời. Nếu lấy nhầm trang, mô hình vẫn có thể nói rất tự tin.

Alpha3s chọn tìm kiếm kết hợp theo ý nghĩa và từ khóa, rồi sắp lại kết quả. Hồ sơ nêu nhu cầu xử lý tiếng Việt, tên sản phẩm, mã hàng và câu hỏi trộn ngôn ngữ. Đây là lựa chọn thiết kế được ghi nhận, không phải bằng chứng mọi câu hỏi đều được tìm đúng. [S21]

Với manager, ba câu quan trọng hơn tên thuật toán: tài liệu nào được phép đưa vào; làm sao biết lấy đúng tài liệu; khi không tìm thấy thì hệ thống nói gì. Một quy trình tri thức tốt cũng cần ngày hiệu lực, người duyệt, phiên bản và cách thu hồi nội dung cũ.

## 3.3. Hiểu ý định khác với biết sự thật

**Natural Language Understanding (NLU)** là hiểu ý định và thông tin trong câu khách nói. “Cho mình hai hũ” có ý định mua và số lượng hai; nó chưa cho biết giá hay tồn kho. **Entity**, hay thực thể được nhận diện, có thể là sản phẩm, số lượng, địa điểm. Nhận diện đúng thực thể không chứng minh giao dịch được phép.

Roadmap Alpha3s ghi bài học về xử lý tiếng Việt: bỏ dấu để so khớp có thể làm những từ khác nghĩa trở thành giống nhau. Bài học quản lý là yêu cầu ví dụ địa phương trong bộ kiểm thử. Một benchmark tiếng Anh tốt không bảo đảm khách viết tắt, không dấu, đổi ý giữa chừng hay dùng từ vùng miền được xử lý đúng. [S02]

## 3.4. Công cụ là nơi dữ liệu sống được xác nhận

**Tool calling**, hay gọi công cụ, là mô hình đề nghị dùng một chức năng như tra tồn hoặc tạo đơn. Phần thực thi phải kiểm dữ liệu đầu vào, quyền và quy tắc nghiệp vụ. Việc mô hình gọi được tên công cụ không đồng nghĩa nó được phép làm mọi việc trong công cụ đó.

Foundation của Alpha3s tách thông tin ổn định đã duyệt vào tri thức; dữ liệu động và riêng theo khách vào công cụ; quyết định rủi ro cao về con người. Bạn có thể áp dụng bằng một bảng nguồn trả lời. Cách pha đi từ tài liệu sản phẩm; giá đi từ hệ thống giá; trạng thái đơn đi từ bản ghi đơn được kiểm quyền; ngoại lệ khiếu nại đi tới nhân viên. [S01]

Một nguyên tắc hữu ích là: lời hứa với khách phải theo trạng thái đã được xác nhận. Trong M1, phản hồi có mã đơn, số lượng và tổng tiền phải lấy từ kết quả giao dịch đã ghi, thay cho lời tự do của mô hình. Đây là **authoritative data**, tức dữ liệu có thẩm quyền cho quyết định cụ thể. [S06]

## 3.5. Chất lượng là đặc tính của cả hành trình

Bạn có thể có mô hình tốt nhưng tin nhắn đến hai lần, hàng đợi mất việc hoặc nhân viên không thấy ca chuyển. **End-to-end (E2E)** nghĩa là từ đầu đến cuối hành trình. Một kiểm tra E2E nên bắt đầu bằng câu khách nói và kết thúc bằng trạng thái người dùng có thể quan sát: biết đơn nào được ghi, có người tiếp nhận, hoặc biết vì sao chưa thể hoàn tất.

**Latency**, hay độ trễ, cũng phải đo theo trải nghiệm. Khách quan tâm mất bao lâu nhận được kết quả có ích, không chỉ thời gian mô hình sinh chữ. Chờ công cụ, gửi lại và chờ nhân viên đều có thể là phần lớn của thời gian. Manager nên yêu cầu bảng tách thời gian theo bước trước khi tăng ngân sách mô hình.

## 3.6. Cách trao đổi với đội kỹ thuật

Thay câu “AI chưa thông minh” bằng một tình huống tái hiện: khách hỏi gì, nguồn đúng là gì, kết quả đang ra sao, hậu quả là gì. Nhờ đội kỹ thuật phân loại lỗi: nguồn, tìm kiếm, chọn đường xử lý, diễn đạt, công cụ hay vận hành. Việc phân loại giúp chọn owner và cách kiểm tra sửa lỗi.

Đừng yêu cầu kiến trúc chi tiết nếu câu hỏi quản lý chỉ cần sơ đồ một trang. Ngược lại, đừng duyệt tự động hóa có tác động tiền chỉ từ bản mô tả trải nghiệm. Mức chi tiết nên theo quyết định đang cần và hậu quả của sai sót.

**Bài tập:** vẽ một hành trình đặt hàng bằng sáu ô. Đánh dấu ô nào do AI đề xuất, ô nào do hệ thống kiểm chứng, ô nào do người duyệt. Với mỗi mũi tên, viết điều gì xảy ra khi bước trước không trả kết quả. Nếu có mũi tên không có người chịu trách nhiệm, đó là một câu hỏi cần giải quyết trước nghiệm thu.

**Câu mang vào cuộc họp:** “Sai ở nguồn, ở cách hiểu, ở hành động hay ở việc giao kết quả cho khách?”

[Nguồn và giới hạn diễn giải](../nguon/NGUON-VA-PHUONG-PHAP.md) · [Mục lục](../MUC-LUC.md)
