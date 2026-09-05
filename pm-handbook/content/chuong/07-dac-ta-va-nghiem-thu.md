# Chương 7. Chốt “xong nghĩa là gì” trước khi bắt đầu

**Năng lực sau chương:** viết yêu cầu có thể kiểm tra, thống nhất tiêu chí và kiểm soát thay đổi trong quá trình review.

## 7.1. Một từ “đúng” có nhiều cách hiểu

PO có thể hiểu “kiểm tra địa chỉ đúng” là khách nhận được hàng. Người làm dữ liệu hiểu là mã địa chỉ hợp lệ. Người viết phần mềm hiểu là hàm trả đúng cấu trúc. Người kiểm an toàn hiểu là không tự chọn khi mơ hồ. Mỗi cách đều hợp lý trong phạm vi riêng nhưng chưa tạo một điều kiện hoàn thành chung.

**Acceptance criteria**, tiêu chí chấp nhận, mô tả hành vi cụ thể của một hạng mục. **Definition of Done (DoD)** là định nghĩa trạng thái hoàn thành theo chất lượng đã thống nhất. Trong handbook, dùng hai khái niệm để tách câu chuyện người dùng khỏi các yêu cầu chất lượng chung; không xem mọi checklist nội bộ là thực hành Scrum chính thức.

Addendum 171 của Alpha3s đưa ra thỏa thuận trước khi xây dựng: mục tiêu, rủi ro, phạm vi, DoD, mối đe dọa thực tế, giao diện cần khóa, bằng chứng, cách khôi phục và người review. Với việc nhỏ, nội dung này có thể nằm ngay trong ticket. [S18]

## 7.2. Viết bằng tình huống và kết quả

Một cách viết dễ hiểu là “khi… trong điều kiện… thì…”. Ví dụ giả định: khi khách gửi lại cùng yêu cầu đặt hàng do mạng chậm, trong khi đơn trước đã được ghi thành công, hệ thống trả lại kết quả cũ và không tạo đơn thứ hai. Bạn có thể kiểm tra câu này mà không cần đọc mã nguồn.

Tiêu chí cũng phải có tình huống không thành công: khi không tra được giá thì chưa chốt tiền; khi thiếu quyền thì không thay đổi; khi địa chỉ có nhiều lựa chọn hợp lệ thì chuyển sang bước xác nhận phù hợp. Tiêu chí chỉ mô tả đường thuận lợi dễ bỏ qua nơi rủi ro thực sự xuất hiện.

Đừng bắt câu trả lời tự nhiên khớp từng chữ nếu ý nghĩa mới là điều quan trọng. Có thể cho phép diễn đạt khác nhưng giữ fact, hành động tiếp theo và giới hạn. Ngược lại, mã đơn, số tiền, quyền và trạng thái giao dịch cần kiểm chính xác.

## 7.3. Chốt phạm vi đe dọa

**Threat model**, mô hình mối đe dọa, là cách hỏi cái gì cần bảo vệ, có thể sai hoặc bị lạm dụng thế nào, và cơ chế nào ngăn hậu quả. Manager không cần liệt kê mọi kiểu tấn công. Trước hết hãy nhìn sai phiên bản dữ liệu, nhầm người, cấp quyền không thu hồi, tạo đơn trùng và lộ thông tin không cần thiết.

Một giả định như “chỉ dùng dữ liệu giả” cần có người xác nhận. Nếu giả định sai, rủi ro và tiêu chí phải đổi. Những nguy cơ ngoài phạm vi nên được ghi với lý do và điều kiện xem lại; không xóa khỏi trí nhớ và cũng không mặc định chặn mọi việc hiện tại.

## 7.4. Đóng băng tiêu chí để review công bằng

**Spec-first** nghĩa là thống nhất đặc tả trước khi xây. **Freeze** là giữ tiêu chí ổn định cho phiên nộp đang xét. Nó không cấm sửa sai nghiêm trọng. Nó yêu cầu khi thay đổi chuẩn, nhóm nói rõ điều gì mới, vì sao mới và ảnh hưởng ra sao.

Alpha3s cho phép thêm blocker khi bản sửa tạo lỗi mới, phạm vi thay đổi, bằng chứng bác bỏ giả định hoặc xuất hiện vấn đề an toàn nghiêm trọng. Những cải tiến tốt nhưng ngoài DoD được đưa vào việc cần làm trước bàn giao hoặc khuyến nghị. Cách này bảo vệ cả chất lượng lẫn khả năng kết thúc công việc. [S18]

Một reviewer có thể luôn tìm thêm điều cải thiện. Nếu mỗi cải thiện thành điều kiện chặn, dự án không có điểm hoàn thành. Manager cần phân biệt “chưa đáp ứng thỏa thuận” với “có thể tốt hơn”. Hai nhóm này cần cách xử lý khác nhau.

## 7.5. Ví dụ Gate B của M5

Directive 176 yêu cầu bộ tình huống có đầu vào giả, kết quả mong đợi và lý do. Các nhóm gồm địa chỉ hiện hành, tên cũ, dấu tiếng Việt, quan hệ địa giới, mốc hiệu lực, mơ hồ và biên điểm tin cậy. Không áp một số lượng test máy móc; phải bao phủ các nhóm cần thiết. [S20]

Yêu cầu “không có trường hợp tự xác minh sai trong bộ kiểm soát” là một DoD cụ thể. Nó không tuyên bố tỷ lệ sai ở thế giới thật bằng không. Manager cần giữ nguyên vế “trong bộ kiểm soát” khi báo cáo lên cấp trên. Phạm vi bằng chứng là một phần của tiêu chí.

## 7.6. Họp chốt yêu cầu trong 30 phút

Mười phút đầu xác nhận người dùng, kết quả và phần không làm. Mười phút tiếp theo đi qua ba tình huống thuận lợi, ba tình huống lỗi và cách trở về an toàn. Mười phút cuối chốt bằng chứng, người nhận và điều kiện thay đổi. Đây là nhịp làm việc gợi ý, không phải thủ tục bắt buộc.

Nếu chưa đồng ý, ghi bất đồng thành câu hỏi cụ thể. “Chưa rõ chất lượng” khó xử lý; “chưa thống nhất trường hợp một tên địa chỉ khớp hai địa điểm thì tự chọn hay chuyển người” có thể quyết được. Sau cuộc họp cần một bản ngắn có phiên bản, không cần biên bản dài thuật lại mọi phát biểu.

**Bài tập:** viết lại yêu cầu “bot tư vấn tốt và an toàn” thành năm tiêu chí có thể kiểm. Ít nhất hai tiêu chí phải là tình huống thất bại. Nhờ người khác thiết kế cách kiểm mà không hỏi thêm bạn. Những chỗ họ không kiểm được là chỗ yêu cầu còn mơ hồ.

**Câu mang vào cuộc họp:** “Chúng ta đã thống nhất bằng chứng nào đủ để đóng việc này chưa?”

[Nguồn và giới hạn diễn giải](../nguon/NGUON-VA-PHUONG-PHAP.md) · [Mục lục](../MUC-LUC.md)
