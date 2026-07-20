# ADR-PRD-002 --- Product Skills Reference Brand Truth

**Status:** Locked\
**Version:** 1.0.0\
**Domain:** Product\
**Date:** 2026-07-17

# Context

Các Product Skills dễ bị lặp lại nội dung thương hiệu hoặc diễn giải
khác nhau nếu không có quy tắc tham chiếu thống nhất.

# Decision

-   Mọi **SKL-PRD-xxx** chỉ mô tả kiến thức sản phẩm trong phạm vi của
    mình.
-   Các thông tin về định vị, giá trị cốt lõi, tuyên bố thương hiệu và
    thông điệp chính phải tham chiếu **SKL-BRAND-001**.
-   Product Skills không được tạo thêm Brand Facts hoặc mâu thuẫn với
    Brand Truth.

# Consequences

## Benefits

-   Product Knowledge rõ phạm vi.
-   Tránh trùng lặp nội dung.
-   Dễ cập nhật khi Brand thay đổi.

## Risks

-   Nếu Brand Truth chưa đầy đủ, Product Skills sẽ thiếu thông tin tham
    chiếu.

# References

-   SKL-BRAND-001
-   SKL-PRD-001
-   SKL-PRD-002
-   ADR-PRD-001
-   ADR-PRD-003
