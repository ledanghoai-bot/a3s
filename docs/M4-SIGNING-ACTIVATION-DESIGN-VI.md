# M4 — Production Signing Activation (Tier B): Thiết kế triển khai

> Authority: `CA-Docs/PHASE1B-M4-9-PRODUCTION-SIGNING-ACTIVATION-ELIGIBILITY-DESIGN-71-VI.md`
> + `…-PRODUCTION-SIGNING-REQUESTER-APPROVAL-ADDENDUM-72-VI.md`.
> **Chưa cấp production signing.** Đây là implementation cho gate tương lai; không tự mở activation.

## 1. Nguyên tắc

- **Capability tách biệt:** quyền kích hoạt production signing là `m4.signing.activate.production`,
  **KHÔNG** suy ra từ role signer. Signer chỉ *request*; không tự approve, không tự activate.
- **Hai sự kiện độc lập:** approval ≠ execution. **SoD:** approver ≠ requester/activator (trừ
  emergency PO có lý do + hậu kiểm bắt buộc).
- **Grant tạm thời:** activation có **scope tối thiểu + TTL ngắn + idempotency key**, fail-closed,
  **tự về dormant** khi hết hạn. Không "standing approval" vô thời hạn.
- **Anti-substitution:** `artifact_digest` khóa lúc request; **bất biến sau approval** (đổi digest → từ chối).
- **No secret** qua argument/env/history. **Audit bất biến** mọi bước.

## 2. State machine (bảng `m4_signing_activation`)

```
REQUESTED ─preflight(pass)→ PREFLIGHT_PASSED ─approve(SoD)→ APPROVED ─activate(in window)→ ACTIVE
    │            │(fail)                                        │                            │
    │            ▼                                              ▼ (auto khi now>window_end)   ▼
    └────────── REVOKED ◄── revoke (PO, mọi state active) ──► EXPIRED                       CLOSED
```

- Terminal: `CLOSED` (hoàn tất), `EXPIRED` (hết TTL → auto dormant), `REVOKED` (PO/auto khi
  policy-violation/key-compromise/incident).
- Transition allowlist ở service (fail-closed); DB CHECK state.

## 3. Điều kiện (Design 71 §2) — enforce ở service preflight/approve/activate

| Điều kiện | Enforce |
|---|---|
| Requester = PO/primary operator ủy quyền | quyền HTTP/CLI + `--actor` |
| Có signer role + capability activation riêng | kiểm `m4.signing.activate.production` |
| Decision record/ticket: scope, boundary, reason, window, rollback owner | field bắt buộc lúc request (fail-closed) |
| Preflight: cert/chain, key custody, KMS/WIF/token health, clock/nonce, policy version, không incident xung đột | `run_preflight` (read-only; rehearsal stub, không chạm dữ liệu khách) |
| Artifact digest khóa; manifest/evidence đủ, anti-substitution | `artifact_digest` immutable sau approve (trigger) |
| SoD production: approver ≠ activator | DB CHECK + service |
| TTL ngắn, scope tối thiểu, idempotency, fail-closed, auto-dormant | `window_end`, `request_id` unique-active, expiry auto |

## 4. Luồng CLI (Design 71 §3 + 72)

```
signer:    request   --scope --digest --manifest --ticket --reason --window-minutes --max-sign
system:    preflight --activation-id            (read-only, fail-closed)
approver:  approve   --activation-id --actor    (SoD: khác requester; kiểm digest + preflight tươi)
activator: activate  --activation-id --actor    (trong window; trả activation receipt)
PO:        revoke    --activation-id --reason   (khẩn; hoặc auto khi expiry/incident)
```
CLI từ chối nếu: thiếu approval, sai scope, digest đổi, preflight stale, quá TTL, không đạt SoD.

## 5. Audit & revoke

Mỗi request/approve/activate/revoke/expire → `audit_log` bất biến (actor/delegated_by/approver/
scope/digest/ticket/activation-id/time/TTL/result/reason — **không** secret). Revoke khẩn (PO) +
auto-revoke khi policy violation/key-cert compromise/incident.

## 6. Ranh giới rehearsal

Rehearsal chạy trọn flow request→approve→activate→revoke trên **dữ liệu tổng hợp** (digest giả),
**không chạm dữ liệu khách**, không start signer/KMS thật. Chứng minh state machine + SoD + TTL +
digest-lock + audit. Activation Gate thật chỉ mở sau CA/PO review completion riêng.

## 7. Ngoài phạm vi (job này)
Không thực thi ký production thật, không KMS/WIF/token thật, không customer data. Migration/code/test
+ rehearsal only; merge/deploy + activation thật cần gate riêng.
