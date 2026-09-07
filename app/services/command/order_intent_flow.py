"""Layer B — orchestrator-side order-intent lifecycle (CA Directive 223 + Amendment 224 §5/§7/§9).

Server SO HUU intent. Module nay resolve-or-create "current intent" cho MOT prospective order TRUOC khi
create_order chay, de cung mot order_intent_id chay xuyen nhieu luot (clarify/correction/confirm/retry/
redelivery) -> at-most-once commit o tang DB (Layer C: order_service._run_winner). Sau commit, ghi
committed-pointer de tra receipt tat dinh cho stale-confirmation (§7.4) ma KHONG tao don moi.

Redis (conversation-scoped, chi COORDINATE — DB la nguon su that theo §6):
- oi:{conv}            -> {"intent_id","order_fp"}                 intent OPEN hien tai
- oi_committed:{conv}  -> {"intent_id","order_fp","order_id"}      lan commit gan nhat (cua so post-commit)

ANCHOR = OPEN intent (§5 "one active intent spans clarification/correction/confirmation/retry/redelivery").
- Con OPEN intent cung fingerprint -> REUSE (nhieu luot cung don) -> Layer C dedup -> 1 don.
- Khong con OPEN + co committed-pointer cung fingerprint (stale confirm §7.4) -> tra committed intent_id
  -> Layer C tra receipt cu (zero mutation). explicit_new_order=True BO QUA buoc nay -> intent MOI (§7.5,
  case 15 harness). Production MAC DINH explicit_new_order=False = an toan (khong vo tinh tao don doi).
- Khong con OPEN + khong committed-pointer khop -> intent MOI (don moi that su / fingerprint khac).

KHONG BAO GIO raise ra luong reply (§3.11 M5): moi loi -> tra {} -> caller giu idempotency tang command cu.
"""
from __future__ import annotations

import json

import redis.asyncio as aioredis

from app.config import settings
from app.db_pool import acquire, release
from app.services.command import order_intent as oi
from app.services.command import order_intent_service as svc
from app.services.safe_log import safe_exc

_OPEN_TTL = 3600          # oi:{conv} song toi da 1h (abandoned -> EXPIRED reaper doc lap; TTL chi cleanup §7)
_COMMITTED_TTL = 900      # cua so post-commit stale-confirm 15' (TTL chi recovery, KHONG quyet dinh identity)


def _k_open(conv) -> str:
    return f"oi:{conv}"


def _k_committed(conv) -> str:
    return f"oi_committed:{conv}"


async def _advance_to_ready(conn, intent_id: str, order_fp: str, addr_fp: str | None,
                            resolution_id: str | None) -> None:
    """Dua intent moi tao (COLLECTING) qua ADDRESS_CHECK -> READY_TO_COMMIT (best-effort, fail-closed).
    Ghi fingerprint + resolution vao intent. Loi transition (version lech) khong lam vo — commit van an
    toan vi _run_winner chi kiem tra COMMITTED/terminal."""
    r = await svc.transition(conn, intent_id, expected_version=0, to_state="ADDRESS_CHECK",
                             order_fingerprint=order_fp, verified_address_fingerprint=addr_fp,
                             verified_resolution_id=resolution_id)
    if r is not None and oi.can_transition("ADDRESS_CHECK", "READY_TO_COMMIT"):
        await svc.transition(conn, intent_id, expected_version=r["state_version"],
                             to_state="READY_TO_COMMIT")


async def resolve_or_create(*, customer_id: int | None, conversation_id, channel: str,
                            order_fp: str, addr_fp: str | None = None,
                            verified_resolution_id: str | None = None,
                            explicit_new_order: bool = False) -> dict:
    """Tra dict: {"order_intent_id": str} khi co intent de dung; {} khi bo qua (legacy command idempotency).
    Optional "stale_confirm": True khi tra ve committed intent (Layer C se tra receipt cu)."""
    if customer_id is None:
        return {}  # khach chua co row -> khong the tao intent; giu legacy (pilot/tester luon co customer)
    conn = None
    redis = None
    try:
        redis = await aioredis.from_url(settings.redis_url, decode_responses=True)
        conn = await acquire()
        # 1) OPEN intent cung fingerprint -> REUSE (anchor §5)
        open_row = await svc.find_open_intent(
            conn, customer_id=customer_id, conversation_id=conversation_id, order_fingerprint=order_fp)
        if open_row is not None:
            await redis.set(_k_open(conversation_id),
                            json.dumps({"intent_id": str(open_row["id"]), "order_fp": order_fp}),
                            ex=_OPEN_TTL)
            return {"order_intent_id": str(open_row["id"])}
        # 2) Stale-confirm sau COMMITTED (§7.4): committed-pointer cung fingerprint, KHONG phai don moi tuong minh
        if not explicit_new_order:
            raw = await redis.get(_k_committed(conversation_id))
            if raw:
                try:
                    ptr = json.loads(raw)
                except (ValueError, TypeError):
                    ptr = None
                if ptr and ptr.get("order_fp") == order_fp and ptr.get("intent_id"):
                    return {"order_intent_id": ptr["intent_id"], "stale_confirm": True}
        # 3) Intent MOI (don moi that su / fingerprint khac / explicit second §7.5)
        async with conn.transaction():
            new = await svc.create_intent(conn, customer_id=customer_id,
                                          conversation_id=conversation_id, channel=channel)
            await _advance_to_ready(conn, new["id"], order_fp, addr_fp, verified_resolution_id)
        await redis.set(_k_open(conversation_id),
                        json.dumps({"intent_id": str(new["id"]), "order_fp": order_fp}), ex=_OPEN_TTL)
        return {"order_intent_id": str(new["id"])}
    except Exception as e:  # noqa: BLE001 — never break reply/order path
        print(f"[order_intent_flow] resolve_or_create skipped: {safe_exc(e)}")
        return {}
    finally:
        if conn is not None:
            await release(conn)
        if redis is not None:
            await redis.aclose()


async def mark_committed_pointer(*, conversation_id, intent_id: str, order_fp: str,
                                 order_id: int) -> None:
    """Sau khi order commit thanh cong: xoa OPEN pointer + ghi committed-pointer (cua so stale-confirm §7.4).
    Best-effort; loi khong lam vo luong."""
    redis = None
    try:
        redis = await aioredis.from_url(settings.redis_url, decode_responses=True)
        await redis.delete(_k_open(conversation_id))
        await redis.set(_k_committed(conversation_id),
                        json.dumps({"intent_id": str(intent_id), "order_fp": order_fp,
                                    "order_id": order_id}), ex=_COMMITTED_TTL)
    except Exception as e:  # noqa: BLE001
        print(f"[order_intent_flow] mark_committed_pointer skipped: {safe_exc(e)}")
    finally:
        if redis is not None:
            await redis.aclose()
