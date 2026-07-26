---
id: A3S-PHASE1B-M1-RUNBOOK
title: Alpha3S M1 — Operator Runbook (Reliable Command and Receipt)
milestone: M1
language: vi-VN
---

# M1 Operator Runbook — Command Bus + Outbox

> Nguyên tắc: mọi lệnh production **read-only trước**; mutation phải có **actor + reason** và được
> audit fail-closed. Không xóa attempt/dead-letter bằng tay. Không sửa migration đã apply.

## 0. Bảng điều khiển
- Dashboard → **Vận hành** (`/ops`): tab Outbox (retry/replay/cancel) + tab Commands.
- Metrics + alert: `GET /dashboard/ops/metrics` (quyền `commands.view`).
- Metric khóa: `outbox_oldest_pending_age_seconds`, `outbox_dead_letter_total`,
  `delivery_retry_ratio_30m`, `stale_processing_total`, `credential_error_15m`.

## 1. Alert → hành động

| Alert | Sev | Nghĩa | Việc làm |
|---|---|---|---|
| `outbox_oldest_pending` | P1 | Hàng đợi tồn > 15 phút | Kiểm tra worker sống? credential? → mục 2/3 |
| `dead_letter_present` | P1 | Có event dead-letter | Mục 4: điều tra → retry/replay/cancel có reason |
| `credential_outage` | P1 | 401/403 khi gửi Telegram | Mục 3: xác minh `TELEGRAM_BOT_TOKEN`/chat id |
| `high_retry_ratio` | P2 | > 10% attempt phải retry | Provider chập chờn — theo dõi, chưa cần can thiệp gấp |
| `stale_command_processing` | P2 | command `processing` > 5 phút | Mục 5: reconcile lease/command |

## 2. Worker/queue tồn đọng
1. `GET /dashboard/ops/metrics` xem `outbox_oldest_pending_age_seconds` + `outbox_by_status`.
2. Kiểm tra arq worker container Up: `docker ps | grep worker`; log `docker logs alpha3s-worker-1 --tail 50`.
3. Cron drain chạy mỗi 10s (`deliver_outbox_job`). Nếu worker chết → restart `docker restart alpha3s-worker-1`.
4. Lease hết hạn của event `delivering` được **tự reclaim** ở vòng drain kế (không cần tay).

## 3. Credential outage (401/403)
1. Metric `credential_error_15m > 0` hoặc alert `credential_outage`.
2. Xác minh biến môi trường `TELEGRAM_BOT_TOKEN` + `TELEGRAM_ADMIN_CHAT_ID` (không in token ra log).
3. Sau khi khôi phục credential: event đang `dead_lettered` do 401/403 → **outbox.retry** (reason).

## 4. Điều tra + xử lý dead-letter
1. `/ops` tab Outbox, filter `dead_lettered` → **Chi tiết** xem redacted payload + attempt timeline.
2. Quyết định:
   - **Retry** (`outbox.retry`, quyền operator): gửi lại cùng nội dung/dedupe, reset attempt budget.
   - **Replay** (`outbox.replay`, quyền admin): tạo event mới (dedupe `:replay:`) khi cần gửi lại có
     chủ đích; **bắt buộc reason** + xác nhận đơn đã tồn tại.
   - **Cancel** (`outbox.cancel`): chỉ khi không cần gửi nữa (event chưa delivered).
3. Mọi hành động ghi audit (`outbox.retry/replay/cancel`) — tra `audit_log` theo `entity_id`.

## 5. Command `processing` treo (reconcile)
1. Thiết kế M1 chạy 1 transaction → committed command luôn terminal; `processing` committed là bất
   thường (hoặc dùng two-phase tương lai).
2. Read-only: `SELECT id, correlation_id, started_at FROM command_executions WHERE status='processing'`.
3. KHÔNG tự chạy lại mù. Đối chiếu business (order tồn tại?) rồi forward-fix; không sửa terminal → non-terminal
   (trigger DB chặn).

## 6. Truy vấn nhanh (read-only)
```sql
-- outbox tồn đọng
SELECT status, count(*), min(available_at) FROM outbox_events GROUP BY status;
-- attempt gần đây theo kết quả
SELECT outcome, count(*) FROM delivery_attempts WHERE started_at > now()-interval '1 hour' GROUP BY outcome;
-- lịch sử 1 event
SELECT attempt_no, outcome, http_status, error_class, started_at FROM delivery_attempts
WHERE outbox_event_id=$1 ORDER BY attempt_no;
-- command theo correlation
SELECT id, status, resource_id, error_code FROM command_executions WHERE correlation_id=$1;
```

## 7. Escalation + forward-fix
- Dead-letter còn tồn sau xử lý, hoặc credential không khôi phục được → escalate PO/CA.
- Sửa lỗi bằng **forward migration/deploy**, không rollback migration đã apply. Rollback ứng dụng chỉ bằng
  tắt flag `M1_RELIABLE_ORDER_COMMAND` khi schema expand vẫn tương thích; event đã tạo phải được drain/xử lý,
  không dừng worker vô thời hạn.
