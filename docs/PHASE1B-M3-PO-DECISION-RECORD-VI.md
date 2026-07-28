# Phase I-B M3 — PO Decision Record: Open Release Inputs

```yaml
document: PHASE1B-M3-PO-DECISION-RECORD
decided_by: Product Owner (anh Hoài)
decided_at: 2026-07-28 (chiều, qua kênh làm việc trực tiếp với Dev)
recorded_by: Dev
basis: docs/PHASE1B-M3-DEV-DELIVERY-PACKAGE-VI.md §7 + E:/Alpha3s/Dev-review/PHASE1B-M3-PO-OPEN-INPUTS-GUIDE-VI.md
scope: 5 open release inputs của M3 — đầu vào cho CA phát hành M3 merge/release gate
```

| # | Input | Quyết định PO |
|---|---|---|
| 1 | Retention [PROPOSED] | **APPROVED toàn bộ giá trị đề xuất** (RET-03=10 năm, RET-04=24 tháng, RET-05=5 năm, RET-06=30 ngày, RET-09=2 năm; RET-01/02/07 TTL giữ nguyên). Điều kiện: executor **dry-run production + PO xem report trước khi bật flag** `m3_retention_executor`. |
| 2 | DeepSeek cross-border 91/2025 | **Phương án 2 bước**: Dev soạn draft hồ sơ đánh giá + thực hiện opt-out training ngay; PO đưa legal review; hồ sơ chính thức hoàn thiện sau M4 masked input. **Không blocker M3 release.** |
| 3 | PSID trong access log | **APPROVED tắt uvicorn access log** (`--no-access-log`) trong M3 release. |
| 4 | Notify text fulfilled | **APPROVED template `order_status_fulfilled` v2**: "Đơn #{id} của bạn đã được bàn giao cho đơn vị vận chuyển." — hiệu lực khi bật `m3_outbound_dispatcher`; v1 giữ nguyên (immutable). |
| 5 | Validation migrations M3 | **APPROVED bổ sung `m3_contract_validation.sql`** (existing-safe) vào `post_migration_validations` của baseline manifest — thực hiện như release-prep delta, CA review trong merge/release gate. |

Kèm theo: PO đề nghị CA phát hành **M3 merge/release gate**.

Ghi chú thực thi (Dev): các quyết định 1/4/5 + mục 3 được chuẩn bị thành release-prep delta trên
branch M3 (migration 035/036, version map dispatcher, `--no-access-log`, validation + manifest) —
**chỉ để CA review trong gate, KHÔNG merge/deploy/bật flag trước khi gate phát hành.**
