"""I-B M4 Stage 0P — interface hep kiem tra pending-deletion (F-M4-0P-02B, CLOSED AT DESIGN LEVEL).

Collector KHONG BAO GIO co PSID (migration 039 khong grant SELECT customers.psid cho
`alpha3s_m4_sample_collector`). Module nay la duong DUY NHAT tra PSID -> boolean; bien `psid`
CHI TON TAI trong scope ham nay — khong return, khong log, khong dua vao audit metadata, khong
gan vao state cua caller.

Goi 2 lan cho MOI khach: (1) luc chon batch (Phase 1, §4), (2) TRUOC KHI giu control fence VA
mot lan nua NGAN HON BEN TRONG fence (Phase 2 — xem stage0p_sampling.py run_collector). Ngay ca
khi race van lot, DSR (app/services/data_deletion.py, muc #17) la THAM QUYEN CUOI CUNG vo dieu
kien — xoa sample bat ke check nay tra gi truoc do.

REV 3 (CA Technical Review #2, T2-01): ca cau DB (`customers.psid`) lan Redis (`del_pending:...`)
gio deu co TIMEOUT tuong minh (khong con vo han) — day la 1 phan cua fenced work unit (khi goi
tu BEN TRONG advisory lock 4013003, xem stage0p_sampling.py), 1 lan doc treo vo han se giu lock
vo thoi han, chan `m4_stage0p_set_capture(OFF)` khong bao gio commit duoc. Loi/timeout van fail-
closed = pending True (an toan hon, giu nguyen tinh than ban goc)."""

import asyncio
import json

import redis.asyncio as aioredis

from app.config import settings

DEFAULT_PENDING_CHECK_TIMEOUT_SECONDS = 1.5


def _log(event: str, **fields) -> None:
    print("[m4-stage0p-eligibility] " + json.dumps({"event": event, **fields},
                                                    ensure_ascii=False, sort_keys=True))


async def _audit_best_effort(conn, customer_id: int, payload: dict) -> None:
    """Audit tot-nhat-co-the — KHONG de loi audit lam vo hieu ket qua fail-closed da co (vd khi
    chinh conn dang gap loi/timeout, INSERT tiep theo tren cung conn co the fail theo)."""
    try:
        await conn.execute(
            "INSERT INTO audit_log (actor_type, action, entity_type, entity_id, after) "
            "VALUES ('system','m4_pending_check','customer',$1,$2::jsonb)",
            str(customer_id), json.dumps(payload),
        )
    except Exception as e:  # noqa: BLE001 — audit la best-effort o day, khong phai gate chinh
        _log("m4_pending_check_audit_failed", customer_id=customer_id, error_type=type(e).__name__)


async def is_pending_deletion(conn, customer_id: int, *,
                              timeout: float = DEFAULT_PENDING_CHECK_TIMEOUT_SECONDS) -> bool:
    """True neu khach dang cho xac nhan xoa du lieu (`del_pending:{psid}` con TTL).

    `conn` phai xac thuc bang role `alpha3s_m4_pending_checker`. `timeout` (giay) ap cho CA cau
    DB lan cau Redis — REV3 T2-01: goi tu ben trong fenced work unit PHAI truyen `timeout` ngan
    hon (xem `PENDING_RECHECK_TIMEOUT_SECONDS` trong stage0p_sampling.py) de gioi han thoi gian
    giu advisory lock. Khach khong ton tai -> False (khong pending, chi la khong khop)."""
    try:
        row = await conn.fetchrow("SELECT psid FROM customers WHERE id = $1", customer_id,
                                  timeout=timeout)
    except Exception as e:  # noqa: BLE001 — DB loi/timeout -> fail closed (coi la pending)
        _log("m4_pending_check_db_error", customer_id=customer_id, error_type=type(e).__name__)
        await _audit_best_effort(conn, customer_id, {"pending": True, "reason": "db_error_fail_closed"})
        return True
    if row is None:
        _log("m4_pending_check", customer_id=customer_id, pending=False, reason="no_such_customer")
        return False

    psid = row["psid"]  # scope CHI trong ham nay — khong duoc thoat ra ngoai bang bat ky duong nao
    try:
        redis = await aioredis.from_url(settings.redis_url, decode_responses=True,
                                        socket_timeout=timeout, socket_connect_timeout=timeout)
        try:
            exists = await asyncio.wait_for(redis.exists(f"del_pending:{psid}"), timeout=timeout)
        finally:
            await redis.aclose()
    except Exception as e:  # noqa: BLE001 — Redis loi/hang/timeout -> fail closed
        _log("m4_pending_check_redis_error", customer_id=customer_id, error_type=type(e).__name__)
        await _audit_best_effort(conn, customer_id, {"pending": True, "reason": "redis_error_fail_closed"})
        return True

    pending = bool(exists)
    _log("m4_pending_check", customer_id=customer_id, pending=pending)
    await _audit_best_effort(conn, customer_id, {"pending": pending})
    return pending
