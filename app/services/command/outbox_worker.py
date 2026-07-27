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
from dataclasses import dataclass

import httpx

from app.config import settings
from app.db_pool import acquire, release
from app.services.command import retry as R
from app.services.command.receipt import format_vnd
from app.services.messenger import GRAPH_URL

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
RETURNING o.id, o.command_id, o.destination, o.dedupe_key, o.payload,
          o.attempt_count, o.max_attempts
"""


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
    return (
        "\U0001F6D2 3S Coffee - DON HANG MOI (M1)\n"
        f"Ma don: #{p.get('order_id')}\n"
        f"Khach: {p.get('customer_name') or '(chua co ten)'} - SDT {p.get('phone_masked') or '***'}\n"
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
    try:
        async with httpx.AsyncClient(timeout=_timeout()) as client:
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
    """Dispatch theo destination -> sender phù hợp (telegram_admin / messenger / telegram_customer)."""
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


async def _send_and_record(conn, ev, send_fn) -> str:
    payload = ev["payload"]
    if isinstance(payload, str):
        payload = json.loads(payload)
    attempt_no = ev["attempt_count"]
    corr = payload.get("correlation_id")
    if corr is None:
        corr = await conn.fetchval("SELECT correlation_id FROM command_executions WHERE id=$1",
                                   ev["command_id"])

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
    stats = {"reclaimed": 0, "delivered": 0, "retried": 0, "dead": 0, "claimed": 0}
    try:
        stats["reclaimed"] = await reclaim_stale(conn)
        events = await conn.fetch(_CLAIM_SQL, BATCH, WORKER_ID, LEASE_SECONDS)
        stats["claimed"] = len(events)
        for ev in events:
            outcome = await _send_and_record(conn, ev, send_fn)
            stats[outcome] += 1
    finally:
        await release(conn)
    return stats
