"""Worker arq: xu ly tin nhan bat dong bo sau khi webhook da tra 200.

Issue #9 (Bat 1): them dedupe theo `mid` (Meta co the gui trung webhook event)
va retry + dead-letter (khi Send API/LLM loi lien tuc).
"""

import json

from arq import cron
from arq.connections import RedisSettings

from app.config import settings
from app.services import conversation_log
from app.services.command import outbox_worker
from app.services.handoff import is_bot_paused
from app.services.messenger import send_text
from app.services.orchestrator import handle_message
from app.services.safe_log import safe_exc

DEDUP_TTL_SECONDS = 24 * 60 * 60  # 24h - du lon hon cua so retry cua Meta
DEAD_LETTER_KEY = "dead_letter:messages"


async def process_message(ctx: dict, event: dict) -> None:
    """Wrapper ben ngoai: dedupe + bat exception de ghi dead-letter o lan thu
    cuoi cung truoc khi de arq bao that bai that su (van raise lai, KHONG nuot
    loi - arq can biet job that bai de tinh dung so lan retry/metric)."""
    message = event.get("message") or {}
    mid = message.get("mid")
    if mid:
        redis = ctx["redis"]
        # SET ... NX EX: chi thanh cong (tra ve True) neu KEY CHUA TUNG TON TAI -
        # tuc la lan dau gap mid nay. Meta gui trung se bi chan ngay o day,
        # tranh tao 2 cau tra loi cho cung 1 tin nhan khach.
        is_first_time = await redis.set(f"dedup:mid:{mid}", "1", nx=True, ex=DEDUP_TTL_SECONDS)
        if not is_first_time:
            print(f"[worker] Bo qua tin nhan trung (mid={mid} da xu ly truoc do).")
            return

    try:
        await _process_message_inner(event)
    except Exception:
        job_try = ctx.get("job_try", 1)
        max_tries = ctx.get("max_tries", 3)
        if job_try >= max_tries:
            # Lan thu CUOI CUNG that bai - arq se KHONG retry them nua, ghi lai
            # "dead letter" de sau nay xem lai/xu ly tay, tranh mat tin nhan
            # am tham khong ai biet.
            redis = ctx["redis"]
            await redis.lpush(
                DEAD_LETTER_KEY,
                json.dumps({"event": event, "job_try": job_try}, ensure_ascii=False),
            )
            # M3-S4: dead-letter la Personal Data Zone (raw event giu de replay) -> TTL 7 ngay
            # (RET-07) + KHONG print raw event ra stdout (chi refs).
            await redis.expire(DEAD_LETTER_KEY, 7 * 24 * 3600)
            mid = ((event.get("message") or {}).get("mid") if isinstance(event, dict) else None)
            print(f"[worker] DEAD-LETTER sau {job_try} lan thu that bai, mid={mid}")
        raise


async def _process_message_inner(event: dict) -> None:
    message = event.get("message") or {}
    text = message.get("text")
    if not text:
        return  # bo qua su kien khong phai tin nhan van ban (delivery, read...)

    is_echo = message.get("is_echo", False)

    if is_echo:
        # Echo cua 1 tin nhan GUI DEN khach - trong echo, "sender" la chinh Page,
        # "recipient" moi la PSID khach that (nguoc voi tin nhan thuong).
        psid = (event.get("recipient") or {}).get("id")
        if not psid:
            return

        paused = await is_bot_paused(psid)
        if not paused:
            # Khong paused -> day la echo cua chinh bot vua tu gui qua send_text()
            # (da duoc orchestrator log roi voi role='bot'). Bo qua, tranh trung/loop.
            return

        # DANG paused ma van co echo -> bot chac chan KHONG tu gui gi trong luc
        # nay (worker return som, khong goi handle_message/send_text) => day
        # chinh la tin nhan THAT cua nhan vien/sep tu tay reply qua Messenger
        # Inbox. "Timetrap": chinh cai cua so bot_paused=TRUE la dieu kien loc,
        # khong can them cot timestamp rieng.
        conversation_id = await conversation_log.ensure_conversation(psid)
        await conversation_log.log_message(conversation_id, "agent", text)
        print(f"[worker] Da ghi tin nhan that cua nhan vien cho {psid} (luc dang paused).")
        return

    # Tin nhan thuong tu khach
    sender_id = (event.get("sender") or {}).get("id")
    if not sender_id:
        return

    # Human handoff (issue #7): hoi thoai dang bot_paused (nhan vien da tiep
    # quan qua escalate_to_human) -> bot im lang, KHONG tu dong tra loi chong
    # len nhan vien. NHUNG van ghi log tin khach de khong mat doan hoi thoai
    # trong dashboard (issue #8 - nang cap hien thi day du luc handover).
    if await is_bot_paused(sender_id):
        conversation_id = await conversation_log.ensure_conversation(sender_id)
        await conversation_log.log_message(conversation_id, "customer", text)
        print(f"[worker] Bot dang paused cho {sender_id}, chi log, khong tra loi (nhan vien dang xu ly).")
        return

    # CR-04: truyền provider message id (Messenger mid) thật vào command idempotency/causation.
    reply = await handle_message(sender_id, text, channel="messenger",
                                 provider_message_id=message.get("mid"))
    await send_text(sender_id, reply)


async def deliver_outbox_job(ctx) -> None:
    """I-B M1 (Slice 5): drain outbox_events dinh ky (at-least-once + retry/dead-letter).
    SKIP LOCKED -> nhieu worker an toan. Khi flag order command TAT, outbox rong -> no-op.
    Loi ben trong duoc bao ve, KHONG lam sap worker."""
    try:
        stats = await outbox_worker.run_once()
        if stats["claimed"] or stats["reclaimed"] or stats["dead"]:
            print(f"[outbox] drain {stats}")
    except Exception as e:  # noqa: BLE001 - drain loi khong duoc lam sap worker
        print(f"[outbox] drain loi (bo qua vong nay): {safe_exc(e)}")


async def expire_reservations_job(ctx) -> None:
    """I-B M2 (Slice 6): sweep reservation đến hạn mỗi 60s -> command reservation.expire (§11.2).
    Flag M2 TẮT -> no-op. Lỗi được bảo vệ, KHÔNG làm sập worker; reservation không bị bỏ quên."""
    try:
        from app.services.command import expiry_worker
        stats = await expiry_worker.run_once()
        if stats.get("claimed"):
            print(f"[expiry] sweep {stats}")
    except Exception as e:  # noqa: BLE001 - sweep loi khong duoc lam sap worker
        print(f"[expiry] sweep loi (bo qua vong nay): {safe_exc(e)}")


async def retention_job(ctx) -> None:
    """I-B M3 (Slice 6): retention executor chạy tường minh qua cron (KHÔNG giấu trong startup —
    Directive §6). Flag m3_retention_executor TẮT -> no-op (run_all_approved trả skipped).
    Chỉ apply policy status='approved'; audit vào retention_run_log (không PII)."""
    try:
        from app.db_pool import acquire, release
        from app.services import retention
        conn = await acquire()
        try:
            out = await retention.run_all_approved(conn, dry_run=False, actor="cron")
        finally:
            await release(conn)
        if out and out != [{"skipped": "flag_off"}]:
            print(f"[retention] run {out}")
    except Exception as e:  # noqa: BLE001 - retention loi khong duoc lam sap worker
        print(f"[retention] job loi (bo qua vong nay): {safe_exc(e)}")


async def signer_access_expiry_job(ctx) -> None:
    """Directive 91: auto-revoke worker — quet signer-access request ACTIVE qua window_end -> EXPIRED
    + revoke temp signer role + expire activation window. Chay moi 60s. Bang chua ton tai (pre-051)
    -> loi bat, no-op. Loi khong duoc lam sap worker; role het han khong bi bo quen (defensive sweep
    trong expire_due cung revoke moi grant qua valid_until)."""
    try:
        from app.services.m4_signing import signer_access
        n = await signer_access.expire_due(actor="cron")
        if n:
            print(f"[signer-access] expired {n} request(s) + revoked temp role")
    except Exception as e:  # noqa: BLE001 - sweep loi khong duoc lam sap worker
        # pre-051 (bang chua co) hoac loi tam -> bo qua vong nay
        print(f"[signer-access] expiry sweep bo qua vong nay: {safe_exc(e)}")


async def m4_signing_execute(ctx, payload: dict) -> dict:
    """M4-9: background execution cua signing run. Goi CLI adapter (run execute) roi chuyen state.

    Fail-closed: bat ky loi nao -> chuyen run sang FAILED (khong bao gio de treo o EXECUTING).
    CLEANUP_FAILED tu runner = danger -> FAILED + terminal_reason ro rang de alert rieng.
    """
    from app.services.m4_signing import cli_adapter, run_store
    run_id = payload["run_id"]
    try:
        result = await cli_adapter.run_execute(
            run_id,
            manifest=payload["manifest"],
            approval_ref=payload["approval_ref"],
            operator_staff_id=payload["operator_staff_id"],
            reviewer_staff_id=payload["reviewer_staff_id"],
        )
        if result.ok:
            await run_store.transition(run_id, "execute_success", actor_staff_id=None,
                                       reason="lifecycle success", detail=result.as_dict())
        else:
            reason = "CLEANUP_FAILED (nguy hiem)" if result.danger else "lifecycle failed"
            await run_store.transition(run_id, "execute_fail", actor_staff_id=None,
                                       reason=reason, detail=result.as_dict())
        return result.as_dict()
    except Exception as e:  # noqa: BLE001 - phai chuyen FAILED, khong de treo EXECUTING
        try:
            await run_store.transition(run_id, "execute_fail", actor_staff_id=None,
                                       reason=f"adapter loi: {safe_exc(e)}")
        except Exception:  # noqa: BLE001
            pass
        print(f"[m4-signing] execute loi run={run_id}: {safe_exc(e)}")
        raise


async def _on_shutdown(ctx) -> None:
    # Dong DB pool cua worker luc shutdown (I-B M0.2). Pool tao lazy trong event loop cua worker.
    from app.db_pool import close_pool
    await close_pool()


class WorkerSettings:
    functions = [process_message, m4_signing_execute]
    # I-B M1: cron drain outbox moi 10 giay (poller). Producer chi sinh event khi flag BAT.
    cron_jobs = [
        cron(deliver_outbox_job, second={0, 10, 20, 30, 40, 50}, run_at_startup=False),
        # I-B M2: sweep reservation het han moi 60s (dau moi phut). Flag M2 TAT -> no-op.
        cron(expire_reservations_job, second={0}, run_at_startup=False),
        # I-B M3-S6: retention executor 03:15 hang ngay. Flag m3_retention_executor TAT -> no-op.
        cron(retention_job, hour={3}, minute={15}, run_at_startup=False),
        # Directive 91: auto-revoke temp signer role + expire signer-access window moi 60s.
        cron(signer_access_expiry_job, second={0}, run_at_startup=False),
    ]
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    max_jobs = 20
    max_tries = 3  # issue #9 Bat 1: khai bao ro rang thay vi dua vao default cua arq
    on_shutdown = _on_shutdown
