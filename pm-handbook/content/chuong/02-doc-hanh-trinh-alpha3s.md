# Chương 2. Đọc hành trình Alpha3s bằng các quyết định

**Năng lực sau chương:** dựng lại tiến trình dự án mà không nhầm kế hoạch, báo cáo thực hiện và kết quả đã xác nhận.

## 2.1. Một dự án có nhiều lịch sử cùng tồn tại

Alpha3s có tài liệu tri thức, kế hoạch triển khai, báo cáo kỹ thuật, bản phản biện, quyết định PO và hồ sơ đóng mốc. Mỗi loại giải thích một phần câu chuyện. Kế hoạch cho biết dự định; báo cáo cho biết người thực hiện nói đã làm gì; review cho biết điều gì được kiểm tra; closure cho biết phạm vi nào được chấp nhận. Người quản lý cần đọc chúng theo quan hệ, không chỉ tìm tệp có tên “final”.

Cuốn sách dùng một mốc cắt: hồ sơ đã đọc trong workspace đến ngày 05/09/2026. Nó không kiểm tra lại máy chủ, doanh thu hay khách hàng thực tế. Vì thế, mọi sự kiện được trình bày là sự kiện được hồ sơ ghi nhận, với giới hạn tương ứng. Cách nói này giữ độ tin cậy và giúp người học không biến một câu tổng kết thành sự thật vượt quá nguồn.

## 2.2. Bản đồ các chặng chính

| Chặng trong hồ sơ | Quyết định quản lý nổi bật | Bài học |
|---|---|---|
| Nền tảng tri thức tháng 7 | Chốt sự thật sản phẩm, tách tri thức và công cụ | Dữ liệu đúng đi trước câu trả lời hay |
| Core và báo cáo Giai đoạn I | Tích hợp bot, công cụ, kênh và hạ tầng | Chứng minh từng lớp của hành trình |
| Roadmap Customer Terminal | Giới hạn gateway thành lớp giao tiếp mỏng | Giữ phạm vi theo nguồn lực và giá trị |
| M0 | Sửa dữ liệu, quyền, audit và nền migration | Chữa nền trước khi mở rộng nghiệp vụ |
| M1 | Chống đơn trùng, trả kết quả từ giao dịch đã ghi | AI không tự xác nhận thành công |
| M2 | Chốt quy tắc giữ tồn, hủy, hoàn và phê duyệt | PO sở hữu chính sách nghiệp vụ |
| M3 | Kích hoạt có giới hạn phần giữ/xóa dữ liệu | Nói chính xác phần nào đã chạy |
| M4 | Bảo vệ dữ liệu, thử nội bộ, ký và bàn giao | Tách thử nghiệm với sẵn sàng phục vụ |
| M5 | Chuẩn hóa dữ liệu địa chỉ, xử lý mơ hồ | Điểm tin cậy không thay được quy tắc cứng |
| Memo 169/Addendum 171 | Kiểm soát theo rủi ro, chốt DoD trước khi làm | Quản lý cả chi phí của quy trình |
| Closure 175/Directive 176 | Đóng Gate A development, mở build/validation Gate B | Kết quả đã đạt có ranh giới |

Bảng là bản đồ học tập, không gán một ngày hoàn tất duy nhất cho mọi tính năng. Các nguồn S01–S25 ở cuối sách cho phép xem tình huống nào dựa vào hồ sơ nào.

## 2.3. Mâu thuẫn cần giữ lại để học

Roadmap ngày 22/07 mô tả mục tiêu hạ tầng 2 vCPU/4 GB, trong khi báo cáo Giai đoạn I ngày 24/07 ghi máy chủ 4 vCPU/8 GB. Đây là hai mô tả ở hai mốc, không phải hai thông số có thể dùng thay nhau. Cuốn sách giữ sự khác biệt như ví dụ về **baseline**, tức trạng thái tham chiếu đã xác định tại một thời điểm. [S02, S03]

Một khác biệt quan trọng hơn: báo cáo Giai đoạn I dùng ngôn ngữ hoàn tất chuyển kênh lên production; closure M2 ngày 28/07 làm rõ đây là triển khai hạ tầng, chưa public serving, Messenger chưa cutover sang VPS trong bối cảnh được review. Memo 169 sau đó cũng căn cứ vào bối cảnh chưa phục vụ khách thật. Cẩm nang không tự kết luận báo cáo nào mô tả đầy đủ mọi thời điểm. Nó dùng closure có phạm vi cụ thể và ghi lại mâu thuẫn khi giải thích trạng thái. [S03, S07, S17]

Trong thực tế, manager có thể gặp cùng một từ mang nhiều nghĩa: “production” là tên máy chủ, môi trường có dữ liệu thật, hay sản phẩm khách đang dùng. Muốn báo cáo chính xác, hãy thêm ba cột: môi trường nào, dữ liệu nào, hành vi nào đang bật. Một câu “đã lên production” thiếu cả ba cột chưa giúp lãnh đạo quyết định ra mắt.

## 2.4. Đọc phần chuyển tiếp và phần hết hiệu lực

Hồ sơ M5 Kickoff 102 từng được gắn vào hoạt động sẵn sàng vận hành, nhưng được đánh dấu superseded vì phân loại nhầm và dẫn sang M4-102A. Tên tệp còn tồn tại không có nghĩa phạm vi đó còn hiệu lực. [S24]

Một quyết định mới cũng không xóa lịch sử. Memo 169 điều chỉnh phương pháp review tiếp theo; nó không biến các thao tác trước đó thành đã được phép. Closure 175 cập nhật trạng thái dữ liệu từ chưa active sang active cho development; nó không mở các luồng khách hàng phía sau. Bài học là theo dõi cái gì được thay thế, cái gì còn giữ và ai đã quyết định.

Bạn có thể tổ chức lịch sử đơn giản bằng một bảng bốn cột: quyết định, lý do, điều thay thế, trạng thái hiện hành. Khi nhóm quay lại sau vài tuần, bảng này có ích hơn một thư mục hàng trăm tệp không có chỉ dẫn.

## 2.5. Những điều hành trình chưa chứng minh

Hồ sơ đọc được không cung cấp một nghiên cứu trước–sau đủ để kết luận AI đã tăng chuyển đổi, giảm chi phí trên mỗi đơn hay cải thiện hài lòng khách hàng. Không lấy số test pass làm số đo doanh thu. Không suy ra khả năng phục vụ quy mô lớn từ một lần chạy dữ liệu nội bộ.

Tương tự, Gate A active dataset không đồng nghĩa chức năng hiểu địa chỉ đã đạt ở khách thật. Directive 176 còn yêu cầu kiểm thử resolver, tức thành phần tìm địa chỉ phù hợp, trên tập tình huống có kiểm soát. Tách được điều đã biết khỏi điều cần kiểm tra tiếp chính là năng lực quản lý sự bất định. [S19, S20]

Điều này không làm hành trình kém giá trị. Phần học quan trọng nằm ở cách đội ngũ đối phó thông tin sai, kiểm thử chưa đủ, phụ thuộc môi trường, cách hiểu khác nhau về quyền và sự nặng nề của quy trình. Một retrospective, hay buổi nhìn lại có mục đích cải tiến, cần giữ cả tiến bộ và giới hạn ấy.

## 2.6. Bài tập dựng timeline

Chọn năm báo cáo trong dự án của bạn. Với mỗi báo cáo, ghi ngày trong nội dung, phạm vi, tác giả, loại bằng chứng và phần chưa làm. Đừng dùng ngày sửa tệp làm ngày sự kiện nếu không có căn cứ. Sau đó tìm một cặp báo cáo có vẻ mâu thuẫn và viết hai giả thuyết giải thích.

**Gợi ý trả lời tốt:** “Tài liệu A mô tả kế hoạch; B ghi trạng thái sau kiểm tra, nên dùng B cho quyết định hiện tại.” Hoặc: “Hai tài liệu nói về hai kênh khác nhau; cần hỏi owner trước khi gộp.” Câu trả lời yếu là chọn bản có tiêu đề mạnh hơn.

**Câu mang vào cuộc họp:** “Kết luận này đúng với phiên bản, môi trường và phạm vi nào?”

[Nguồn và giới hạn diễn giải](../nguon/NGUON-VA-PHUONG-PHAP.md) · [Mục lục](../MUC-LUC.md)
