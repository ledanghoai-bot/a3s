---
id: ALPHA3S-CONTRIBUTING
title: Contributing Guide
document_type: governance
owner: Alpha3S
version: 2.0.0
status: approved
approved_by: PO
last_review: 2026-07-20
review_after: 2027-01-20
last_updated: 2026-07-20
---

# Contributing to Alpha3S Knowledge Base

## Working Agreement

```text
Author/CA defines scope
  → Draft .md
  → Self-review
  → PO review
  ├─ Approve → version, publish and lock
  └─ Amend   → revise and review again
```

## Before Writing

1. Tìm canonical source hiện có.
2. Kiểm tra document có trùng responsibility không.
3. Xác định asset type và ID.
4. Xác định dữ liệu là static Knowledge hay dynamic Tool data.
5. Xác định consumers và test bị ảnh hưởng.

## Naming

- Skill: `SKL-{DOMAIN}-{NNN}.md`.
- Playbook: `PBK-{NAME}.md`.
- ADR: `ADR-{DOMAIN}-{NNN}.md`.
- Evaluation: `EV-{NNN}-{TITLE}.md`.
- Không dùng khoảng trắng trong canonical filename.

## Status Lifecycle

```text
draft → review → approved → locked → superseded → archived
```

- Không sửa im lặng bản locked.
- Thay đổi có ý nghĩa phải tăng version và cập nhật CHANGELOG.
- Breaking schema/meaning: MAJOR.
- Nội dung mới tương thích: MINOR.
- Sửa wording/metadata không đổi nghĩa: PATCH.

## Change Process

1. Sửa canonical source trước.
2. Dùng `TRACEABILITY.md`/`KG-003` tìm consumers.
3. Cập nhật derived facts và tests.
4. PO approve.
5. Rebuild affected Knowledge Units/index.
6. Chạy smoke/regression.
7. Publish versioned release.

## Pull Request / Review Checklist

- [ ] ID không trùng.
- [ ] Status/version hợp lệ.
- [ ] Source facts đã xác thực.
- [ ] Không dynamic data.
- [ ] Dependencies tồn tại.
- [ ] FAQ không tự tạo fact.
- [ ] Safety/complaint routing đúng.
- [ ] Test/impact analysis đã cập nhật.
- [ ] CHANGELOG đã ghi nhận nếu cần.

## Commit Message Examples

```text
docs(product): update brewing facts
docs(faq): add cold brewing variants
fix(brand): remove unsupported claim
test(routing): add pricing tool regression
```

## Do Not

- Không chỉnh trực tiếp production Knowledge.
- Không approve nội dung do AI tự đề xuất nếu chưa có PO/source review.
- Không sửa test expectation chỉ để model pass.
- Không auto-deploy chỉ vì Markdown thay đổi.
