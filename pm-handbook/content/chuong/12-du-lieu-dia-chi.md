# Chương 12. Dữ liệu mơ hồ: biết khi nào không tự quyết

**Năng lực sau chương:** quản lý dữ liệu có nhiều cách hiểu, đặt ngưỡng và thiết kế đường chuyển người hợp lý.

## 12.1. Một tên đúng có thể chỉ nhiều nơi

M5 xử lý dữ liệu địa chỉ, gồm tên hiện hành, tên cũ và quan hệ hành chính. Review 126 kết luận tên cũ trùng tên chuẩn của một đơn vị khác có thể là sự mơ hồ hợp lệ, không tự động là dữ liệu hỏng. Hệ thống cần giữ các ứng viên và chuyển review khi xuất hiện quan hệ một–nhiều. [S13]

**Canonical name** là tên chuẩn được chọn trong tập dữ liệu. **Alias** là tên khác có thể cùng trỏ tới một đối tượng. **Legacy** chỉ dữ liệu hoặc cách gọi cũ. Một alias trùng canonical của nơi khác không thể được giải quyết chỉ bằng quy tắc “tên chuẩn luôn thắng”, vì điều đó có thể mất ý nghĩa khách muốn nói.

Bài học áp dụng rộng: mã sản phẩm cũ, tên khách trùng nhau, đơn vị đo thay đổi hay dữ liệu từ hệ thống khác đều có thể mơ hồ hợp lệ. Manager cần phân biệt dữ liệu sai với dữ liệu chưa đủ để quyết định.

## 12.2. Điểm tin cậy là tín hiệu, không phải quyền

**Confidence score**, điểm tin cậy, là điểm do hệ thống tạo theo cơ chế của nó. Nếu chưa có đánh giá hiệu chuẩn, không mặc định 0,95 có nghĩa “đúng 95% trong thực tế”. Điểm giúp phân tuyến, nhưng vẫn phải đi cùng điều kiện nghiệp vụ và dữ liệu hợp lệ.

Directive 176 dùng ba vùng: từ 0,95 có thể tự xác minh nếu mọi quy tắc cứng đạt; từ 0,80 đến dưới 0,95 sang xác nhận khách; thấp hơn sang nhân viên. Nhưng quan hệ một–nhiều, cha không khớp hoặc dữ liệu không hợp lệ không được tự chọn bất kể điểm cao. [S20]

**Hard rule**, quy tắc cứng, bảo vệ điều không thể bù bằng điểm. Ví dụ giả định: hai phường cùng tên thuộc hai tỉnh mà khách chưa nói tỉnh thì điểm cao không đủ. Cần thêm thông tin hoặc nhân viên xét. Tự chọn cho nhanh có thể đẩy chi phí sang giao hàng và hỗ trợ sau đó.

## 12.3. Thiết kế đường chuyển tuyến

Có ít nhất ba kết quả tốt: tự xử lý đúng; hỏi khách một câu rõ để xác nhận; chuyển nhân viên kèm thông tin cần thiết. Nếu chỉ tối ưu tỷ lệ tự động, hệ thống có thể tránh chuyển người bằng cách đoán. Manager nên đo cả chất lượng chuyển tuyến và thời gian giải quyết.

Xác nhận khách nên giúp phân biệt các lựa chọn có ý nghĩa. “Bạn xác nhận địa chỉ đúng không?” không hữu ích nếu khách không thấy hệ thống đã hiểu địa chỉ nào. Giao diện cần hiển thị phần được chuẩn hóa và cho phép sửa, đồng thời không làm lộ thông tin của người khác.

Khi chuyển staff review, nhân viên cần thấy đầu vào, các ứng viên, lý do mơ hồ, phiên bản dữ liệu và hành động được phép. Nếu chỉ chuyển một nhãn “confidence thấp”, con người vẫn phải điều tra từ đầu.

## 12.4. Quản lý hiệu lực theo thời gian

Dữ liệu địa giới có thể đổi; đơn đã tạo cần giữ căn cứ tại thời điểm quyết định. **As-of lookup** là tra theo mốc thời gian. **Snapshot** là bản ghi trạng thái cần giữ cho một sự kiện. Nếu luôn ghi đè bằng dữ liệu mới, việc giải thích tại sao đơn cũ dùng địa chỉ cũ trở nên khó.

Với manager, yêu cầu quan trọng là dữ liệu có phiên bản, ngày hiệu lực và quan hệ chuyển đổi được giải thích. Đừng yêu cầu sửa toàn bộ lịch sử sang tên mới mà chưa đánh giá tác động tới đơn, báo cáo và đối soát.

## 12.5. Gate A đạt, điều gì còn chưa đạt?

Closure 175 ghi ingest 3.355 đơn vị và 10.560 alias, một phiên bản dataset active cho development, cùng 2.404 collision được khóa trong gate. Các con số này là kết quả được hồ sơ dự án xác nhận cho tập dữ liệu đó; không phải thống kê hành chính toàn quốc đã được cuốn sách thẩm định độc lập. [S19]

Đích của Gate A là nhập, kiểm, chấp nhận và kích hoạt dữ liệu trong phạm vi development. Gate B kiểm thành phần tìm địa chỉ. Những bước xác nhận khách, quan sát thực tế và áp vào đơn nằm ở phạm vi sau. Tách như vậy giúp một thành công nhỏ không bị kể thành hoàn tất sản phẩm.

## 12.6. Thẻ dữ liệu cho manager

Một **data card**, thẻ mô tả dữ liệu, nên có nguồn, phiên bản, ngày hiệu lực, số lượng, cách biến đổi, người chấp nhận, giới hạn và mục đích được dùng. Khi gặp tập dữ liệu đẹp nhưng thiếu nguồn hoặc cách biến đổi, manager chưa nên xem nó là sẵn sàng sử dụng.

**Data quality**, chất lượng dữ liệu, gồm đúng cấu trúc, đủ trường cần, không trùng sai, quan hệ hợp lệ, có nguồn và phù hợp mục đích. Tập dữ liệu đạt định dạng có thể vẫn không đại diện cách khách diễn đạt. Do đó kiểm dữ liệu và kiểm hành vi trên dữ liệu là hai bước bổ sung.

**Bài tập:** tạo sáu địa chỉ giả gồm tên trùng, thiếu tỉnh, tên cũ, mã không tồn tại, tên không dấu và địa chỉ rõ ràng. Với mỗi ca, quyết định tự xử lý, hỏi lại hay chuyển staff. Viết lý do trước khi xem kết quả hệ thống; đó là đáp án tham chiếu ban đầu của bạn.

**Câu mang vào cuộc họp:** “Trường hợp này thiếu dữ liệu để quyết định, hay dữ liệu thực sự sai?”

[Nguồn và giới hạn diễn giải](../nguon/NGUON-VA-PHUONG-PHAP.md) · [Mục lục](../MUC-LUC.md)
