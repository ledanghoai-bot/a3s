# Chương 9. Khi AI đi từ lời nói sang hành động

**Năng lực sau chương:** xác định ranh giới tự động hóa cho đơn hàng, tồn kho, giá và các hành động có hậu quả.

## 9.1. Một câu sai và một giao dịch sai khác nhau

Một lời giải thích dài có thể làm khách khó chịu. Một đơn tạo hai lần hoặc thông báo sai tổng tiền có thể làm mất tiền và lòng tin. Khi AI có công cụ, manager phải đánh giá quyền hành động theo hậu quả, không chỉ độ tự nhiên của hội thoại.

Trong M1, Alpha3s sửa hai điểm có ý nghĩa quản lý rõ: khóa chống trùng phải ổn định khi cùng yêu cầu được thực hiện lại; thông tin đơn thành công phải lấy từ giao dịch đã ghi, không để mô hình tự dựng. Báo cáo review chấp nhận phần development nhưng giữ riêng quyền phát hành. [S06]

## 9.2. Gửi lại không được biến thành mua thêm

**Idempotency**, tính không lặp tác dụng, có thể hiểu là gửi lại cùng một yêu cầu không làm phát sinh tác động lần thứ hai. Mạng chậm, ứng dụng tự thử lại hoặc người dùng bấm lại đều có thể tạo yêu cầu trùng. Việc này không nhất thiết do AI, nhưng hệ thống AI làm nhiều bước nên càng cần kiểm soát.

Một khóa chống trùng phải phản ánh sự kiện nghiệp vụ ổn định. Nếu nó dựa vào mã mới sinh mỗi lần mô hình chạy, hệ thống có thể nghĩ hai lần thực hiện lại là hai yêu cầu khác nhau. Manager không cần thiết kế khóa; cần yêu cầu kiểm tra tình huống cùng tin đến lại, cùng giao dịch trả chậm và khách thực sự đặt thêm lần mới.

**Ví dụ giả định:** khách gửi “mua hai hũ”, đơn đã ghi nhưng tin xác nhận gửi lỗi. Hệ thống thử lại phải gửi lại xác nhận của đơn cũ. Nếu khách sau đó chủ động đặt thêm hai hũ, đó có thể là giao dịch mới. Chống trùng phải giữ được sự khác biệt này.

## 9.3. Xác nhận từ biên nhận đã ghi

**Committed receipt**, biên nhận của giao dịch đã ghi thành công, là căn cứ để nói đơn đã tồn tại. Nếu công cụ chưa xác nhận, bot cần nói chưa hoàn tất hoặc đang kiểm tra, tùy trạng thái thật. Không dùng câu “đặt hàng thành công” chỉ vì mô hình đã gọi công cụ.

Alpha3s thay phần lời tự do chứa thông tin đơn bằng phản hồi từ dữ liệu đã ghi. Bài học là những thông tin có giá trị cam kết nên được dựng bằng dữ liệu xác định. AI vẫn có thể giúp giải thích bước tiếp theo, nhưng mã đơn, số lượng và tiền phải theo hệ thống có thẩm quyền. [S06]

## 9.4. PO phải chốt trạng thái nghiệp vụ

**State**, trạng thái, cho biết một đối tượng đang ở bước nào. Đơn mới, xác nhận, xử lý, hoàn tất và hủy có quy tắc khác nhau. **State transition** là chuyển trạng thái có điều kiện. Việc hủy trước khi giao và trả sau khi giao không thể dùng cùng một thao tác cộng lại tồn.

Quyết định M2 phân biệt hết thời hạn giữ hàng, hủy thông thường, hủy ngoại lệ và yêu cầu trả hàng sau hoàn tất. Nó cũng yêu cầu xử lý lại cùng sự kiện không giải phóng tồn lần hai. Đây là chính sách do nghiệp vụ quyết định, rồi kỹ thuật hiện thực hóa. [S22]

Manager nên yêu cầu bảng: từ trạng thái nào, ai được yêu cầu, cần điều kiện gì, chuyển sang đâu, thông báo cho ai, và khi thất bại thì giữ gì. Một bảng chuyển trạng thái thường giúp phát hiện ngoại lệ tốt hơn mô tả vài đoạn “hệ thống hỗ trợ hủy đơn”.

## 9.5. Những điều phải luôn đúng

**Invariant**, điều kiện bất biến, là điều phải giữ trước và sau thao tác. Ví dụ: một yêu cầu không tạo hai đơn; không tự điều chỉnh tồn sau giao hàng; người không có quyền không đổi giá; lỗi ghi nhật ký bắt buộc không để giao dịch nhạy cảm hoàn tất âm thầm.

Closure M0 ghi việc sửa điểm đổi giá từ chỉ cần đăng nhập sang cần quyền quản lý giá, cùng kiểm tra người không đủ quyền bị từ chối và lỗi audit làm rollback thay đổi. Đăng nhập chứng minh có danh tính; phân quyền quyết định danh tính đó được làm gì. [S05]

**Audit trail**, dấu vết kiểm tra, giúp truy ai làm, làm gì, khi nào và kết quả ra sao. Nó không nên trở thành nơi chứa quá nhiều thông tin khách. Manager cần xác định câu hỏi điều tra cần trả lời rồi chọn dữ liệu tối thiểu để lưu.

## 9.6. Quyền dừng và cách bù hậu quả

**Rollback** là quay về trạng thái trước bằng cơ chế được thiết kế. **Compensation**, hành động bù, xử lý hậu quả đã ra ngoài hệ thống: thông báo sửa, hoàn tiền theo chính sách hoặc liên hệ khách. Tắt tính năng không tự thu hồi tin đã gửi hay hủy giao dịch tại bên thứ ba.

Vì vậy, kế hoạch cho hành động quan trọng cần cả đường dừng và đường xử lý phần đã xảy ra. Ai được tắt? Ai rà các giao dịch trong khoảng ảnh hưởng? Ai liên hệ khách? Ai duyệt bồi hoàn? Các câu này thuộc quản lý sản phẩm và vận hành, không thể để tới lúc sự cố mới phân công.

**Bài tập:** chọn một công cụ AI có quyền ghi. Viết ba điều không được sai và thiết kế một tình huống mất kết nối giữa chừng. Đội ngũ phải giải thích khách sẽ thấy gì, dữ liệu ở trạng thái nào và làm sao thử lại không tạo tác dụng thứ hai.

**Câu mang vào cuộc họp:** “Lời xác nhận này dựa vào trạng thái đã ghi hay chỉ dựa vào điều AI dự định làm?”

[Nguồn và giới hạn diễn giải](../nguon/NGUON-VA-PHUONG-PHAP.md) · [Mục lục](../MUC-LUC.md)
