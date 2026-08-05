# Alpha3S Phase I-B M4 — Integration Re-baseline Record

- **id:** A3S-PHASE1B-M4-REBASELINE-001
- **governing directive:** A3S-PHASE1B-M4-DEV-DIRECTIVE-001 v1.1.0 §11 (Integration re-baseline)
- **ngày:** 2026-07-28 18:11+07:00
- **lý do:** M2 + M3 đã merge `main` → có accepted integration baseline; M4 rebase + renumber
  migration trước khi code tiếp S2 (đúng kế hoạch dừng-chờ ghi tại S1).

## 1. Baseline mới và SHA record (§11: ghi pre/post-rebase SHAs)

| Hạng mục | Giá trị |
|---|---|
| Accepted integration baseline | `main` @ `dc839ca036baef6a5f5cee3026e0741e140b71d9` (Merge PR #3 — M3; trước đó M2) |
| Production đối chiếu | VPS đã deploy đúng SHA này, schema 037/37, validations PASS (hồ sơ M3 final package) |
| Pre-rebase heads | S0 `61e0441`, S1 `e4fa948` (base cũ: exact M2 RC `9b49628`) |
| Post-rebase heads | S0 `c5face6`, S1 `dc8193a` (trên `dc839ca`) |
| Rebase conflicts | **0** — git hoà tự động; đã review nội dung sau rebase: hook shadow -0.5 đứng đúng chỗ (sau `ensure_conversation`, trước guard handoff), imports orchestrator gộp đúng (`safe_log` của M3-S4 + `pii_shadow` của M4-S0), config có đủ 4 flag `m3_*` + 5 config `m4_*` |
| Migration head thực tế | `037_retention_policy_immutability` |
| **Renumber** | `040_m4_slot_store.sql` → **`038_m4_slot_store.sql`** (git mv, header cập nhật lịch sử số) |
| Manifest checksum mới (sha256-of-sha256 `migrations/*.sql`, 38 file) | `dd0d9a6404913cd0d1cf…` (full trong evidence run) |

## 2. Evidence chạy lại toàn bộ với số mới (môi trường: container `alpha3s-m4-test` + DB riêng `alpha3s-m4-db` pgvector:pg16 FRESH — recreate trước khi đo)

| # | Lệnh | Thời điểm | Exit | Kết quả |
|---|---|---|---|---|
| 1 | `migrate.py up` trên DB FRESH | 2026-07-28 18:02+07:00 | 0 | Applied **38 migration** (001→037 + 038); validations `operational_seed_validation.sql` + `m3_contract_validation.sql` PASS; postcondition 038 PASS |
| 2 | **Existing-apply rehearsal**: DB2 `alpha3s_rehearse` apply 001→037 (giữ 038 ra ngoài) → seed synthetic (customers/conversations) → trả 038 về → `migrate.py up` | 2026-07-28 18:05+07:00 | 0 | Applied đúng **1 migration (038)**; data intact (counts giữ nguyên), `pii_slots` tồn tại, `schema_migrations`=38; validations PASS |
| 3 | `migrate.py up` lần 2 (idempotent) | 2026-07-28 18:08+07:00 | 0 | Không pending; validations PASS |
| 4 | `scripts/m4_slot_store_test.py` | 2026-07-28 18:08+07:00 | 0 | **RESULT: PASS 20/20** (isolation/tamper-alert/replay/concurrency/expiry/role-deny/no-plaintext/log-sạch) |
| 5 | `scripts/m4_pii_shadow_test.py` | 2026-07-28 18:09+07:00 | 0 | **RESULT: PASS** (recall/precision synthetic như S0) |
| 6 | `pytest -q` | 2026-07-28 18:10+07:00 | 0 | **147 passed** (baseline mới `dc839ca` không thêm pytest test; 81+51+15 giữ nguyên) |
| 7 | `ruff check app scripts/m4_*.py tests` | 2026-07-28 18:10+07:00 | 0 | All checks passed |
| 8 | `scripts/m3_pii_log_test.py` (regression M3-S4, gồm **static guard** quét `app/` chặn pattern log nguy hiểm) | 2026-07-28 18:10+07:00 | 0 | **ALL PASS** — code M4 (`[m4-shadow]`, `[m4-slot]`) không vi phạm guard PII-log của M3 |

## 3. Tương thích với thay đổi M3 (checklist resume đã kiểm)

- Orchestrator: M3-S4 đổi `print(exception)` → `safe_exc` (~30 điểm) — hook M4 không dùng
  `str(e)` từ trước (chỉ `error_type`), không đụng nhau; import gộp sạch.
- `retention_policies`/`outbound_templates` có immutability trigger (035–037): M4 **không đụng**
  2 bảng này; `m3_contract_validation.sql` chạy PASS trong mọi lần apply ở §2.
- Flags production hiện tại: `m3_retention_executor=True` (CA activation), mọi flag `m4_*` = False.
  M4 không đổi default nào của M1/M2/M3.

## 4. Kết luận

Re-baseline §11 hoàn tất: branch M4 đứng trên `dc839ca`, migration M4 = **038** (head mới 38/38),
toàn bộ migration/regression/security evidence chạy lại PASS với số mới. Đủ điều kiện code tiếp
M4-S2 (masked orchestration). Draft PR #4 giữ nguyên (force-push sau rebase).
