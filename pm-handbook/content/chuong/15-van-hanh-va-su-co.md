# Chương 15. Vận hành khi người viết hệ thống không ở đó

**Năng lực sau chương:** chuẩn bị bàn giao, diễn tập và xử lý sự cố bằng trách nhiệm rõ ràng.

## 15.1. Vận hành là một phần của sản phẩm

Người dùng không phân biệt bot trả lời chậm vì mô hình, hàng đợi hay tài khoản kênh. Họ chỉ thấy việc chưa xong. Vì vậy owner sản phẩm cần biết ai theo dõi, ai tiếp nhận ngoại lệ và ai được phép dừng.

Trong Alpha3s, lỗi Telegram có hai tiến trình cùng poll từng được ghi nhận và xử lý. Đây là vấn đề cấu hình vận hành: cùng một bot có hai nơi nhận việc, không thể kết luận ngay là lỗi mã mới. Bài học là lập bản đồ thành phần đang chạy thực tế, gồm cả môi trường local có thể còn dùng quyền thật. [S05, S07]

## 15.2. Runbook để người nhận tự dùng

**Runbook** là hướng dẫn thao tác một công việc thường gặp hoặc xử lý tình huống. Người viết nên bắt đầu từ người đọc: họ đang thấy gì, cần kiểm gì, được làm gì và khi nào phải dừng. Những bước yêu cầu quyền hoặc dữ liệu đặc biệt phải được nhận diện trước.

Một runbook tốt có điều kiện bắt đầu, đầu vào, thao tác, kết quả mong đợi, cách nhận biết sai và đường chuyển cấp. Nó cần phù hợp phiên bản đang chạy. Hướng dẫn đúng cho phiên bản cũ có thể nguy hiểm nếu giao diện hay quyền đã đổi.

Việc sửa trang signing guide của Alpha3s sang ngôn ngữ phổ thông nhắc một điều quan trọng: tài liệu vận hành cũng là trải nghiệm người dùng. Dù thuật ngữ chính xác, người nhận vẫn cần hiểu bước đó phục vụ mục đích nào và kết quả trông ra sao. [S23]

## 15.3. Diễn tập bằng người sẽ nhận việc

Để kiểm bàn giao, nhờ người nhận thực hiện một tác vụ bằng tài liệu, người viết chỉ quan sát. Ghi chỗ họ dừng, câu hỏi họ phải hỏi và nhãn họ hiểu sai. Nếu người viết liên tục giải thích ngoài tài liệu, runbook chưa đủ để bàn giao.

Diễn tập nên có cả đường lỗi: mất quyền, dữ liệu không khớp, kết quả không như mong đợi, hoặc cần dừng giữa chừng. Mục tiêu là người nhận biết dừng đúng và giữ thông tin cần điều tra, không phải thuộc lệnh.

Với đội nhỏ, có thể chưa có người vận hành độc lập. Ghi đây là giới hạn của giai đoạn và chuẩn bị tài liệu để giảm lệ thuộc, thay vì giả định đã có đội trực hoàn chỉnh.

## 15.4. Khi sự cố xảy ra

**Incident** là sự cố ảnh hưởng hoặc có nguy cơ ảnh hưởng dịch vụ, dữ liệu hay người dùng theo mức tổ chức xác định. **Containment** là khoanh vùng để hạn chế hậu quả trước khi sửa tận gốc. Dừng tính năng, khóa đường gửi hoặc chuyển sang người thật có thể là hành động khoanh vùng.

Manager cần bốn dòng thông tin: điều gì quan sát được, phạm vi ảnh hưởng đã biết, hành động giảm hậu quả và thời điểm cập nhật tiếp theo. Đừng ép đội ngũ đưa nguyên nhân chắc chắn khi mới chỉ có dấu hiệu. Phân biệt “đã xác nhận” và “đang kiểm tra” giữ giao tiếp đáng tin.

Một lần preflight dừng vì thiếu điều kiện không nhất thiết là sự cố dịch vụ. Báo cáo Gate A dừng trước ghi là ví dụ kiểm soát phát hiện sai khác sớm. Cần sửa kế hoạch và điều kiện thực tế, không phạt hành vi dừng đúng chỉ vì chưa đạt lịch. [S15]

## 15.5. Sao lưu phải đi cùng khôi phục

**Backup** là bản sao lưu; **restore** là đưa dữ liệu trở lại để dùng. Một lịch backup thành công không đủ nếu không có khóa giải mã, không biết bản nào dùng được hoặc chưa thử phục hồi.

**RPO** là mức mất dữ liệu theo thời gian có thể chấp nhận; **RTO** là mục tiêu thời gian khôi phục. Manager nên diễn đạt bằng tác động: có thể mất tối đa bao nhiêu giờ dữ liệu; hoạt động có thể dừng bao lâu. Đây là mục tiêu cần đo và thương lượng với nguồn lực, không phải con số trang trí trong tài liệu.

Roadmap Alpha3s nêu diễn tập giả định mất máy chủ và khả năng lấy khóa ở ngoài máy bị mất. Bài học là kiểm toàn bộ khả năng hồi phục, gồm dữ liệu, quyền, khóa và người thực hiện. [S02]

## 15.6. Nhìn lại mà không tìm người để đổ lỗi

**Postmortem** hoặc **incident review** là nhìn lại sau sự cố để cải tiến. Một bản tốt có trình tự sự kiện, tác động, yếu tố góp phần, điều giúp phát hiện, điều làm chậm và hành động cụ thể. Tránh giải thích bằng “nhân viên bất cẩn” nếu hệ thống và hướng dẫn cho phép nhầm dễ dàng.

Không phải hành động nào cũng cần thêm một gate. Có thể sửa nhãn, kiểm quyền sớm, thêm test, xóa bước thừa hoặc làm rõ owner. Chọn vài việc có khả năng ngăn tái diễn cao, giao owner và ngày kiểm hiệu quả.

**Bài tập:** giả định người xây bot nghỉ một tuần, mô hình trả lỗi và nhân viên đang nhận khiếu nại. Viết ai phát hiện, ai tắt, thông báo khách thế nào, dữ liệu nào giữ để điều tra và làm sao khôi phục. Nếu mọi mũi tên quay về một người vắng mặt, kế hoạch chưa sẵn sàng.

**Câu mang vào cuộc họp:** “Một người không tham gia xây dựng có thể xử lý tình huống này bằng hướng dẫn hiện có không?”

[Nguồn và giới hạn diễn giải](../nguon/NGUON-VA-PHUONG-PHAP.md) · [Mục lục](../MUC-LUC.md)
