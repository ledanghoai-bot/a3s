# Chương 13. Đọc bằng chứng và tổ chức review hiệu quả

**Năng lực sau chương:** nhận một gói bàn giao, đánh giá kết luận có đủ căn cứ và đóng vòng sửa mà không nâng chuẩn vô hạn.

## 13.1. Bằng chứng phải trả lời một câu hỏi

Một thư mục hàng trăm ảnh chụp chưa chắc giúp manager biết việc đã hoàn thành. Bằng chứng hữu ích gắn với một tiêu chí: phiên bản nào được thử, kết quả nào mong đợi, kết quả thật là gì và điều gì còn giới hạn. **Evidence package**, gói bằng chứng, nên có bản tóm tắt dẫn tới chi tiết đúng chỗ.

Ví dụ giả định: tiêu chí là gửi lại không tạo đơn trùng. Bằng chứng cần thể hiện cùng yêu cầu được gửi lại, số đơn thực tế và phản hồi nhận được. Một ảnh “test suite passed” không tự chứng minh ca đó tồn tại hoặc kiểm đúng điều cần.

## 13.2. Phân biệt báo cáo, chứng thực và kiểm tra độc lập

**Reported result** là kết quả người thực hiện báo. **Attestation** là xác nhận của người có trách nhiệm về điều họ quan sát hoặc thực hiện. **Independent verification** là kiểm tra độc lập theo một phương pháp cụ thể. Ba loại có giá trị khác nhau và có thể cùng xuất hiện trong một gói.

Review 168 nói rõ một số test là evidence nộp lên, reviewer không tự chạy suite hay kiểm live. Closure 175 ghi việc kiểm lại hash và manifest. Cẩm nang dẫn những phát biểu này đúng phạm vi; bản thân cẩm nang không lặp lại vận hành hay xác minh máy chủ. [S16, S19]

Manager không cần loại bỏ attestation. Trong thử nghiệm nội bộ ít rủi ro, xác nhận có trách nhiệm kết hợp log thông thường có thể đủ. Nhưng cần ghi rõ đó là xác nhận của ai, về sự kiện gì, và có mâu thuẫn với bằng chứng khác không.

## 13.3. Phiên bản và dấu vân tay nội dung

**Commit** là một mốc thay đổi trong Git. **Hash** là giá trị tính từ nội dung, có thể dùng như dấu vân tay để phát hiện nội dung khác. Hash khớp cho biết tệp khớp giá trị tham chiếu; nó không tự chứng minh tệp đúng, an toàn, tác giả là ai hoặc giá trị tham chiếu đáng tin.

**Manifest** là danh sách các thành phần trong gói. Khi có nhiều tệp quan trọng, manifest giúp kiểm gói đủ và không đổi sau khi nộp. Với tài liệu nhỏ, một phiên bản rõ và lịch sử Git có thể đủ; không cần dùng cơ chế mật mã phức tạp nếu nó không giảm rủi ro hiện tại.

Addendum 171 yêu cầu giữ các phiên nộp và snapshot đã dẫn, tránh ghi đè làm mất lịch sử. Đây là phản hồi trực tiếp với khó khăn phân biệt các lần correction. Bài học rộng là bản đã được xét cần còn truy lại được, còn bản sửa phải nói rõ thay điều gì. [S18]

## 13.4. Review theo tiêu chí đã chốt

Một review tốt bắt đầu bằng quyết định: chấp nhận, chấp nhận có giới hạn, cần sửa hoặc dừng. Tiếp theo là các phát hiện gắn với tiêu chí, mức rủi ro và cách chứng minh đã sửa. Những lời khuyên không chặn cần tách rõ để đội ngũ không nhầm ưu tiên.

**Consolidated review**, review tổng hợp, gom các vấn đề có thể nhận ra trong một lượt. Nó giảm tình trạng sửa xong một điểm rồi mới biết thêm điểm khác đã có thể thấy từ đầu. Không ai bảo đảm phát hiện mọi lỗi, nhưng reviewer nên chịu trách nhiệm về độ đầy đủ hợp lý của lượt đọc.

Khi correction nộp lại, xem phần thay đổi và hồi quy liên quan. Nếu chỉ thay mô tả, không mặc định yêu cầu kiểm thử lại toàn hệ thống. Nếu thay hành vi nghiệp vụ, cần bằng chứng mới cho hành vi bị ảnh hưởng. Mức kiểm phải dựa trên delta, tức phần thay đổi thực tế.

## 13.5. Chấp nhận có giới hạn là một quyết định hữu ích

**Qualified acceptance** nghĩa là chấp nhận trong phạm vi nêu rõ, có giới hạn còn lại. Ví dụ: bộ dữ liệu đủ để chạy thử nội bộ, chưa đủ để bật chức năng cho khách. Nó giúp đội ngũ tiến bước mà không tuyên bố quá mức.

Giới hạn phải đi với owner và bước tiếp theo. Nếu ghi “còn một số hạn chế” mà không chỉ ra gì, người nhận sau có thể hiểu như đã xong toàn bộ. Một báo cáo tốt nên có mục “đã được chứng minh” và “chưa được chứng minh”, viết bằng ngôn ngữ người quản lý hiểu.

## 13.6. Cách đóng việc

**Closure**, đóng việc, xác nhận tiêu chí đã đạt, trạng thái cuối và phần chuyển tiếp. Nó giúp nhóm dừng lặp lại kiểm tra cũ trừ khi có thay đổi hoặc bằng chứng mới. Closure 175 nói rõ không cần thêm vòng correction cho Gate A development và giữ các phần khác ngoài phạm vi. [S19]

Manager nên kiểm ba câu trước khi đóng: điều kiện hoàn thành đã đạt chưa; trạng thái cuối có đúng mong muốn không; việc còn lại đã có nơi quản lý chưa. Đừng để chữ “closed” làm biến mất backlog bàn giao, cũng đừng giữ mốc mãi mở chỉ vì còn ý tưởng cải tiến.

**Bài tập:** lấy một gói bàn giao và tạo bảng một hàng cho mỗi tiêu chí: dẫn chứng, kết quả, giới hạn, quyết định. Hàng thiếu dẫn chứng là yêu cầu bổ sung cụ thể. Hàng đủ dẫn chứng không cần hỏi lại theo cảm giác.

**Câu mang vào cuộc họp:** “Bằng chứng này hỗ trợ đúng kết luận nào, và có điều gì nó chưa thể chứng minh?”

[Nguồn và giới hạn diễn giải](../nguon/NGUON-VA-PHUONG-PHAP.md) · [Mục lục](../MUC-LUC.md)
