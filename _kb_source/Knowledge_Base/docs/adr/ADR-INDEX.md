---
id: ADR-INDEX
title: Alpha3S Architecture Decision Record Index
document_type: adr_index
owner: Alpha3S
version: 1.1.0
status: approved
last_updated: 2026-07-19
---

# ADR Index

## Product Domain

| ADR ID | Title | Status | Related assets |
|---|---|---:|---|
| `ADR-PRD-001` | Brand Truth as Single Source of Truth | locked | `SKL-BRAND-001`, all Product and Sales Skills |
| `ADR-PRD-002` | Product Skills Reference Brand Truth | locked | `SKL-PRD-001` to `SKL-PRD-004` |
| `ADR-PRD-003` | Product Knowledge to Customer Experience | locked | `SKL-PRD-003`, `SKL-SAL-004` |

## Wave 3 Review

Wave 3 không tạo ADR mới. Năm Sales Skills triển khai các quyết định kiến trúc hiện hữu và không làm thay đổi kiến trúc nền:

- Brand Truth tiếp tục là Single Source of Truth.
- Product Facts được chuyển thành tư vấn theo `Fact → Observation → Recommendation`.
- Dữ liệu động thuộc Tool Layer.
- Sales Skills là Behavior/Decision Layer, không tự tạo Brand Fact hoặc Product Fact.

## Next ADR Trigger

Chỉ tạo ADR mới khi Wave 4 đưa ra một quyết định khó đảo ngược hoặc ảnh hưởng nhiều domain, chẳng hạn:

- Tách Conversation Engine khỏi Sales Skills.
- Chuẩn hóa assembly giữa Knowledge, Playbook và Prompt.
- Thay đổi đơn vị retrieval từ section sang Knowledge Unit.

Các thay đổi nội dung thông thường không cần ADR; ghi vào `CHANGELOG.md` là đủ.
