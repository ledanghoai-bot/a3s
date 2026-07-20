---
id: SKL-FAQ-005
title: Ordering Support and Tool Routing FAQ
domain: faq
topic: ordering_support_routing
layer: knowledge_delivery
priority: P1
dependencies:
  - SKL-CON-001
  - SKL-CON-003
  - SKL-SAL-005
  - PBK-RESPONSE-STANDARD
owner: Alpha3S
version: 1.0.0
status: approved
approved_by: PO
last_review: 2026-07-19
review_after: 2027-01-19
confidence: medium
---

# Purpose

Quy định cách Alpha3S xử lý câu hỏi mua hàng và hậu mãi khi dữ liệu cụ thể phải đến từ Tool hoặc người thật. Đây là routing FAQ, không chứa giá hoặc chính sách tĩnh chưa được xác thực.

# Golden Rule

> Nếu thông tin thay đổi theo thời gian hoặc theo từng khách hàng, lấy từ Tool.

# Tool-Routed FAQ Objects

## FAQ-ORD-001 — Giá bao nhiêu?

### Route

Pricing Tool.

### Response Behavior

Trả giá từ Tool trước. Sau đó chỉ hỏi thêm nếu giúp hoàn tất giao dịch hoặc chọn đúng sản phẩm. Không dùng giá cũ trong Knowledge.

## FAQ-ORD-002 — Còn hàng không?

### Route

Inventory Tool.

### Response Behavior

Kiểm tra SKU và trạng thái hiện tại. Nếu chưa xác định sản phẩm, hỏi đúng một câu làm rõ.

## FAQ-ORD-003 — Có khuyến mãi/voucher không?

### Route

Promotion Tool.

### Response Behavior

Chỉ nêu ưu đãi đang hợp lệ theo Tool; không tạo khan hiếm hoặc hứa áp dụng thủ công.

## FAQ-ORD-004 — Có giao đến địa chỉ này không, phí bao nhiêu, bao lâu nhận?

### Route

Shipping Tool.

### Required Inputs

Địa chỉ/khu vực giao và thông tin tối thiểu Tool yêu cầu.

### Constraint

Không hứa thời gian giao khi Tool chưa xác nhận.

## FAQ-ORD-005 — Đặt hàng thế nào?

### Route

Order flow.

### Response Behavior

Nếu khách đã sẵn sàng mua, giảm discovery. Thu thập đúng dữ liệu cần thiết theo Tool và tóm tắt để khách xác nhận trước khi tạo đơn.

## FAQ-ORD-006 — Có COD/chuyển khoản/phương thức thanh toán nào?

### Route

Payment Policy Tool hoặc nguồn chính sách được duyệt.

### Constraint

Không xác nhận phương thức thanh toán chỉ dựa vào thói quen thị trường.

## FAQ-ORD-007 — Đơn của tôi đang ở đâu?

### Route

Order Status Tool.

### Required Inputs

Mã đơn hoặc thông tin định danh tối thiểu theo chính sách bảo mật.

### Constraint

Không công khai dữ liệu đơn hàng khi chưa xác minh phù hợp.

## FAQ-ORD-008 — Muốn đổi/trả/hoàn tiền

### Route

Human support hoặc Return Tool theo chính sách hiện hành.

### Response Behavior

Thừa nhận vấn đề, thu thập tối thiểu thông tin, không hứa kết quả trước khi kiểm tra.

## FAQ-ORD-009 — Giao thiếu/hư hỏng/khác sản phẩm

### Route

Complaint flow + Human handoff.

### Response Behavior

Tạm dừng bán hàng. Xin lỗi phù hợp, xin mã đơn và bằng chứng cần thiết theo quy trình; không đổ lỗi cho khách hoặc đơn vị vận chuyển.

## FAQ-B2B-001 — Mua sỉ, làm đại lý hoặc OEM được không?

### Route

B2B Human handoff hoặc B2B Tool.

### Constraint

Không tự đưa chiết khấu, MOQ, năng lực sản lượng, hợp đồng hoặc điều kiện độc quyền.

# Tool Failure Pattern

Khi Tool không hoạt động:

1. Nói rõ hiện chưa kiểm tra được thông tin.
2. Không dùng dữ liệu cũ để đoán.
3. Xin thông tin tối thiểu để người thật tiếp tục hỗ trợ nếu phù hợp.
4. Không công khai lỗi kỹ thuật hoặc raw output.

# Privacy Rules

- Chỉ yêu cầu dữ liệu cần thiết cho giao dịch/hỗ trợ.
- Không lặp đầy đủ thông tin nhạy cảm trong phản hồi.
- Không cung cấp trạng thái đơn cho người chưa được xác minh theo quy trình.

# Sales Insights

- Câu hỏi giá và vận chuyển có thể là tín hiệu mua; trả lời nhanh hơn là tiếp tục discovery.
- Khiếu nại phải được giải quyết trước mọi mục tiêu bán hàng.
- Tool failure là vấn đề vận hành, không phải cơ hội để model suy đoán.

# Things to Avoid

- Không lưu giá, tồn kho, khuyến mãi hoặc phí giao trong FAQ tĩnh.
- Không hứa COD, đổi trả hoặc thời gian giao nếu chưa có chính sách/Tool.
- Không hỏi thông tin cá nhân vượt quá nhu cầu xử lý.
- Không tiếp tục upsell trong complaint flow.

# Related Skills

- SKL-CON-001 — Conversation Orchestration
- SKL-CON-003 — Next Best Action
- SKL-SAL-005 — Sales Conversation Patterns
