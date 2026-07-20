---
id: DEV-BEST-PRACTICES
title: Best Practices
domain: integration
version: 1.0.0
status: approved
approved_by: PO
last_review: 2026-07-19
review_after: 2027-01-19
owner: Alpha3S
---

# Knowledge

- Một source canonical cho mỗi fact quan trọng.
- Structure English, Knowledge Vietnamese.
- ID/version/status bắt buộc.
- FAQ references source; không trở thành source ngược.
- Derived fact ghi inputs và stale khi input đổi.

# Retrieval

- Chunk theo heading/intent.
- Hybrid search cho tiếng Việt + tên/ID.
- Filter approved trước search.
- Rerank và dedupe.
- Log selected/rejected source IDs.

# Prompt

- Block-based assembly.
- Chỉ load context liên quan.
- Tool result tách khỏi Knowledge.
- Một Next Best Action.
- Reserve output budget.

# Runtime

- Tool gate trước static retrieval cho dữ liệu động.
- Complaint/safety tắt sales progression.
- Preserve confirmed state; inferred state không ghi đè.
- Validate response trước gửi.
- Retry có giới hạn.

# Testing

- P1 smoke suite nhỏ nhưng bắt buộc.
- Mỗi lỗi production thành regression test.
- Không dùng average score che S0/S1.
- So model với cùng fixtures.

# Deployment

- Version mọi artifact/index/config.
- Build beside, atomic switch, rollback.
- Canary trước full production.
- Log release manifest.

# Business Discipline

- Ưu tiên câu hỏi cản trở 10 đơn cà phê đầu tiên.
- Không xây graph DB/dashboard nếu schema/docs đã đủ.
- Đo bằng customer outcome, không bằng số file.
