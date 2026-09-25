"""Outbox delivery worker (I-B M1 Slice 5). Spec §9, §8.2, §8.3.

Drain outbox_events -> gui external (Telegram admin) voi at-least-once + retry/backoff/dead-letter.
Claim FOR UPDATE SKIP LOCKED (nhieu worker an toan), lease 60s (crash -> reclaim). HTTP send NGOAI
transaction; ghi delivery_attempts + doi state trong statement ngan sau send. Provider timeout -> UNKNOWN
(khong failed ngay). Message chua order_id on-dinh (§8.3); payload da redact (khong PII raw).

run_once(send_fn=...) thuan-testable: inject send_fn gia de test khong cham Telegram that.
"""
from __future__ import annotations

import json
import os
import socket
import time
import uuid
from dataclasses import dataclass

import httpx

from app.config import settings
from app.db_pool import acquire, release
from app.services.command import retry as R
from app.services.command.receipt import format_vnd
from app.services.messenger import GRAPH_URL
from app.services.safe_log import safe_exc

OUTBOX_DEST_TELEGRAM_ADMIN = "telegram_admin"
OUTBOX_DEST_MESSENGER = "messenger"
OUTBOX_DEST_TELEGRAM_CUSTOMER = "telegram_customer"

WORKER_ID = f"{socket.gethostname()}:{os.getpid()}"
LEASE_SECONDS = 60
BATCH = 25

_CLAIM_SQL = """
WITH c AS (
  SELECT id FROM outbox_events
  WHERE status IN ('pending','retry_scheduled') AND available_at <= now()
    AND (lease_expires_at IS NULL OR lease_expires_at < now())
  ORDER BY available_at, created_at
  FOR UPDATE SKIP LOCKED
  LIMIT $1
)
UPDATE outbox_events o
   SET status='delivering', attempt_count=attempt_count+1,
       lease_owner=$2, lease_expires_at=now() + ($3 * interval '1 second')
  FROM c WHERE o.id=c.id
RETURNING o.id, o.command_id, o.event_type, o.destination, o.dedupe_key, o.payload,
          o.attempt_count, o.max_attempts
"""

# CA Directive 396 §2.1: tin fulfillment GUI KHACH (da giao thanh cong) -> ghi vao lich su hoi thoai `messages`
# (role 'bot', dedupe 'outbox:<event_id>') de bot/staff thay dung dieu da noi voi khach (vd ETA trong tin bao phi).
# CHI destination kenh khach; tin staff noi bo (telegram_admin) KHONG ghi. order.receipt.customer da duoc ghi
# rieng (dedupe order_receipt:<id>, CA 233-05) -> khong ghi lai.
_HISTORY_DESTINATIONS = (OUTBOX_DEST_MESSENGER, OUTBOX_DEST_TELEGRAM_CUSTOMER)
_HISTORY_EVENT_PREFIXES = ("fulfillment.", "shipment.", "payment.")
_HISTORY_EVENT_TYPES = ("order.status.customer",)


def is_history_event(event_type: str | None, destination: str | None) -> bool:
    et = event_type or ""
    return destination in _HISTORY_DESTINATIONS and (
        et.startswith(_HISTORY_EVENT_PREFIXES) or et in _HISTORY_EVENT_TYPES)


async def persist_customer_history(conn, event_id, event_type: str | None, destination: str | None,
                                   payload: dict) -> bool:
    """Ghi tin da gui khach vao `messages` (exactly-once theo outbox event). True neu ghi moi.
    Khong tao customer/conversation moi (khach phai ton tai san). Loi -> caller nuot (khong chan delivery)."""
    if not is_history_event(event_type, destination):
        return False
    text, ref = payload.get("text"), payload.get("customer_ref")
    if not text or not ref:
        return False
    conv_id = await conn.fetchval(
        "SELECT c.id FROM conversations c JOIN customers cu ON cu.id=c.customer_id WHERE cu.psid=$1 "
        "ORDER BY c.created_at DESC LIMIT 1", str(ref))
    if conv_id is None:
        return False
    rid = await conn.fetchval(
        "INSERT INTO messages(conversation_id, role, content, dedupe_key) VALUES($1,'bot',$2,$3) "
        "ON CONFLICT (dedupe_key) WHERE dedupe_key IS NOT NULL DO NOTHING RETURNING id",
        conv_id, text, f"outbox:{event_id}")
    return rid is not None


@dataclass
class SendResult:
    ok: bool
    http_status: int | None = None
    provider_message_id: str | None = None
    is_timeout: bool = False
    error_class: str | None = None


# --------------------------------------------------------------------------
# Real Telegram admin sender (destination='telegram_admin')
# --------------------------------------------------------------------------

def _telegram_admin_text(p: dict) -> str:
    if p.get("kind") == "staff_attention":
        # M7 (Directive 272 §4): hang doi staff_attention -> bao admin (redacted, chi ma don + ly do).
        return (
            "\U0001F514 3S Coffee - CAN NHAN VIEN (M7 fulfillment)\n"
            f"Ma don: #{p.get('order_id')}\n"
            f"Ly do: {p.get('reason') or '-'}\n"
            f"Chi tiet: {(p.get('detail_text') or '-')[:160]}\n"
            "(Xem dashboard /fulfillment/attention de xu ly.)"
        )
    if p.get("kind") == "escalation":
        # CA 251 §3.D + 252-02: admin-notify khi ESCALATED. has_intent=True -> escalation gan order-intent
        # (don chua chot); has_intent=False -> handoff conversation-scoped (khong gan don).
        head = (
            "\U0001F198 3S Coffee - CAN HO TRO (ESCALATION)\n"
            f"Ly do: {p.get('reason_code') or '(khong ro)'}\n"
            f"Kenh: {p.get('channel') or '-'}\n"
            # CA 387 §5: intent -> nguoi nhan (draft); conversation-scoped -> ho so chu tai khoan.
            f"{'Nguoi nhan' if p.get('has_intent') else 'Tai khoan'}: {p.get('customer_name') or '(chua co ten)'}"
            f" - SDT {p.get('phone_masked') or '***'}\n"
        )
        if p.get("has_intent"):
            return head + (
                f"San pham: {p.get('sku') or '-'} x {p.get('quantity') or '-'}\n"
                f"Dia chi (tam): {(p.get('address') or '-')[:80]}\n"
                f"Intent: {p.get('intent_id')} - Conv: {p.get('conversation_id')}\n"
                "(Don CHUA duoc chot. Xem dashboard theo intent/conversation de xu ly.)"
            )
        return head + (
            f"Chi tiet: {(p.get('reason_detail') or '-')[:120]}\n"
            f"Tin gan nhat: {(p.get('last_message') or '-')[:120]}\n"
            f"Conv: {p.get('conversation_id')} (KHONG gan don)\n"
            "(Xem dashboard theo conversation de ho tro khach.)"
        )
    return (
        "\U0001F6D2 3S Coffee - DON HANG MOI (M1)\n"
        f"Ma don: #{p.get('order_id')}\n"
        f"Nguoi nhan: {p.get('customer_name') or '(chua co ten)'} - SDT {p.get('phone_masked') or '***'}\n"
        f"San pham: {p.get('sku')} x {p.get('quantity')} @ {format_vnd(p.get('unit_price_vnd') or 0)}\n"
        f"Tong: {format_vnd(p.get('total_vnd') or 0)} - Trang thai: {p.get('status', 'new')}\n"
        "(Dia chi/SDT day du: xem dashboard theo ma don tren)"
    )


async def telegram_send(destination: str, payload: dict) -> SendResult:
    """Gui thong bao admin qua Telegram. Tra SendResult (khong raise)."""
    if destination != "telegram_admin":
        return SendResult(ok=False, http_status=400, error_class="unknown_destination")
    if not settings.telegram_bot_token or not settings.telegram_admin_chat_id:
        return SendResult(ok=False, http_status=403, error_class="not_configured")
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    timeout = httpx.Timeout(R.TOTAL_TIMEOUT, connect=R.CONNECT_TIMEOUT)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json={
                "chat_id": settings.telegram_admin_chat_id,
                "text": _telegram_admin_text(payload),
            })
    except httpx.TimeoutException:
        return SendResult(ok=False, is_timeout=True, error_class="timeout")
    except httpx.HTTPError as e:  # network/other
        return SendResult(ok=False, error_class=type(e).__name__)
    if 200 <= resp.status_code < 300:
        pmid = None
        try:
            pmid = str(resp.json().get("result", {}).get("message_id"))
        except Exception:  # noqa: BLE001
            pmid = None
        return SendResult(ok=True, http_status=resp.status_code, provider_message_id=pmid)
    return SendResult(ok=False, http_status=resp.status_code, error_class=f"http_{resp.status_code}")


def _timeout():
    return httpx.Timeout(R.TOTAL_TIMEOUT, connect=R.CONNECT_TIMEOUT)


def _from_resp(resp, pmid_key: str | None) -> SendResult:
    if 200 <= resp.status_code < 300:
        pmid = None
        if pmid_key:
            try:
                pmid = str(resp.json().get(pmid_key))
            except Exception:  # noqa: BLE001
                pmid = None
        return SendResult(ok=True, http_status=resp.status_code, provider_message_id=pmid)
    return SendResult(ok=False, http_status=resp.status_code, error_class=f"http_{resp.status_code}")


async def _messenger_send(payload: dict) -> SendResult:
    """CR-03: customer receipt qua Messenger Send API (durable)."""
    if not settings.page_access_token:
        return SendResult(ok=False, http_status=403, error_class="not_configured")
    try:
        async with httpx.AsyncClient(timeout=_timeout()) as client:
            resp = await client.post(
                GRAPH_URL, params={"access_token": settings.page_access_token},
                json={"recipient": {"id": payload.get("customer_ref")},
                      "messaging_type": "RESPONSE", "message": {"text": payload.get("text", "")}})
    except httpx.TimeoutException:
        return SendResult(ok=False, is_timeout=True, error_class="timeout")
    except httpx.HTTPError as e:  # noqa: BLE001
        return SendResult(ok=False, error_class=type(e).__name__)
    return _from_resp(resp, "message_id")


async def _telegram_customer_send(payload: dict) -> SendResult:
    """CR-03: customer receipt qua bot Telegram khách (durable)."""
    if not settings.telegram_customer_bot_token:
        return SendResult(ok=False, http_status=403, error_class="not_configured")
    ref = str(payload.get("customer_ref") or "")
    chat_id = ref[3:] if ref.startswith("tg:") else ref
    url = f"https://api.telegram.org/bot{settings.telegram_customer_bot_token}/sendMessage"
    # M7 (272 §3.3): payload co qr_payload -> tai tao PNG TAT DINH tu snapshot luc dispatch va gui sendPhoto
    # (caption = text). Thieu lib/render loi -> fallback sendMessage text (instruction text da du thong tin).
    png = None
    if payload.get("qr_payload"):
        try:
            from app.services.payment import vietqr as _vq
            png = _vq.png_bytes(str(payload["qr_payload"]))
        except Exception:  # noqa: BLE001
            png = None
    try:
        async with httpx.AsyncClient(timeout=_timeout()) as client:
            if png:
                purl = f"https://api.telegram.org/bot{settings.telegram_customer_bot_token}/sendPhoto"
                resp = await client.post(purl, data={"chat_id": chat_id, "caption": payload.get("text", "")[:1024]},
                                         files={"photo": ("vietqr.png", png, "image/png")})
            else:
                resp = await client.post(url, json={"chat_id": chat_id, "text": payload.get("text", "")})
    except httpx.TimeoutException:
        return SendResult(ok=False, is_timeout=True, error_class="timeout")
    except httpx.HTTPError as e:  # noqa: BLE001
        return SendResult(ok=False, error_class=type(e).__name__)
    if 200 <= resp.status_code < 300:
        pmid = None
        try:
            pmid = str(resp.json().get("result", {}).get("message_id"))
        except Exception:  # noqa: BLE001
            pmid = None
        return SendResult(ok=True, http_status=resp.status_code, provider_message_id=pmid)
    return SendResult(ok=False, http_status=resp.status_code, error_class=f"http_{resp.status_code}")


async def deliver(destination: str, payload: dict) -> SendResult:
    """Dispatch theo destination -> sender phù hợp (telegram_admin / messenger / telegram_customer).
    M3-S5: payload dạng dispatcher (marker 'outbound.message') -> đi qua permission/template trước."""
    if payload.get("dispatch") == "outbound.message":
        from app.services.command import dispatcher  # lazy: tránh vòng import
        return await dispatcher.deliver_outbound(destination, payload)
    if destination == OUTBOX_DEST_TELEGRAM_ADMIN:
        return await telegram_send(destination, payload)
    if destination == OUTBOX_DEST_MESSENGER:
        return await _messenger_send(payload)
    if destination == OUTBOX_DEST_TELEGRAM_CUSTOMER:
        return await _telegram_customer_send(payload)
    return SendResult(ok=False, http_status=400, error_class="unknown_destination")


# --------------------------------------------------------------------------
# Core drain
# --------------------------------------------------------------------------

def _rowcount(status: str) -> int:
    try:
        return int(status.split()[-1])
    except Exception:  # noqa: BLE001
        return 0


async def reclaim_stale(conn) -> int:
    """'delivering' voi lease het han (worker crash) -> retry_scheduled, available now (§8.2)."""
    res = await conn.execute(
        "UPDATE outbox_events SET status='retry_scheduled', available_at=now(), "
        "lease_owner=NULL, lease_expires_at=NULL "
        "WHERE status='delivering' AND lease_expires_at IS NOT NULL AND lease_expires_at < now()"
    )
    return _rowcount(res)


def _classify(sr: SendResult) -> tuple[str, str]:
    """-> (attempt_outcome, decision) voi decision in {delivered, retry, terminal}."""
    if sr.ok:
        return "delivered", "delivered"
    if sr.is_timeout:
        return "unknown", "retry"  # §8.2 timeout=unknown -> retry theo policy
    if sr.http_status is not None:
        outcome, _cred = R.classify_http(sr.http_status)
        if outcome == R.RETRYABLE:
            return "retryable_error", "retry"
        if outcome == R.TERMINAL:
            return "terminal_error", "terminal"
        return "delivered", "delivered"
    return "retryable_error", "retry"  # network error khong status -> retryable


async def _is_stale(conn, sc: dict) -> bool:
    """CA 268-01: stale theo SEMANTIC STATE, KHONG theo aggregate version.
    Notify mo ta 1 status muc tieu (to_status/new_status). Truoc khi gui, doi chieu status hien tai:
    - status hien tai == status notify mo ta -> notify VAN DUNG (du version cao hon do sua carrier/tracking/
      metadata) -> GUI.
    - status hien tai da chuyen sang trang thai lam noi dung SAI -> huy (cancelled).
    Re-dispatch transition moi co dedupe_key rieng (order:version) nen van 1 event/transition; retry cung outbox
    event van effective-once. Fail-open (gui) khi thieu du lieu de khong chan nham notify hop le."""
    if not sc:
        return False
    kind, order_id = sc.get("kind"), sc.get("order_id")
    try:
        # CA Directive 387: don da huy -> moi notify M6/M7 (giao hang/thanh toan/hoi thoai) cua don do la lac hau.
        if kind in ("shipment", "payment", "fulfillment") and order_id is not None and await conn.fetchval(
                "SELECT status IN ('cancelled','cancelled_by_exception') FROM orders WHERE id=$1", order_id):
            return True
        if kind == "shipment":
            expected = sc.get("to_status")
            cur = await conn.fetchval("SELECT status FROM shipments WHERE order_id=$1", order_id)
        elif kind == "payment":
            cur = await conn.fetchval("SELECT status FROM payments WHERE order_id=$1", order_id)
            # CA Review 294-01: notify co the hop le cho NHIEU status ke tiep (vd COD confirmation dung ca 'collected'
            # lan successor 'reconciled') -> allowed_statuses (semantic ro rang) thay vi exact-match. Fallback exact
            # new_status cho cac payment notify khac (check_request/BANK confirmed) — KHONG noi long chung.
            allowed = sc.get("allowed_statuses")
            if allowed:
                return cur is not None and cur not in allowed
            expected = sc.get("new_status")
        elif kind == "fulfillment":
            # M7: prompt/cod notify mo ta 1 step hoi thoai; step da doi (khach chon xong / staff) -> stale.
            expected = sc.get("step")
            cur = await conn.fetchval("SELECT step FROM fulfillment_conversations WHERE order_id=$1", order_id)
        else:
            return False
    except Exception:  # noqa: BLE001
        return False
    if expected is None or cur is None:
        return False
    return cur != expected


async def _refresh_dynamic_text(conn, payload: dict, sc: dict) -> None:
    """CA 268-01 ('chi gui phan khong stale'): handover mang carrier/tracking/eta -> re-render tu state HIEN TAI
    luc dispatch de khong gui snapshot cu neu carrier/tracking bi sua sau khi enqueue."""
    if sc.get("kind") != "shipment" or sc.get("to_status") != "in_transit":
        return
    try:
        row = await conn.fetchrow("SELECT carrier, tracking_text, eta_text FROM shipments WHERE order_id=$1",
                                  sc.get("order_id"))
        if row is None:
            return
        from app.services.fulfillment import notify as _n
        payload["text"] = _n.handover_text(sc.get("order_id"), carrier=row["carrier"],
                                           tracking_text=row["tracking_text"], eta_text=row["eta_text"])
    except Exception:  # noqa: BLE001
        return  # giu text cu neu refresh loi (khong chan gui)


async def _send_and_record(conn, ev, send_fn) -> str:
    payload = ev["payload"]
    if isinstance(payload, str):
        payload = json.loads(payload)
    # CA 268-01: bo qua thong bao M6 lac hau theo SEMANTIC STATE (status doi lam noi dung sai) -> cancelled.
    sc = payload.get("stale_check") if isinstance(payload, dict) else None
    if sc and await _is_stale(conn, sc):
        await conn.execute(
            "UPDATE outbox_events SET status='cancelled', cancelled_at=now(), last_error_code='superseded_stale', "
            "lease_owner=NULL, lease_expires_at=NULL WHERE id=$1 AND status='delivering' AND lease_owner=$2",
            ev["id"], WORKER_ID)
        return "cancelled"
    # CA 268-01: re-render carrier/tracking/eta cua handover tu state hien tai (khong gui snapshot cu).
    if sc:
        await _refresh_dynamic_text(conn, payload, sc)
    attempt_no = ev["attempt_count"]
    corr = payload.get("correlation_id")
    if corr is None and ev.get("command_id") is not None:
        corr = await conn.fetchval("SELECT correlation_id FROM command_executions WHERE id=$1",
                                   ev["command_id"])
    if corr is None:
        # CA 253-01.3: event khong command-backed (escalation) va payload thieu correlation_id ->
        # fallback UUID (delivery_attempts.correlation_id NOT NULL) — worker KHONG duoc crash.
        corr = str(uuid.uuid4())

    t0 = time.monotonic()
    sr = await send_fn(ev["destination"], payload)
    dur_ms = int((time.monotonic() - t0) * 1000)

    attempt_outcome, decision = _classify(sr)
    # Retry ceiling theo max_attempts CUA EVENT (khong phai default global).
    if decision == "retry" and attempt_no >= ev["max_attempts"]:
        decision = "terminal"  # het max attempts -> dead-letter

    # append delivery_attempts (§7.3)
    await conn.execute(
        "INSERT INTO delivery_attempts (outbox_event_id, attempt_no, worker_id, started_at, "
        "finished_at, outcome, http_status, provider_message_id, error_class, duration_ms, "
        "correlation_id) VALUES ($1,$2,$3, now() - ($10 * interval '1 millisecond'), now(), "
        "$4,$5,$6,$7,$8,$9)",
        ev["id"], attempt_no, WORKER_ID, attempt_outcome, sr.http_status,
        sr.provider_message_id, sr.error_class, dur_ms, corr, dur_ms,
    )

    # CR-02: compare-and-set — chỉ ghi trạng thái cuối khi event VẪN 'delivering' và VẪN thuộc lease
    # của worker này. Nếu event đã bị cancel/reclaim trong lúc gửi -> UPDATE 0 dòng, KHÔNG đè.
    if decision == "delivered":
        await conn.execute(
            "UPDATE outbox_events SET status='delivered', delivered_at=now(), "
            "provider_message_id=$2, lease_owner=NULL, lease_expires_at=NULL "
            "WHERE id=$1 AND status='delivering' AND lease_owner=$3",
            ev["id"], sr.provider_message_id, WORKER_ID,
        )
        # CA 396 §2.1: tin da thuc su toi khach -> ghi lich su. Ghi ca khi CAS 0 dong (event bi reclaim trong luc
        # gui nhung tin DA di): dedupe outbox:<id> dam bao retry/redeliver khong ghi trung.
        try:
            await persist_customer_history(conn, ev["id"], ev.get("event_type"), ev["destination"], payload)
        except Exception as e:  # noqa: BLE001 — lich su khong duoc chan delivery
            print(f"[outbox_worker] history persist skipped: {safe_exc(e)}")
        return "delivered"
    if decision == "retry":
        backoff = R.backoff_seconds(attempt_no)
        await conn.execute(
            "UPDATE outbox_events SET status='retry_scheduled', "
            "available_at=now() + ($2 * interval '1 second'), last_error_code=$3, "
            "lease_owner=NULL, lease_expires_at=NULL "
            "WHERE id=$1 AND status='delivering' AND lease_owner=$4",
            ev["id"], backoff, sr.error_class, WORKER_ID,
        )
        return "retried"
    # terminal -> dead-letter (§9.2)
    await conn.execute(
        "UPDATE outbox_events SET status='dead_lettered', dead_lettered_at=now(), "
        "last_error_code=$2, lease_owner=NULL, lease_expires_at=NULL "
        "WHERE id=$1 AND status='delivering' AND lease_owner=$3",
        ev["id"], sr.error_class, WORKER_ID,
    )
    return "dead"


async def run_once(send_fn=None) -> dict:
    """Mot vong drain: reclaim stale -> claim batch -> send+record tung event. Tra stats."""
    send_fn = send_fn or deliver
    conn = await acquire()
    stats = {"reclaimed": 0, "delivered": 0, "retried": 0, "dead": 0, "claimed": 0, "cancelled": 0}
    try:
        stats["reclaimed"] = await reclaim_stale(conn)
        events = await conn.fetch(_CLAIM_SQL, BATCH, WORKER_ID, LEASE_SECONDS)
        stats["claimed"] = len(events)
        for ev in events:
            outcome = await _send_and_record(conn, ev, send_fn)
            stats[outcome] += 1
    finally:
        await release(conn)
    # CA 235-03: moi vong worker cung ghi bu staff-history receipt row con thieu (idempotent, durable retry).
    try:
        from app.services.command import staff_receipt_reconcile
        stats["staff_receipt_reconciled"] = await staff_receipt_reconcile.reconcile_staff_receipts()
    except Exception as e:  # noqa: BLE001
        print(f"[outbox_worker] staff receipt reconcile skipped: {safe_exc(e)}")
    return stats
