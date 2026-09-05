# Chương 14. Từ đã xây xong đến có thể phục vụ khách

**Năng lực sau chương:** phân biệt các trạng thái phát hành và tổ chức quyết định mở chức năng theo mức ảnh hưởng.

## 14.1. Một chữ “xong” không đủ

Playbook Alpha3s tách development acceptance, sẵn sàng merge, quyền triển khai, xác minh môi trường và closure. M1 được chấp nhận development nhưng chưa cho merge vì nhánh chính có cơ chế tự deploy. M2 đóng triển khai mã và schema nhưng giữ các cờ chức năng tắt. [S06, S07, S25]

**Merge** là hợp nhất thay đổi mã nguồn. **Deploy** là đưa phiên bản tới môi trường chạy. **Release** thường chỉ đưa chức năng tới người sử dụng; nghĩa cụ thể cần thống nhất trong tổ chức. **Activation** là bật khả năng đã có. Các thao tác có thể nối tự động, nhưng vẫn mang hậu quả khác nhau.

Manager không cần bắt buộc bốn cuộc họp riêng. Cần biết quyết định hiện tại bao gồm thao tác nào và phần nào chưa thuộc quyền đó. Nếu một nút merge làm deploy ngay, review phải biết liên kết này trước khi bấm.

## 14.2. Triển khai nhưng chưa bật

**Feature flag**, cờ chức năng, cho phép giữ tính năng ở trạng thái tắt dù mã đã triển khai. **Dormant** nghĩa là chưa hoạt động trong phạm vi đã xác định. M4 dùng con đường này để hoàn thiện tích hợp và thử nội bộ mà chưa mở dữ liệu khách hoặc public activation. [S08, S14]

Không nên hiểu một cờ tắt là mọi rủi ro bằng không. Mã mới vẫn có thể ảnh hưởng khởi động, cơ sở dữ liệu hoặc đường dùng chung. Vì vậy cần kiểm phần nền bị tác động và kiểm trạng thái cờ thực tế sau deploy, không chỉ đọc giá trị mặc định trong tài liệu.

Một bảng trạng thái cho manager nên tách: phiên bản đã xây, đã review, đã triển khai, nhóm được dùng, dữ liệu được dùng, hành động đang bật và người trực. Bảng này hữu ích hơn phần trăm hoàn thành chung khi chuẩn bị ra mắt.

## 14.3. Thử nhỏ nhưng đủ điều kiện

**Rehearsal**, diễn tập, tập trước quy trình trong điều kiện được kiểm soát. **Canary**, mở thử cho nhóm nhỏ, giúp quan sát trước khi mở rộng. **Shadow mode**, chạy quan sát song song, tạo kết quả để so sánh nhưng không để kết quả mới quyết định hành vi chính. Đây là các cách giảm phạm vi tác động; chúng không tự tạo chất lượng.

Mỗi cách cần câu hỏi rõ. Diễn tập kiểm thao tác và khả năng phục hồi. Canary kiểm trải nghiệm trong phạm vi nhỏ thật. Shadow kiểm kết quả mới so với đường hiện hành. Nếu dùng dữ liệu thật, vẫn cần yêu cầu phù hợp về quyền, mục đích và giám sát.

Trong M4, ngưỡng thử nội bộ được tách khỏi ngưỡng quan sát hội thoại khách. Bài học là không ép dữ liệu giả chứng minh thống kê khách thật và không dùng kết quả nội bộ để tuyên bố hiệu năng công khai. [S14]

## 14.4. Danh sách Go/No-Go của manager

**Go/No-Go** là quyết định đi tiếp hoặc chưa đi tiếp. Trước mở cho khách, hãy kiểm mục tiêu và nhóm người dùng, phiên bản và cấu hình, dữ liệu được phép, chất lượng đã kiểm, người hỗ trợ, tín hiệu lỗi và cách dừng. Phần kỹ thuật có thể có nhiều chi tiết hơn, nhưng manager cần nhìn được hệ quả.

| Câu hỏi | Bằng chứng nên có |
|---|---|
| Chúng ta đang bật đúng bản? | Phiên bản và kết quả kiểm tương ứng |
| Khách nào chịu ảnh hưởng? | Phạm vi kênh/nhóm và cách giới hạn |
| Nếu sai thì phát hiện thế nào? | Chỉ số, cảnh báo, người nhận |
| Nếu cần dừng thì ai làm? | Quyền dừng và hướng dẫn đã thử |
| Phần đã xảy ra được xử lý ra sao? | Đối soát và kế hoạch hỗ trợ |
| Khi nào mở rộng? | Điều kiện đánh giá và owner quyết định |

Đây là mẫu thực hành đề xuất. Không dùng như bằng chứng rằng Alpha3s đã đạt mọi điều kiện cho khách thật.

## 14.5. Tránh nhầm tín hiệu sức khỏe

Một trang trả mã thành công có thể chỉ cho biết máy chủ còn trả lời. Nó không chứng minh khách nhận được phản hồi đúng hay người dùng có quyền truy cập. Closure M2 làm rõ mã từ chối của endpoint webhook trong một kiểu gọi không phải tín hiệu hệ thống hỏng. [S07]

Manager nên yêu cầu **service health**, sức khỏe dịch vụ, gắn với hành trình: tin được nhận, việc được xử lý, kết quả được gửi, và ngoại lệ tới đúng người. Một vài kiểm tra kỹ thuật là cần, nhưng kết quả sử dụng mới quyết định trải nghiệm.

## 14.6. Cập nhật trạng thái sau thay đổi

Sau deploy hoặc activation, ghi trạng thái thực tế thay vì chỉ nói “đã chạy lệnh”. Cờ nào bật, phiên bản nào hoạt động, kiểm tra nào đạt, có sai lệch gì, cần theo dõi thêm gì. Khi trạng thái mới đã được chấp nhận, tài liệu tham chiếu phải cập nhật để vòng sau không yêu cầu trở về một điều kiện cũ đã hết hiệu lực.

Closure 175 là ví dụ: active dataset cho development thay thế trạng thái NULL trước đó, nhưng không mở các gate sau. Một manager phải giữ được cả phần thay đổi và phần vẫn chưa được phép. [S19]

**Bài tập:** viết thông báo phát hành năm dòng cho một tính năng. Cần có ai được dùng, dữ liệu gì, trạng thái nào, giới hạn gì và người hỗ trợ. Nếu chỉ có “v1.2 đã deploy thành công”, hãy bổ sung thông tin để bộ phận kinh doanh không hiểu nhầm.

**Câu mang vào cuộc họp:** “Đã triển khai ở đâu, đã bật cho ai, và đã kiểm trải nghiệm nào?”

[Nguồn và giới hạn diễn giải](../nguon/NGUON-VA-PHUONG-PHAP.md) · [Mục lục](../MUC-LUC.md)
