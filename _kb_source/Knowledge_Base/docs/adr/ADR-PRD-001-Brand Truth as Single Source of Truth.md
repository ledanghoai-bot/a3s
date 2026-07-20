# ADR-PRD-001 --- Brand Truth as Single Source of Truth

**Status:** Locked\
**Version:** 1.0.0\
**Domain:** Product\
**Date:** 2026-07-17

# Context

Trong quá trình xây dựng Knowledge Base, các định nghĩa về thương hiệu,
sản phẩm và thông điệp xuất hiện ở nhiều tài liệu khác nhau, tạo nguy cơ
sai lệch và mất tính nhất quán.

# Decision

-   Thiết lập **SKL-BRAND-001** là **Single Source of Truth** cho toàn
    bộ thông tin thương hiệu.
-   Mọi Product Skills, Sales Skills, FAQ và Prompt chỉ được tham chiếu
    tới Brand Truth, không tự định nghĩa lại thương hiệu.
-   Mọi thay đổi về Brand phải được cập nhật tại SKL-BRAND-001 trước khi
    lan tỏa sang các tài liệu khác.

# Consequences

## Benefits

-   Một nguồn chân lý duy nhất.
-   Loại bỏ mâu thuẫn giữa các tài liệu.
-   Đơn giản hóa việc bảo trì Knowledge Base.

## Risks

-   Thay đổi Brand Truth cần được quản trị chặt chẽ vì ảnh hưởng rộng.

# References

-   SKL-BRAND-001
-   ADR-PRD-002
-   ADR-PRD-003
