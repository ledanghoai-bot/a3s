---
id: DEV-INGESTION
title: Knowledge Ingestion Guide
domain: integration
version: 1.0.1
status: approved
approved_by: PO
last_review: 2026-07-19
review_after: 2027-01-19
owner: Alpha3S
---

# Purpose

Quy định cách chuyển Markdown đã approved thành Knowledge Units có thể tìm kiếm và truy vết.

# Canonical Path Validation

Ingestion chỉ chấp nhận Skill từ `skills/` (số nhiều). FAQ phải nằm trong `skills/faq/`.

Các đường dẫn `skill/` và `docs/faq/` là không hợp lệ. Pipeline phải dừng với lỗi cấu trúc rõ ràng thay vì tự tạo alias hoặc âm thầm di chuyển file.

# Included Assets

Ingest customer-runtime content:

- Brand, Product, CS, Sales, Conversation và FAQ Skills.
- Shared Playbooks khi Prompt Assembly yêu cầu.

Không embed mặc định:

- README, CHANGELOG, CONTRIBUTING.
- ADR, roadmap và governance docs.
- Developer/integration docs.
- Draft, superseded hoặc archived files.

# Pipeline

```text
Discover files
  → Parse front matter
  → Validate schema/status
  → Classify asset type
  → Split by semantic heading
  → Attach inherited metadata
  → Generate stable KU ID
  → Deduplicate
  → Embed/index
  → Publish versioned index
```

# Chunking Rules

- Chunk theo `##`/`###` có ý nghĩa.
- Giữ parent title và section heading.
- Một chunk nên tập trung một intent/fact/decision.
- Không cắt bảng fact khỏi heading/context liên quan.
- Nếu section quá dài, tách theo subsection; không cắt máy móc theo ký tự.
- FAQ Object nên là một Knowledge Unit độc lập.

# Required Metadata

```yaml
id: KU-FAQ-003-005
parent_id: SKL-FAQ-003
source_file: skills/faq/SKL-FAQ-003.md
source_version: 1.0.0
status: approved
domain: faq
heading: FAQ-BREW-005 — Nên pha mấy muỗng?
language: vi
dependencies: []
content_hash: string
```

# Stable IDs

- ID không phụ thuộc vị trí dòng.
- Không tái sử dụng ID của section đã bị xóa cho nội dung khác.
- Khi content đổi nhưng identity giữ nguyên, giữ KU ID và tăng source version/hash.

# Validation

Block ingestion khi:

- Thiếu `id`, `version`, `status`.
- ID trùng.
- Status không phải approved cho production.
- Dependency bắt buộc không tồn tại.
- File encoding không phải UTF-8.

# Index Publication

- Build index mới bên cạnh index hiện tại.
- Chạy smoke retrieval.
- Atomic switch sang index mới.
- Giữ index trước để rollback.

# Rebuild Scope

- Metadata/keyword thay đổi: reindex affected KU.
- Content fact thay đổi: re-embed KU + consumers theo impact analysis.
- Embedding model đổi: full re-embed vào index version mới.

# Acceptance

- 100% production units có provenance.
- 0 draft/superseded units.
- Số KU và rejected files có báo cáo.
- P1 canonical sources retrieve được sau ingest.
