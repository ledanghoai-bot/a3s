# Chương 17. Đưa AI vào công việc của con người

**Năng lực sau chương:** thiết kế sự tiếp nhận của nhân viên, chất lượng chuyển người và vòng phản hồi sau triển khai.

## 17.1. Có tính năng chưa có nghĩa được sử dụng

**Adoption**, mức tiếp nhận và sử dụng, phụ thuộc người dùng có hiểu, tin và thấy lợi ích không. Nhân viên có thể tránh dùng công cụ nếu sợ chịu trách nhiệm cho câu trả lời không kiểm được. Khách có thể rời đi nếu phải lặp lại thông tin sau khi chuyển từ bot sang người.

Foundation Alpha3s mô tả kết quả mong muốn: khách không cần lặp lại nhu cầu, hiểu sản phẩm và được chuyển người đúng lúc. Đây là mục tiêu trải nghiệm; hồ sơ không tự chứng minh mục tiêu đã đạt ở khách thật. Manager nên biến chúng thành quan sát và bài thử cụ thể. [S01]

## 17.2. Thiết kế handoff như một phần sản phẩm

**Human handoff** là chuyển việc cho người thật. Nó cần điều kiện chuyển, người nhận, thông tin bàn giao, thời gian phản hồi và cách xử lý khi chưa có ai. “AI sẽ chuyển người” chưa đủ nếu không có hàng đợi hoặc trách nhiệm tiếp nhận.

**Ví dụ giả định:** khách phản ánh nhận thiếu hàng. Bot ghi nhận vấn đề và chuyển nhân viên, kèm mã đơn đã kiểm quyền, nội dung cần giải quyết và việc đã hỏi. Nhân viên không nhận một tập log dài không tóm tắt. Khách được biết đang chờ ai và cần làm gì, nhưng không được hứa một thời gian đội ngũ chưa đủ khả năng đáp ứng.

Handoff tốt có thể làm tỷ lệ tự động giảm nhưng chất lượng tăng. Manager nên đo tỷ lệ chuyển đúng, ca bị bỏ quên, số lần hỏi lại và kết quả cuối. Nếu chỉ giao chỉ tiêu “giảm số ca chuyển”, nhân viên và hệ thống có thể bị khuyến khích giữ lại ca vượt khả năng.

## 17.3. Huấn luyện cách tin đúng mức

**Automation bias** là xu hướng tin đề xuất tự động quá mức. Đối cực là không tin gì và làm lại mọi bước, khiến AI không tạo lợi ích. Người dùng cần biết phần nào có nguồn kiểm chứng, phần nào là gợi ý và phần nào phải xác nhận.

Một buổi đào tạo nên có câu trả lời đúng, câu sai có vẻ hợp lý, lỗi công cụ và trường hợp chuyển người. Nhân viên thực hành nhận ra giới hạn, sửa thông tin và báo lỗi. Đừng chỉ trình diễn đường hoàn hảo; người nhận việc cần biết cách thoát khỏi tình huống xấu.

Với manager, kỹ năng quan trọng là đọc trạng thái và hỏi nguồn, không phải học mọi thuật ngữ AI. Một nhãn “đã ghi đơn” phải có nghĩa rõ khác “đề xuất tạo đơn”. Một nhãn “đang kiểm tra” không nên bị hiểu thành cam kết giao hàng.

## 17.4. Giao diện và hướng dẫn bằng tiếng phổ thông

Tài liệu kỹ thuật có thể dùng identifier để chính xác, nhưng giao diện quản lý cần giải thích tác dụng. Thay “revoke capability” bằng “thu hồi quyền thực hiện” và cho biết điều đó dừng được việc gì. Có thể đặt thuật ngữ gốc trong chú thích để người đọc tra cứu.

Quá trình sửa signing guide Alpha3s là ví dụ về việc giữ nội dung chuyên môn nhưng diễn đạt cho người thao tác. Thay đổi văn bản có thể tác động đáng kể tới mức hiểu, dù không đổi logic phần mềm. Cần kiểm với người dùng mục tiêu thay vì chỉ nhờ người đã biết hệ thống đọc lại. [S23]

## 17.5. Thu phản hồi đủ để hành động

Một phản hồi tốt gồm tình huống, kỳ vọng, điều xảy ra, mức ảnh hưởng và khả năng tái hiện. “Bot dở” khó chuyển thành việc; “khách đổi số lượng ở lượt thứ ba nhưng xác nhận vẫn dùng số cũ” có thể tạo test.

EV-005 phân loại lỗi thành thiếu/sai tri thức, tìm không ra, chọn sai đường, lắp ngữ cảnh sai, sinh sai, công cụ lỗi và trải nghiệm khó hiểu. Manager có thể dùng cách phân loại đó để giao owner thay vì đẩy mọi lỗi cho người viết prompt. [S12]

Đừng thu phản hồi theo cách khiến nhân viên sợ bị đánh giá. Nếu báo lỗi làm họ bị coi là dùng sai công cụ, tổ chức sẽ mất nguồn học. Nên thưởng cho phát hiện sớm và theo dõi xem lỗi được sửa có quay lại không.

## 17.6. Nhịp cải tiến nhỏ và đều

Trong giai đoạn đầu, một buổi ngắn xem các ca thất bại quan trọng có thể hữu ích hơn dashboard rất lớn. Chọn vài ca, tìm nguyên nhân, tạo test trước, giao thay đổi nhỏ và đo lại. Khi lượng dùng tăng, bổ sung lấy mẫu và theo dõi có hệ thống.

Không để AI tự biến mọi hội thoại thành tri thức đang dùng. Người sở hữu nghiệp vụ vẫn cần xác nhận sự thật và kỳ vọng. Sự học của tổ chức là một quy trình có người chịu trách nhiệm, dù AI hỗ trợ tìm mẫu và viết nháp.

**Bài tập:** thiết kế buổi đào tạo 45 phút cho nhân viên nhận ca từ bot. Có ba tình huống thường gặp, một lỗi tự tin nhưng sai, một ca không ai nhận và một cách báo lỗi. Kết thúc bằng việc người học tự xử lý, không chỉ trả lời đã hiểu.

**Câu mang vào cuộc họp:** “Khi AI không làm được, người tiếp nhận có đủ thông tin và quyền để giải quyết không?”

[Nguồn và giới hạn diễn giải](../nguon/NGUON-VA-PHUONG-PHAP.md) · [Mục lục](../MUC-LUC.md)
