"""I-B M4 Stage 0P — interface hep kiem tra pending-deletion (F-M4-0P-02B, CLOSED AT DESIGN LEVEL).

Collector KHONG BAO GIO co PSID (migration 039 khong grant SELECT customers.psid cho
`alpha3s_m4_sample_collector`). Module nay la duong DUY NHAT tra PSID -> boolean; bien `psid`
CHI TON TAI trong scope ham nay — khong return, khong log, khong dua vao audit metadata, khong
gan vao state cua caller.

Goi 2 lan cho MOI khach: (1) luc chon batch (Phase 1, §4), (2) NGAY TRUOC persist tung tin nhan
(Phase 2 — chong race giua 2 lan check, cung checkpoint voi kill switch va cap). Ngay ca khi race
van lot, DSR (app/services/data_deletion.py, muc #17) la THAM QUYEN CUOI CUNG vo dieu kien — xoa
sample bat ke check nay tra gi truoc do.
"""

import json

import redis.asyncio as aioredis

from app.config import settings


def _log(event: str, **fields) -> None:
    print("[m4-stage0p-eligibility] " + json.dumps({"event": event, **fields},
                                                    ensure_ascii=False, sort_keys=True))


async def is_pending_deletion(conn, customer_id: int) -> bool:
    """True neu khach dang cho xac nhan xoa du lieu (`del_pending:{psid}` con TTL).

    `conn` phai xac thuc bang role `alpha3s_m4_pending_checker` (migration 039 — CHI role nay
    duoc SELECT customers.psid trong pham vi M4). Khach khong ton tai (id sai/da bi xoa that su,
    ROW van con vi anonymize khong xoa customers) -> False (khong pending, chi la khong khop)."""
    row = await conn.fetchrow("SELECT psid FROM customers WHERE id = $1", customer_id)
    if row is None:
        _log("m4_pending_check", customer_id=customer_id, pending=False, reason="no_such_customer")
        return False

    psid = row["psid"]  # scope CHI trong ham nay — khong duoc thoat ra ngoai bang bat ky duong nao
    redis = await aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        exists = await redis.exists(f"del_pending:{psid}")
    except Exception as e:  # noqa: BLE001 — Redis loi -> fail closed (coi la pending, an toan hon)
        _log("m4_pending_check_redis_error", customer_id=customer_id, error_type=type(e).__name__)
        await conn.execute(
            "INSERT INTO audit_log (actor_type, action, entity_type, entity_id, after) "
            "VALUES ('system','m4_pending_check','customer',$1,$2::jsonb)",
            str(customer_id), json.dumps({"pending": True, "reason": "redis_error_fail_closed"}),
        )
        return True
    finally:
        await redis.aclose()

    pending = bool(exists)
    _log("m4_pending_check", customer_id=customer_id, pending=pending)
    await conn.execute(
        "INSERT INTO audit_log (actor_type, action, entity_type, entity_id, after) "
        "VALUES ('system','m4_pending_check','customer',$1,$2::jsonb)",
        str(customer_id), json.dumps({"pending": pending}),
    )
    return pending
