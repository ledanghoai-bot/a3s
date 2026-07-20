# Changelog

## [Unreleased]

### Added

- `UAT-001-ALPHA3S-TEST-PACK.md` approved v1.0.0 với 100 test cases phục vụ Release Readiness.

### Fixed

- Chuẩn hóa YAML front matter cho `SKL-BRAND-001`, `SKL-CS-001` và `SKL-PRD-003`.
- Khóa canonical Skill root là `skills/` (số nhiều).
- Khóa vị trí FAQ tại `skills/faq/`.
- Đánh dấu `skill/` và `docs/faq/` là cấu trúc không hợp lệ trong release và ingestion.

Tài liệu này ghi lại các thay đổi chính thức của Alpha3S Knowledge Base.

Định dạng dựa trên Keep a Changelog và Semantic Versioning.

## [Unreleased]

### Next

- Implementation, smoke testing and supervised production operation.

### Added

- Draft `IMPLEMENTATION_PLAN.md` cho phase sau Knowledge Base V1.
- Draft `DEV_HANDOFF_CHECKLIST.md`.
- Draft `MVP_RELEASE_CHECKLIST.md`.
- Tái xuất bản approved `SKL-CS-003`, `SKL-PRD-001`, `SKL-PRD-002` và `SKL-PRD-004` trong workspace hiện tại.
- Tái xuất bản approved `SKL-CS-002 — Need Discovery` trong workspace hiện tại.

### Changed

- Tái biên soạn `README.md` thành repository entry point `draft v2.0.0`, chờ PO review.
- Đồng bộ cây thư mục README với canonical layout trong `depository-structure.md`; README lên `draft v2.0.1`.
- Tái biên soạn root documents theo baseline W1–W9: `FOUNDATION.md`, `STYLE_GUIDE.md`, `CONTRIBUTING.md`, `ARCHITECTURE.md` và `taxonomy.yaml` ở `draft v2.0.0`.

### Approved

- PO phê duyệt `README.md v2.0.1`.
- PO xác nhận `depository-structure.md v2.2.0` là canonical repository structure.
- PO phê duyệt `CHANGELOG.md` hiện hành ngày 2026-07-20.
- PO phê duyệt `FOUNDATION.md`, `STYLE_GUIDE.md`, `CONTRIBUTING.md`, `ARCHITECTURE.md` và `taxonomy.yaml` phiên bản 2.0.0.

## [KNOWLEDGE-BASE-1.0.0] - 2026-07-20

### Released

- Alpha3S Knowledge Base V1 hoàn tất.
- Foundation, Brand, Product, Sales, Conversation, FAQ, Knowledge Graph, Prompt/Runtime, Evaluation và Developer Handoff đã được PO phê duyệt.

### Next Phase

- Implementation and Go-Live MVP.
- Không tiếp tục mở rộng Knowledge Architecture nếu chưa có dữ liệu vận hành thực tế.

## [W9-DEVELOPER-HANDOFF-1.0.0] - 2026-07-19

### Added

- `DEVELOPER_GUIDE.md`.
- `INGESTION_GUIDE.md`.
- `RAG_PIPELINE.md`.
- `API_CONTRACT.md`.
- `TESTING_GUIDE.md`.
- `DEPLOYMENT_GUIDE.md`.
- `REFERENCE_IMPLEMENTATION.md`.
- `BEST_PRACTICES.md`.
- `ANTI_PATTERNS.md`.

### Approved

- Product Owner đã phê duyệt toàn bộ chín tài liệu Wave 9.
- Các tài liệu được compile từ `draft v0.1.0` thành `approved v1.0.0`.
- Wave 9 — Developer Integration and Handoff được khóa và đánh dấu hoàn thành.
- Alpha3S Knowledge Architecture & Developer Handoff baseline hoàn tất.

### Decision

- Dừng mở rộng kiến trúc ở W9.
- Chuyển sang implementation, smoke test và vận hành với khách thật.

## [W8-EVALUATION-1.0.0] - 2026-07-19

### Added

- `EV-001` — Evaluation Framework.
- `EV-002` — Test Case Schema.
- `EV-003` — Retrieval and Routing Evaluation.
- `EV-004` — Response Quality and Safety Evaluation.
- `EV-005` — Continuous Learning Loop.

### Approved

- Product Owner đã review và phê duyệt toàn bộ năm tài liệu Wave 8.
- Các tài liệu được compile từ `draft v0.1.0` thành `approved v1.0.0`.
- Wave 8 — Evaluation and Continuous Learning được khóa và đánh dấu hoàn thành.

## [W7-PROMPT-RUNTIME-1.0.0] - 2026-07-19

### Added

- `PA-001` — Prompt Assembly Pipeline.
- `PA-002` — Context Selection and Budget.
- `PA-003` — Source Ordering and Conflict Resolution.
- `RT-001` — Runtime Input Output Contract.
- `RT-002` — Runtime Guardrails and Fallbacks.

### Approved

- Product Owner đã review và phê duyệt toàn bộ năm tài liệu Wave 7.
- Các tài liệu được compile từ `draft v0.1.0` thành `approved v1.0.0`.
- Wave 7 — Prompt Assembly and Runtime Integration được khóa và đánh dấu hoàn thành.

### Notes

- Runtime context được lắp ráp theo Knowledge Unit thay vì load toàn bộ repository.
- Source ordering, context budget, runtime contract và fallback đã có baseline độc lập với model/framework.

## [W6-KNOWLEDGE-GRAPH-1.0.0] - 2026-07-19

### Added

- `KG-001` — Knowledge Graph Model.
- `KG-002` — Entity and Relationship Taxonomy.
- `KG-003` — Impact Analysis Rules.
- `TRACEABILITY.md` — Knowledge Traceability Matrix.

### Approved

- Product Owner đã review và phê duyệt toàn bộ bốn tài liệu Wave 6.
- Các tài liệu được compile từ `draft v0.1.0` thành `approved v1.0.0`.
- Wave 6 — Knowledge Graph and Traceability được khóa và đánh dấu hoàn thành.

### Notes

- Knowledge Graph hiện là schema và traceability contract.
- Chưa yêu cầu graph database hoặc runtime automation.

## [W5-FAQ-1.0.0] - 2026-07-19

### Added

- `SKL-FAQ-001` — Brand and Product FAQ.
- `SKL-FAQ-002` — Taste and Comparison FAQ.
- `SKL-FAQ-003` — Brewing and Personalization FAQ.
- `SKL-FAQ-004` — Caffeine, Nutrition and Safety FAQ.
- `SKL-FAQ-005` — Ordering Support and Tool Routing FAQ.

### Approved

- Product Owner đã review và phê duyệt toàn bộ năm FAQ Skills.
- Các tài liệu được compile từ `draft v0.1.0` thành `approved v1.0.0`.
- Wave 5 — FAQ Domain / Knowledge Delivery Layer được khóa và đánh dấu hoàn thành.

### Notes

- FAQ là Delivery Layer và không tự tạo Brand/Product Fact.
- Câu hỏi dữ liệu động tiếp tục route sang Tool.

## [W4-CONVERSATION-1.0.0] - 2026-07-19

### Added

- `SKL-CON-001` — Conversation Orchestration.
- `SKL-CON-002` — Conversation State Management.
- `SKL-CON-003` — Next Best Action.
- `PBK-BRAND-VOICE` — 3S Coffee Brand Voice.
- `PBK-RESPONSE-STANDARD` — Response Standard.
- `PBK-TONE-MATRIX` — Tone Matrix.

### Approved

- Product Owner đã review và phê duyệt toàn bộ sáu tài liệu Wave 4.
- Các tài liệu được compile từ `draft v0.1.0` thành `approved v1.0.0`.
- Wave 4 — Conversation Engine and Shared Playbooks được khóa phạm vi và đánh dấu hoàn thành.

### Notes

- Conversation Engine điều phối Source Priority, state và Next Best Action.
- Shared Playbooks quản lý cách diễn đạt, tiêu chuẩn phản hồi và tone; không phải nguồn Product Fact.

## [W3-SALES-1.0.0] - 2026-07-19

### Added

- `SKL-SAL-001` — Consultative Selling Principles.
- `SKL-SAL-002` — Customer Intent Recognition.
- `SKL-SAL-003` — Questioning Framework.
- `SKL-SAL-004` — Recommendation Engine.
- `SKL-SAL-005` — Sales Conversation Patterns.

### Approved

- Product Owner đã review và phê duyệt toàn bộ năm Sales Skills.
- Cả năm tài liệu được compile từ `draft v0.1.0` thành `approved v1.0.0`.
- Wave 3 — Sales Knowledge Foundation được khóa phạm vi và đánh dấu hoàn thành.

### Notes

- Wave 3 kết nối Brand Truth và Product Knowledge với năng lực tư vấn bán hàng.
- Mọi khuyến nghị tiếp tục tuân thủ nguyên tắc `Fact → Observation → Recommendation`.
- Thông tin động vẫn phải lấy từ Tool; Sales Skills không được dùng để tạo giá, tồn kho, khuyến mãi hoặc trạng thái đơn.

## [W2-PRODUCT-1.0.0] - Prior release

### Added

- Brand Truth Foundation.
- Product Knowledge từ `SKL-PRD-001` đến `SKL-PRD-004`.
- Product ADR từ `ADR-PRD-001` đến `ADR-PRD-003`.

## [W1-FOUNDATION-1.0.0] - Prior release

### Added

- Knowledge Foundation, Style Guide, Contribution Guide and Architecture baseline.
- Taxonomy and ADR governance foundation.
