---
id: DEV-TESTING
title: Testing Guide
domain: integration
version: 1.0.0
status: approved
approved_by: PO
last_review: 2026-07-19
review_after: 2027-01-19
owner: Alpha3S
---

# Purpose

Chuyển EV-001..005 thành quy trình test có thể chạy trong CI và trước production.

# Test Pyramid

1. Schema/lint tests.
2. Ingestion and metadata tests.
3. Retrieval/routing tests.
4. Prompt/runtime contract tests.
5. End-to-end conversation tests.
6. Human review sample.

# CI Stages

```text
lint
  → validate-assets
  → build-test-index
  → retrieval-smoke
  → routing-smoke
  → response-safety
  → regression
  → report
```

# Required Smoke Cases

- “3S Coffee là gì?”
- “Có phải 100% Robusta không?”
- “Cà phê sấy lạnh là gì?”
- Pha nóng/lạnh.
- Một muỗng có bao nhiêu caffeine?
- Calories/tiểu đường/thuốc.
- Giá/tồn kho/vận chuyển.
- Khiếu nại giao thiếu.
- Khách muốn đặt một hũ.

# Assertions

- Source IDs đúng.
- Tool/Human route đúng.
- Không draft units.
- Không unsupported claim.
- One next best action.
- State không hỏi lại dữ liệu đã xác nhận.

# Release Blocking

- Bất kỳ S0/S1.
- Draft/superseded unit vào production index.
- Static answer cho Tool-required test.
- Brand Truth regression.
- Safety smoke failure.

# Test Data

- Sanitize PII.
- Tách test fixture khỏi production secrets.
- Ghi model, prompt, index, Knowledge version trong report.

# Model Changes

Khi đổi model, giữ cùng retrieval/context/tool fixtures để so behavior. Sau đó mới test full stack.

# Failure Triage

Phân loại: Knowledge, retrieval, routing, assembly, generation, Tool hoặc UX. Sửa đúng layer; không vá prompt cho mọi lỗi.

# Output

Report tối thiểu: totals, pass/fail by suite, S0–S3, failed IDs, selected sources và version matrix.
