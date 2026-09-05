# Chương 6. Quản lý tri thức như một tài sản sản phẩm

**Năng lực sau chương:** tổ chức nguồn đúng, người sở hữu và vòng đời nội dung để AI không lặp lại thông tin sai.

## 6.1. Sai trong dữ liệu có thể trông rất đúng trong câu trả lời

Kế hoạch M0 của Alpha3s ghi việc sửa mô tả sản phẩm cũ và giá trị khẩu phần chưa có nguồn chuẩn hỗ trợ. Giá trị khẩu phần có thể khiến công cụ suy ra số ly trên một hũ, tạo một Product Fact chưa được duyệt. Sửa lời nhắc mô hình thôi chưa giải quyết nguồn dữ liệu này. [S04]

**Product Fact** là sự thật về sản phẩm: thành phần, quy cách, cách dùng, đơn vị hay giới hạn đã được xác nhận. Manager cần phân biệt fact với nhận xét và gợi ý. “Hũ nặng bao nhiêu” là fact; “phù hợp mang đi làm” có thể là khuyến nghị theo bối cảnh. Khuyến nghị không được lén trở thành lời cam kết tuyệt đối.

Nếu chưa có nguồn, trạng thái “chưa biết” thường tốt hơn một số có vẻ hợp lý. Dữ liệu trống được kiểm soát cho phép hệ thống hỏi hoặc chuyển người. Dữ liệu sai có cấu trúc khiến hệ thống tự tin tính tiếp và lan sai sang nhiều kênh.

## 6.2. Một nguồn có thẩm quyền cho từng loại thông tin

**Single source of truth** nghĩa là mỗi sự thật quan trọng có một nguồn được công nhận làm căn cứ. Nó không bắt buộc mọi dữ liệu nằm trong một tệp. Giá có thể thuộc hệ thống bán hàng, thông tin thương hiệu thuộc bộ nội dung đã duyệt, tồn kho thuộc sổ kho.

Khi có xung đột, nguồn nào thắng phải rõ trước. Một bài quảng cáo cũ không được thay giá hiện hành. Một hội thoại khách kể lại không tự trở thành chính sách hoàn tiền. Một ví dụ trong tài liệu đào tạo không được đưa vào kho fact như dữ liệu thật.

| Loại nội dung | Chủ sở hữu phù hợp | Dấu hiệu cần cập nhật |
|---|---|---|
| Thành phần, quy cách | Owner sản phẩm | Thay nhà cung cấp, đổi bao bì |
| Giá, khuyến mãi | Owner thương mại | Đổi bảng giá hoặc kỳ hiệu lực |
| Tồn và trạng thái đơn | Owner vận hành | Phát sinh giao dịch |
| Cách nói với khách | CSKH/brand owner | Phản hồi khó hiểu, sai giọng |
| Quy tắc chuyển người | PO và CSKH | Ca mới hoặc năng lực hỗ trợ đổi |

## 6.3. Vòng đời nội dung đơn giản

Một nội dung nên đi qua nháp, được duyệt, đang dùng, bị thay thế hoặc thu hồi. **Versioning**, hay quản lý phiên bản, giúp biết câu trả lời dựa trên nội dung nào. **Provenance**, hay nguồn gốc có thể truy lại, giúp biết ai cung cấp và vì sao nội dung được tin.

Đối với đội nhỏ, một bảng có mã nội dung, owner, nguồn, ngày hiệu lực, phiên bản và tình trạng là điểm bắt đầu tốt. Không cần xây ngay hệ thống xuất bản phức tạp. Nhưng phải có cách ngăn nội dung nháp và bị thay thế lọt vào phần AI đang dùng.

Mỗi lần sửa fact, hãy hỏi phạm vi ảnh hưởng: FAQ nào trích nó, công cụ nào dùng nó, ví dụ nào lặp lại nó, bộ test nào còn mong câu trả lời cũ. Đó là **impact analysis**, tức phân tích tác động thay đổi. Chỉ sửa một tệp trong khi dữ liệu đã được nhập sang nơi khác có thể không thay đổi hành vi của bot.

## 6.4. Tách dữ liệu tĩnh và dữ liệu động

Thông tin ổn định có thể được đưa vào kho tri thức. Giá và tồn thay đổi nên đi qua công cụ ở thời điểm cần. “Động” không chỉ có nghĩa thay mỗi giây; chính sách có ngày hết hạn cũng cần cơ chế hiệu lực. Foundation Alpha3s nêu rõ ranh giới này để tránh bot trả giá hoặc tồn từ nội dung tĩnh. [S01]

**Ví dụ giả định:** FAQ có câu “hôm nay còn hàng”. Dù câu đúng lúc viết, một tuần sau nó không còn là tri thức an toàn. Cách viết tốt hơn là giải thích cách kiểm tra tồn, còn số tồn được lấy từ nguồn hiện hành. Manager cần duyệt cả nội dung lẫn cách nội dung được sử dụng.

## 6.5. Làm nội dung để con người cũng đọc được

Kho tri thức hữu ích không phải tập văn bản thật dài để “AI tự hiểu”. Mỗi mục nên có một chủ đề, ranh giới áp dụng, ví dụ và điểm chuyển người. Ngôn ngữ rõ giúp cả reviewer nghiệp vụ và AI dùng nhất quán.

Một chủ sở hữu không kỹ thuật có thể kiểm nội dung qua ba câu: thông tin đúng chưa, có đủ điều kiện đi kèm chưa, có điều gì dễ bị hiểu thành lời hứa quá mức không. Đội kỹ thuật chịu trách nhiệm cách đưa nội dung vào hệ thống, nhưng không nên tự duyệt sự thật thương mại.

## 6.6. Biến lỗi thành tri thức có kiểm soát

EV-005 của Alpha3s mô tả vòng phản hồi: nhận lỗi, làm sạch thông tin cá nhân, phân loại nguyên nhân, tạo test rồi đề xuất thay đổi. AI có thể gợi ý FAQ và nguyên nhân nhưng không tự duyệt fact hay tự hạ mức lỗi để bản phát hành đạt. [S12]

Đây là **continuous improvement**, cải tiến liên tục có kiểm soát. Nó khác với cho bot tự học mọi điều khách nói. Khách có thể nói nhầm, đùa hoặc cố dẫn hệ thống đi sai. Nội dung mới phải qua xác minh trước khi trở thành nguồn trả lời chính thức.

**Bài tập:** lấy năm câu AI thường trả lời. Với mỗi câu, đánh dấu từng phát biểu là fact, nhận xét hay gợi ý. Điền nguồn và owner cho mỗi fact. Nếu không tìm thấy, chọn thu hồi, sửa cách diễn đạt hoặc bổ sung nguồn; không mặc định giữ vì câu đã dùng lâu.

**Câu mang vào cuộc họp:** “Nếu thông tin này đổi ngày mai, ai biết, ai sửa và làm sao chắc bot đã dùng bản mới?”

[Nguồn và giới hạn diễn giải](../nguon/NGUON-VA-PHUONG-PHAP.md) · [Mục lục](../MUC-LUC.md)
