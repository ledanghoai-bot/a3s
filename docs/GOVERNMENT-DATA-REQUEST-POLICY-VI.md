# Quy trình xử lý yêu cầu cung cấp dữ liệu từ cơ quan công quyền

**Đơn vị:** Robanme Coffee (thương hiệu 3S Coffee)
**Phạm vi:** Toàn bộ dữ liệu cá nhân của khách hàng mà hệ thống Alpha3S thu thập/xử lý, bao gồm
Dữ liệu nền tảng nhận từ Meta (PSID, tên hiển thị, nội dung tin nhắn Messenger) và dữ liệu do
khách tự cung cấp (SĐT, địa chỉ giao hàng, lịch sử đơn hàng).
**Hiệu lực:** từ ngày 03/09/2026.
**Người phê duyệt & chịu trách nhiệm thi hành:** Lê Đăng Hoài (Chủ đơn vị — Product Owner,
kiêm mọi vai vận hành trong giai đoạn xây dựng; xem quy ước phân vai nội bộ).

## 1. Nguyên tắc chung

Mọi yêu cầu từ cơ quan công quyền (cơ quan nhà nước, cơ quan điều tra, tòa án…) đòi cung cấp
dữ liệu cá nhân hoặc thông tin cá nhân của người dùng đều phải xử lý theo quy trình này.
Không cá nhân nào được tự ý cung cấp dữ liệu ngoài quy trình.

## 2. Quy trình bắt buộc (3 bước)

### Bước 1 — Xem xét tính hợp pháp
- Kiểm tra yêu cầu có bằng văn bản chính thức không (công văn, quyết định, lệnh của cơ quan
  có thẩm quyền theo pháp luật Việt Nam).
- Kiểm tra thẩm quyền của cơ quan/người ký và căn cứ pháp lý được viện dẫn.
- Yêu cầu miệng, qua điện thoại, hoặc không nêu căn cứ pháp lý → từ chối và đề nghị gửi
  văn bản chính thức.
- Khi có nghi ngờ về tính hợp pháp, tham vấn tư vấn pháp lý trước khi phản hồi.

### Bước 2 — Giảm thiểu dữ liệu (data minimization)
- Chỉ cung cấp đúng phạm vi dữ liệu tối thiểu mà văn bản yêu cầu nêu rõ; không cung cấp
  thừa (không xuất cả bảng/cả hội thoại khi chỉ bị yêu cầu một trường/một giao dịch).
- Dữ liệu của người dùng khác không thuộc phạm vi yêu cầu phải được loại bỏ/che trước khi
  bàn giao.

### Bước 3 — Ghi chép (documentation)
Mỗi yêu cầu phải được ghi vào sổ theo dõi nội bộ (file riêng, ngoài repo mã nguồn), tối thiểu gồm:
- Ngày nhận, cơ quan yêu cầu, người ký, căn cứ pháp lý viện dẫn;
- Phạm vi dữ liệu bị yêu cầu và phạm vi dữ liệu thực tế đã cung cấp (hoặc lý do từ chối);
- Lập luận pháp lý/đánh giá ở Bước 1, các bên đã tham vấn;
- Ngày phản hồi và người thực hiện.

## 3. Lưu ý riêng cho Dữ liệu nền tảng của Meta

Dữ liệu nhận từ Meta (PSID, nội dung tin nhắn…) còn chịu thêm Điều khoản nền tảng của Meta.
Khi yêu cầu đụng tới loại dữ liệu này, ngoài quy trình trên cần đối chiếu nghĩa vụ với Meta
(Platform Terms) trước khi cung cấp.

## 4. Rà soát

Quy trình này được rà soát lại khi: (a) có nhân sự vận hành mới (Staff N theo mô hình phân
vai), (b) có yêu cầu thực tế đầu tiên, hoặc (c) tối thiểu mỗi 12 tháng — tùy điều kiện nào
đến trước.

---
*Văn bản này được lập để trả lời trung thực mục "Data handling — requests from public
authorities" trong Data Access Renewal của Meta (app 541838039979536), phản ánh đúng quy
trình đơn vị cam kết áp dụng kể từ ngày hiệu lực.*
