# Chương 10. Kiểm soát tương xứng với rủi ro

**Năng lực sau chương:** chọn mức kiểm soát đủ để bảo vệ dự án và tránh biến quy trình thành nguồn trì hoãn.

## 10.1. Kiểm soát cũng có chi phí

Mỗi vòng review cần thời gian chuẩn bị, đọc, sửa và chờ. Mỗi bằng chứng bổ sung có thể giảm một rủi ro, nhưng cũng có thể tạo thêm công cụ cần bảo trì. Manager cần quản lý cả chi phí sai sót lẫn chi phí kiểm soát.

Trong M5, chuỗi review công cụ xác nhận vận hành đi tới nhiều phiên bản. Review 168 vẫn tìm thấy vấn đề về đường dẫn, cách triển khai và phục hồi của công cụ. Memo 169 sau đó điều chỉnh cách làm: không bắt công cụ xác nhận phức tạp trở thành điều kiện cho thử nghiệm development khi quy trình đơn giản đủ kiểm tra phạm vi và trạng thái. [S16, S17]

Bài học không phải các lỗi công cụ không tồn tại. Bài học là phải hỏi dự án có cần công cụ đó ngay để đạt mục tiêu hiện tại không. Nếu giữ nó làm công cụ bàn giao sau này, hãy quản lý như một hạng mục riêng.

## 10.2. Phân loại theo tác động thực tế

Addendum 171 dùng bốn mức nội bộ. Chúng giúp cuộc trao đổi rõ hơn nhưng không phải hệ phân loại quốc tế bắt buộc. [S18]

| Mức dùng trong Alpha3s | Cách hiểu cho manager | Kiểm soát trọng tâm |
|---|---|---|
| DEV-INTERNAL | Thử trong phạm vi tách biệt, chưa tác động khách | Đúng chức năng, dữ liệu thử, cách reset |
| PRE-CUSTOMER | Môi trường dùng chung/đã triển khai nhưng chưa có tác động khách thật | Phạm vi rõ, phiên bản đúng, trạng thái trước–sau, khôi phục |
| CUSTOMER-FACING | Ảnh hưởng khách thật, dữ liệu hoặc hành vi phục vụ | Sẵn sàng vận hành, quyền, riêng tư, giám sát, phục hồi |
| FINANCIAL | Có tiền hoặc cam kết tài chính trong phạm vi | Đối soát, hạn mức, chống trùng, phê duyệt và xử lý hậu quả |

Một script chạy trên laptop nhưng gọi API thanh toán thật không phải thử nghiệm ít rủi ro. Một máy chủ mang tên production nhưng chỉ chứa dữ liệu giả chưa tự có mọi rủi ro của hệ thống phục vụ khách. Hãy xác định dữ liệu, quyền, bên ngoài bị tác động và khả năng khôi phục.

## 10.3. Ba loại phát hiện khi review

Memo 169 tách **BLOCKER NOW**, vấn đề phải xử lý trước khi tiếp tục; **FIX BEFORE HANDOVER**, việc cần hoàn thiện trước bàn giao; và **ADVISORY**, khuyến nghị. Cách phân loại buộc reviewer giải thích thời điểm rủi ro trở nên hiện hữu. [S17]

Ví dụ giả định: sai phiên bản tập dữ liệu là blocker cho lần nhập dữ liệu đang làm. Thiếu lịch trực độc lập có thể là việc trước phục vụ khách nếu hiện chỉ thử nội bộ. Đổi màu nhãn cho dễ đọc có thể là advisory, trừ khi nhãn hiện tại làm người dùng thực hiện nhầm hành động nguy hiểm.

Mức độ không gắn vĩnh viễn vào tên lỗi. Nó phụ thuộc tác động. Manager có quyền yêu cầu nêu rõ: lỗi gây hậu quả gì trong phạm vi hiện tại; khả năng xảy ra dựa vào đâu; kiểm soát đề xuất giảm rủi ro thế nào; có cách nhỏ hơn không.

## 10.4. Chấp nhận rủi ro còn lại có nghĩa gì?

**Residual risk** là rủi ro còn lại sau kiểm soát. Chấp nhận nó là một quyết định có thông tin, có phạm vi và người chịu trách nhiệm. Nó không phải câu “PO đồng ý mọi rủi ro” và không làm biến mất nghĩa vụ của tổ chức.

Một bản ghi tốt nêu rủi ro, vì sao chưa xử lý ngay, ai có thể bị ảnh hưởng, dấu hiệu cần dừng và thời điểm xem lại. Nếu chưa đủ thông tin để hiểu hậu quả, việc phù hợp có thể là thử nhỏ để giảm bất định trước khi chấp nhận.

**Ví dụ giả định:** dùng một máy chủ ở giai đoạn thử nghiệm, chấp nhận khả năng gián đoạn để giữ chi phí thấp, nhưng vẫn có bản sao lưu khôi phục được. Khi bắt đầu nhận đơn thật liên tục, yêu cầu thời gian phục hồi được xem lại. Đây là quyết định theo vòng đời, không phải mặc định dùng kiến trúc rẻ mãi.

## 10.5. Một cửa kiểm soát cần thay đổi được quyết định

**Gate** là điểm quyết định đi tiếp, sửa, dừng hoặc giới hạn phạm vi. Nếu một gate chỉ xác nhận đã có đủ tệp mà không đổi hành động, hãy xem lại mục đích. Gate nên gắn với một chuyển đổi có ý nghĩa: dùng dữ liệu thật, mở kênh, bật hành động ghi hoặc bàn giao người mới.

Ngược lại, không cần một gate mới cho mọi sửa lỗi câu chữ. Khi phạm vi đã được giao rõ và hành động có thể đảo lại, nhóm nên tiếp tục trong quyền đã nhận. Điều quan trọng là có ranh giới để biết khi nào thực sự cần quyết định mới.

## 10.6. Khi quy trình bắt đầu cản dự án

Dấu hiệu gồm lặp lại yêu cầu bằng chứng không đổi kết luận, thêm chuẩn sau mỗi lần nộp, xây công cụ chỉ để chứng minh công cụ khác, và không ai nói được điều kiện đóng. Đây là lúc manager yêu cầu một review tổng hợp theo mục tiêu và rủi ro đã chốt.

Không giải quyết bằng việc bỏ mọi kiểm tra. Hãy giữ các kiểm soát bảo vệ dữ liệu, phạm vi, kết quả và phục hồi; chuyển phần chưa cần sang backlog có trigger. Đo số vòng sửa, thời gian chờ và lỗi lọt qua để biết quy trình tinh gọn có hiệu quả không.

**Bài tập:** lấy một checklist dài. Với từng mục, điền rủi ro cụ thể đang giảm. Nếu không giải thích được, hỏi lại owner trước khi giữ nó làm điều kiện chặn. Với mục bỏ khỏi hiện tại, ghi khi nào cần mở lại.

**Câu mang vào cuộc họp:** “Kiểm soát này đang giảm rủi ro nào đang tồn tại, với chi phí bao nhiêu?”

[Nguồn và giới hạn diễn giải](../nguon/NGUON-VA-PHUONG-PHAP.md) · [Mục lục](../MUC-LUC.md)
