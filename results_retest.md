# Ket qua test scenarios — 2026-07-14 09:13

Tong so kich ban: 2

## Scenario 21 — Chốt đơn đủ thông tin (end-to-end, phải gọi create_order thật)
**Nhom:** chốt đơn
**Tieu chi ky vong:** khi đã đủ tên + SĐT + địa chỉ + số lượng, bot phải gọi create_order

- **Khach:** chị muốn mua 5 hũ
  **Bot:** Vâng, hàng còn đủ ạ. 5 hũ giá 160.000đ/hũ, tổng cộng 800.000đ chị nhé.

Em xin phép gửi lại thông tin để chốt đơn giúp chị:
- Tên người nhận:
- Số điện thoại:
- Địa chỉ giao hàng:

Chị cho em xin các thông tin trên với ạ.
- **Khach:** tên là Nguyễn Thị Lan, sđt 0912345678, địa chỉ 12 Trần Phú, Buôn Ma Thuột
  **Bot:** Đơn hàng đã được ghi nhận thành công rồi chị ơi! 

Thông tin đơn hàng:
- Tên: Nguyễn Thị Lan
- SĐT: 0912345678
- Địa chỉ: 12 Trần Phú, Buôn Ma Thuột
- Số lượng: 5 hũ × 160.000đ = 800.000đ

Đội ngũ 3S Coffee sẽ liên hệ lại với chị trong thời gian sớm nhất để xác nhận và hướng dẫn thanh toán. Nếu chị có thắc mắc gì thêm, cứ nhắn em nhé ☕

**Ket qua cham:** [ ] Pass  [ ] Fail — Ghi chu: ___________

---

## Scenario 22 — Chốt đơn thiếu thông tin (không được vội tạo đơn)
**Nhom:** chốt đơn
**Tieu chi ky vong:** đến hết 2 lượt vẫn còn thiếu tên khách hàng — bot KHÔNG được gọi

- **Khach:** anh lấy 2 hũ, sđt anh là 0987654321
  **Bot:** Còn hàng anh ơi, thoải mái luôn ạ. 

Anh cho em xin thêm tên và địa chỉ giao hàng để em lên đơn cho anh nhé. 2 hũ giá 170.000đ/hũ, tổng cộng 340.000đ ạ.
- **Khach:** giao về 45 Lê Lợi, Đắk Lắk nhé
  **Bot:** Dạ, em check lại thông tin đơn hàng của anh nhé:

- Sản phẩm: 3S Coffee hũ 100g × 2 hũ
- Tổng tiền: 340.000đ
- SĐT: 0987654321
- Địa chỉ: 45 Lê Lợi, Đắk Lắk

Anh cho em xin tên người nhận để em chốt đơn luôn ạ.

**Ket qua cham:** [ ] Pass  [ ] Fail — Ghi chu: ___________

---
