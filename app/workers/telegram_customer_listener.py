"""Telegram bot cho KHACH HANG (khac han bot admin trong telegram_listener.py) -
kenh du phong khi Messenger bi gian doan (vd Meta khoa tai khoan test - xem
ISSUES.md). Dung TOKEN RIENG (TELEGRAM_CUSTOMER_BOT_TOKEN), KHONG dung chung
voi bot admin, vi bot nay phai tra loi BAT KY AI nhan tin toi (khac bot admin
chi xu ly dung 1 chat_id da cau hinh).

sender_id dua vao he thong dang "tg:<telegram_chat_id>" (co prefix) de KHONG
bao gio trung voi PSID Facebook that (PSID luon la chuoi so dai 15-17 chu so,
Telegram chat_id thuong ngan hon nhieu, nhung van prefix cho chac chan va de
phan biet nguon goc khi doc log/DB).

Dung LONG POLLING (khong can HTTPS public/domain - #9 deploy that chua xong),
y het cau truc voi telegram_listener.py.

Chay tay de test:
    python -m app.workers.telegram_customer_listener
"""

import asyncio
import random
import time

import httpx

from app.config import settings
from app.services import conversation_log
from app.services.handoff import is_bot_paused
from app.services.orchestrator import handle_message
from app.services.safe_log import safe_exc

API_BASE = "https://api.telegram.org"
POLL_TIMEOUT = 30

# CA Review 292-03: auto-recovery cho poll loop (backoff + jitter co gioi han + re-init client khi loi lien tiep).
_BACKOFF_BASE = 1.0            # giay
_BACKOFF_CAP = 60.0            # tran backoff
_JITTER = 0.25                 # +/- 25%
# So loi getUpdates lien tiep -> DONG client cu + tao client MOI (fresh pool) de thoat trang thai ket/pool poisoned.
_RECONNECT_AFTER_CONSEC_ERRORS = 3
# CA Review 298-03: heartbeat theo THOI GIAN (~60s), KHONG theo so poll — long-poll 30s nen 60 poll co the ~30 phut,
# qua cham de phat hien treo. Log dinh ky khi poller con poll de operator/supervisor thay song.
_HEARTBEAT_SECONDS = 60

# Heartbeat/liveness: phan biet "process con song" vs "poller THUC SU dang poll".
# _last_poll_ok_at = time.monotonic() cua lan getUpdates thanh cong gan nhat (None neu chua bao gio).
_last_poll_ok_at: float | None = None
_poll_started_at: float | None = None


def _backoff_delay(consec_errors: int) -> float:
    """Exponential backoff co tran + jitter. consec_errors >= 1. TAT DINH-ish (jitter ngau nhien) nhung bounded:
    delay = min(cap, base * 2^(n-1)) * (1 +/- jitter). Khong bao gio vuot cap*(1+jitter)."""
    n = max(1, int(consec_errors))
    raw = min(_BACKOFF_CAP, _BACKOFF_BASE * (2 ** (n - 1)))
    return raw * (1.0 + random.uniform(-_JITTER, _JITTER))


def _next_reconnect_count(prev: int, had_success: bool) -> int:
    """CA Review 298-01: neu phien vua roi TUNG poll thanh cong -> reset ve 1 (backoff base) cho reconnect ke tiep;
    neu chua tung poll OK (outage lien tuc) -> tang dan (backoff lon dan toi cap)."""
    return 1 if had_success else prev + 1


def poller_status(*, now: float | None = None, max_age_s: float = POLL_TIMEOUT * 3) -> dict:
    """Readiness cho liveness check: 'started' (loop da chay), 'last_ok_age_s' (giay tu lan poll OK cuoi),
    'healthy' (co poll OK trong max_age_s gan day). max_age_s mac dinh = 3 chu ky long-poll."""
    now = now if now is not None else time.monotonic()
    started = _poll_started_at is not None
    age = None if _last_poll_ok_at is None else (now - _last_poll_ok_at)
    healthy = started and age is not None and age <= max_age_s
    return {"started": started, "last_ok_age_s": age, "healthy": healthy}


def _configured() -> bool:
    return bool(settings.telegram_customer_bot_token)


async def _send_reply(client: httpx.AsyncClient, chat_id: int, text: str) -> None:
    url = f"{API_BASE}/bot{settings.telegram_customer_bot_token}/sendMessage"
    try:
        await client.post(url, json={"chat_id": chat_id, "text": text}, timeout=10.0)
    except Exception as e:
        print(f"[telegram_customer_listener] Gui tin nhan that bai: {safe_exc(e)}")


async def _handle_customer_message(client: httpx.AsyncClient, chat_id: int, text: str,
                                   message_id: int | None = None) -> None:
    sender_id = f"tg:{chat_id}"

    # Human handoff (issue #7/#8): dung y het logic worker Messenger
    # (app/workers/tasks.py) - neu dang bot_paused thi CHI log, khong tra loi,
    # tranh chong len nhan vien.
    if await is_bot_paused(sender_id):
        conversation_id = await conversation_log.ensure_conversation(sender_id)
        await conversation_log.log_message(conversation_id, "customer", text)
        print(f"[telegram_customer_listener] Bot dang paused cho {sender_id}, chi log.")
        return

    # channel='telegram_customer' (khớp CHANNELS của command envelope) + provider message id thật
    # (message_id Telegram) cho idempotency/causation — CR-04.
    reply = await handle_message(
        sender_id, text, channel="telegram_customer",
        provider_message_id=(f"tg:{message_id}" if message_id is not None else None))
    # CA 275-01: chi gui khi co reply THAT (non-empty string). None/rong = M7 SILENT (bot im lang) -> KHONG goi
    # Telegram API voi text=null.
    if isinstance(reply, str) and reply.strip():
        await _send_reply(client, chat_id, reply)


class _ReconnectSession(Exception):
    """CA Review 298-02: inner RAISE (khong sleep) khi can tao client moi; outer lifecycle SO HUU reconnect delay.
    Mang `had_success` de outer reset backoff neu phien nay tung poll thanh cong (CA 298-01)."""
    def __init__(self, had_success: bool):
        self.had_success = had_success


async def _run_session(client: httpx.AsyncClient, state: dict) -> None:
    """Mot phien voi 1 httpx client. Loi getUpdates lien tiep < nguong -> retry TRONG phien (cung client, backoff).
    >= nguong -> RAISE _ReconnectSession (KHONG sleep — outer so huu delay) de tao client moi (thoat pool poisoned/ket).
    offset giu qua cac phien (state). CancelledError (shutdown) propagate. Loi xu ly 1 message KHONG lam vo loop.
    Heartbeat theo THOI GIAN (~_HEARTBEAT_SECONDS) — CA 298-03."""
    global _last_poll_ok_at
    token = settings.telegram_customer_bot_token
    try:
        await client.post(f"{API_BASE}/bot{token}/deleteWebhook")
    except asyncio.CancelledError:
        raise
    except Exception as e:
        print(f"[telegram_customer_listener] deleteWebhook loi (bo qua): {safe_exc(e)}")

    print("[telegram_customer_listener] Da ket noi, bat dau long-polling (kenh khach hang)...")
    consec_errors = 0
    ok_count = 0
    had_success = False
    last_hb = time.monotonic()
    while True:
        try:
            params = {"timeout": POLL_TIMEOUT}
            if state.get("offset") is not None:
                params["offset"] = state["offset"]
            resp = await client.get(f"{API_BASE}/bot{token}/getUpdates", params=params)
            resp.raise_for_status()
            data = resp.json()
        except asyncio.CancelledError:
            raise                                  # shutdown -> propagate (client dong o async with)
        except Exception as e:
            consec_errors += 1
            if consec_errors >= _RECONNECT_AFTER_CONSEC_ERRORS:
                # CA 298-02: KHONG sleep o day — RAISE ngay, outer lifecycle so huu reconnect delay (1 tang duy nhat).
                print(f"[telegram_customer_listener] Loi getUpdates ({consec_errors}): {safe_exc(e)} -> tao ket noi moi")
                raise _ReconnectSession(had_success) from e
            delay = _backoff_delay(consec_errors)   # retry trong phien (cung client)
            print(f"[telegram_customer_listener] Loi getUpdates ({consec_errors}): {safe_exc(e)}, thu lai sau {delay:.1f}s")
            await asyncio.sleep(delay)
            continue

        # getUpdates OK -> reset backoff trong phien + cap nhat heartbeat + danh dau phien da poll thanh cong
        consec_errors = 0
        had_success = True
        _last_poll_ok_at = time.monotonic()
        ok_count += 1
        if (_last_poll_ok_at - last_hb) >= _HEARTBEAT_SECONDS:     # heartbeat theo thoi gian (~60s)
            last_hb = _last_poll_ok_at
            print(f"[telegram_customer_listener] heartbeat: dang poll (poll_ok={ok_count}, offset={state.get('offset')})")

        for update in data.get("result", []):
            state["offset"] = update["update_id"] + 1     # tien offset TRUOC khi xu ly (khong xu ly lai update loi)
            message = update.get("message") or {}
            chat_id = (message.get("chat") or {}).get("id")
            text = message.get("text")
            if not chat_id or not text:
                continue  # bo qua sticker/anh/lenh he thong khac
            try:
                await _handle_customer_message(client, chat_id, text, message.get("message_id"))
            except asyncio.CancelledError:
                raise
            except Exception as e:
                # loi xu ly 1 message KHONG duoc lam vo poll loop (offset da tien -> khong lap vo han)
                print(f"[telegram_customer_listener] Loi xu ly message (bo qua update nay): {safe_exc(e)}")


async def _poll_loop() -> None:
    """Outer lifecycle: moi vong tao 1 httpx client MOI; neu phien ket thuc bat thuong -> backoff roi tao lai.
    Client re-init giai quyet pool poisoned/ket sau loi mang/DNS tam thoi (CA Review 292-03)."""
    global _poll_started_at
    _poll_started_at = time.monotonic()
    state: dict = {"offset": None}      # offset ben vung qua cac phien
    reconnects = 0                      # so lan reconnect LIEN TIEP (khong co poll thanh cong o giua)
    while True:
        try:
            async with httpx.AsyncClient(timeout=POLL_TIMEOUT + 10) as client:
                await _run_session(client, state)
            # _run_session chi tra ve binh thuong khi bi cancel-free break (hien khong xay ra) -> reset an toan.
            reconnects = 0
        except asyncio.CancelledError:
            print("[telegram_customer_listener] Nhan cancel -> dung long-polling.")
            raise
        except _ReconnectSession as rs:
            # CA 298-01: RESET backoff neu phien vua roi TUNG poll thanh cong (outage cu khong con lam cham recovery
            # cua outage moi). CA 298-02: outer SO HUU reconnect delay (chi 1 tang sleep).
            reconnects = _next_reconnect_count(reconnects, rs.had_success)
            delay = _backoff_delay(reconnects)
            print(f"[telegram_customer_listener] Reconnect #{reconnects} (had_success={rs.had_success}) -> "
                  f"tao client moi sau {delay:.1f}s")
            await asyncio.sleep(delay)
        except Exception as e:
            reconnects += 1
            delay = _backoff_delay(reconnects)
            print(f"[telegram_customer_listener] Phien poll loi bat thuong ({reconnects}): {safe_exc(e)}, "
                  f"khoi dong lai sau {delay:.1f}s")
            await asyncio.sleep(delay)


async def main() -> None:
    if not _configured():
        print(
            "[telegram_customer_listener] Thieu TELEGRAM_CUSTOMER_BOT_TOKEN trong .env - "
            "khong khoi dong. Tao bot moi qua @BotFather (KHAC bot admin) roi cau hinh."
        )
        return
    await _poll_loop()


if __name__ == "__main__":
    asyncio.run(main())
