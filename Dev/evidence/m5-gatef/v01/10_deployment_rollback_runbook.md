# Gate F Deployment Plan + Rollback/Kill-Switch Runbook + Live Verification — CA Directive 243 §5

## A. Preflight (ghi trước merge)
- deployed commit/tree/schema; flags readback (`python scripts/m5_scope_readback.py` trên VPS); orders/messages/order_intents counts + orders_digest; container health; backup freshness (pg_backup_daily); Meta readiness (app LIVE) + secret-rotation status.

## B. Merge + deploy
1. Merge exact qualified head vào `main` (squash) — pipeline/deploy tự động (main CI → VPS git pull + `compose up`).
2. Xác minh deployed tree == qualified tree; containers healthy; **readback: full-scope tất cả = OFF** (deploy KHÔNG tự bật scope — fail-closed).

## C. Bật full-scope (staged theo channel, KHÔNG cần execution window)
Cấu hình bằng .env trên VPS rồi reload/restart container app (config đọc lúc khởi tạo):
1. **Telegram trước:** đặt `GATE_E_FULLSCOPE_TELEGRAM_CUSTOMER=true` + `ADDRESS_RESOLVER_FULLSCOPE_TELEGRAM_CUSTOMER=true` → restart → **readback xác nhận** TG full-scope=ON, kill=OFF → chạy 1 flow verify từ identity NGOÀI allowlist (đặt→confirm→commit).
2. **Messenger sau** (chỉ khi đã ROTATE secret — xem receipt §09): `GATE_E_FULLSCOPE_MESSENGER=true` + `ADDRESS_RESOLVER_FULLSCOPE_MESSENGER=true` → restart → readback → chạy 1 flow verify từ external/non-test-role identity. Nếu Meta chưa nhận external traffic → báo `BLOCKED_BY_META_PLATFORM`, KHÔNG bật.

## D. Bounded live verification (mỗi channel, ghi số liệu)
- Một identity ngoài allowlist: đặt đơn → server extract → summary → confirm → **COMMITTED đúng 1 order**, **1 receipt khách + 1 admin notify**, **1 staff-history row**.
- Địa chỉ không rõ → clarify server-derived (không tự áp sai/không escalate sớm).
- Replay provider event → 0 order/receipt thừa. Cross-channel/cross-conversation: không lẫn.
- Ghi latency p50/p95 mẫu + lỗi thực tế theo channel. Đánh dấu test data để PO reset trước official launch.

## E. Rollback / Kill switch (ưu tiên cao nhất)
- **Kill switch:** đặt `GATE_E_KILL_SWITCH=true` → restart → readback xác nhận kill=ON. Chặn MỌI M5 order processing mới (full-scope + allowlist). KHÔNG hỏng order đã COMMITTED, KHÔNG xoá durable evidence (outbox/receipt/intent giữ nguyên).
- **Rollback scope 1 channel:** đặt `*_FULLSCOPE_<channel>=false` → restart → channel đó về dormant, channel kia không ảnh hưởng.
- **Rollback code:** revert merge trên `main` → deploy → về `7c2885d` (tester-only). Migration 059-061 additive, không cần down-migration.
- **Trigger rollback:** correctness/duplicate/loss/signature failure → kill channel bị ảnh hưởng, giữ evidence, rollback theo trên, báo CA.

## F. Post-activation completion
- Ghi post baseline (counts/digest/health/readback). Chứng minh: single order/receipt, no false escalation, no cross mix-up, latency. Nộp completion snapshot để CA đóng Gate F/M5.

## Config keys (typed, per-channel; default OFF; fail-closed)
`GATE_E_FULLSCOPE_TELEGRAM_CUSTOMER`, `GATE_E_FULLSCOPE_MESSENGER`,
`ADDRESS_RESOLVER_FULLSCOPE_TELEGRAM_CUSTOMER`, `ADDRESS_RESOLVER_FULLSCOPE_MESSENGER`,
`GATE_E_KILL_SWITCH` (ưu tiên cao nhất). Readback: `scripts/m5_scope_readback.py` (không in secret).
