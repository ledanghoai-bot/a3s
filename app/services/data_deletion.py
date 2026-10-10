"""Xu ly xoa du lieu khach theo yeu cau Meta (Data Deletion Callback).

Luong Meta: khi khach go app khoi Facebook, Meta POST toi callback URL kem
`signed_request` (base64url, ky HMAC-SHA256 bang APP SECRET). App phai:
  1. Xac thuc chu ky -> lay `user_id` (chinh la PSID).
  2. Khoi tao xoa du lieu cua PSID do.
  3. Tra JSON {url, confirmation_code} de Meta hien cho khach tra trang thai.

Chinh sach xoa (khop trang /privacy):
  - XOA HAN noi dung hoi thoai: messages + escalations + conversations.
  - AN DANH don hang: bo shipping_name/phone/address (giu don + item cho nghia
    vu ke toan, dung cam ket "phan bat buoc luu se duoc an danh").
  - AN DANH customer: bo name/phone/address, doi CA psid LAN external_chat_id ->
    'deleted:<code>' (CA Directive 405 §2.1) de cat lien ket voi PSID/ChatID that
    (giu lai dong de khoa ngoai orders con hop le) va de cung ChatID nhan lai tao
    duoc customer moi (khong vuong uq_customers_channel_chat).
  - Kho van hanh con giu dinh danh (CA 405 §2.4): command_executions (actor/scope/
    ten), order_intents (draft ten/SDT/dia chi), outbox_events (customer_ref/ten/
    dia chi/tin gan nhat; tin chua gui toi khach -> huy), fulfillment_conversations
    (customer_ref) -> tombstone/bo truong PII trong CUNG transaction.
  - XOA cache Redis: chat/profile/nlu_state/del_pending/addr_clarify:<psid> + loc
    raw event cua khach khoi dead_letter:messages.

Khoa ngoai KHONG co ON DELETE CASCADE -> phai xoa dung thu tu (con truoc cha);
command_executions/order_intents tro toi conversations -> go lien ket truoc khi xoa.
"""

import asyncio
import base64
import hashlib
import hmac
import json
import secrets
import unicodedata

import redis.asyncio as aioredis

from app.config import settings
from app.db_pool import get_pool
from app.services.customer_identity import tombstone
from app.services.safe_log import mask_ref, safe_exc

# Domain cong khai (khop {$DOMAIN} trong Caddy) - dung dung URL trang thai tra ve
# cho Meta. Request tu Meta di qua Caddy nen request.url la noi bo (api:8000),
# khong dung de tao URL cong khai.
PUBLIC_BASE_URL = "https://a3s.robanme.com"


def _b64url_decode(data: str) -> bytes:
    """Giai base64url (them padding neu thieu)."""
    data += "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data)


def parse_signed_request(signed_request: str, app_secret: str) -> dict | None:
    """Xac thuc + giai `signed_request` cua Meta. Tra ve payload dict neu chu ky
    hop le, None neu sai/khong parse duoc. So sanh chu ky bang compare_digest."""
    if not signed_request or "." not in signed_request:
        return None
    try:
        encoded_sig, payload = signed_request.split(".", 1)
        sig = _b64url_decode(encoded_sig)
        data = json.loads(_b64url_decode(payload))
    except (ValueError, json.JSONDecodeError):
        return None

    if str(data.get("algorithm", "")).upper() != "HMAC-SHA256":
        return None

    expected = hmac.new(app_secret.encode(), payload.encode(), hashlib.sha256).digest()
    if not hmac.compare_digest(sig, expected):
        return None
    return data


async def _record_request(confirmation_code: str, status: str, subject_hmac: str | None = None) -> None:
    """subject_hmac CHI ghi khi status='redis_pending' (de retry tim lai key Redis); moi status khac -> NULL."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO data_deletion_requests (confirmation_code, status, completed_at, subject_hmac)
            VALUES ($1, $2, CASE WHEN $2 = 'completed' THEN now() ELSE NULL END,
                    CASE WHEN $2 = 'redis_pending' THEN $3 ELSE NULL END)
            ON CONFLICT (confirmation_code)
            DO UPDATE SET status = EXCLUDED.status, completed_at = EXCLUDED.completed_at,
                          subject_hmac = EXCLUDED.subject_hmac
            """,
            confirmation_code,
            status,
            subject_hmac,
        )


def subject_hmac(ref: str) -> str:
    """CA 415 §3.5: dinh danh GIA DANH (HMAC khoa server) cua psid — chi de ghep lai request redis_pending voi key Redis
    cua chinh khach do, KHONG dao nguoc duoc neu khong co khoa. Khong bao gio luu psid tho."""
    key = hashlib.sha256(("a3s-dsr-v1|" + (settings.meta_app_secret or "")).encode()).digest()
    return hmac.new(key, ref.encode(), hashlib.sha256).hexdigest()


async def get_status(confirmation_code: str) -> dict | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT confirmation_code, status, requested_at, completed_at "
            "FROM data_deletion_requests WHERE confirmation_code = $1",
            confirmation_code,
        )
        return dict(row) if row else None


def _tag_count(command_tag: str) -> int:
    """asyncpg execute() tra ve command tag kieu 'DELETE 3' / 'UPDATE 2' -> so cuoi."""
    try:
        return int(command_tag.split()[-1])
    except (ValueError, IndexError, AttributeError):
        return 0


# Intent con mo (khop index oi_one_open_per_conversation, migration 058) -> huy khi khach xoa du lieu.
_OPEN_INTENT_STATES = ["COLLECTING", "ADDRESS_CHECK", "NEEDS_CLARIFICATION", "READY_TO_COMMIT", "COMMITTING",
                       "RETRYING"]
# Truong PII trong payload outbox (order.created / order.escalated / handoff.escalated / dispatcher params).
_OUTBOX_PII_KEYS = ["customer_name", "address", "last_message"]
_DEAD_LETTER_KEY = "dead_letter:messages"  # = app.workers.tasks.DEAD_LETTER_KEY (khong import worker vao service)


async def _scrub_operational_stores(conn, *, cid: int, psid: str, tomb: str, conv_ids: list[int],
                                    order_ids: list[int], summary: dict) -> None:
    """CA 405 §2.4: tach dinh danh khoi kho van hanh mutable — CHAY TRUOC khi xoa conversations (go FK
    command_executions/order_intents -> conversations, neu khong ca transaction rollback)."""
    conv_txt = [str(c) for c in conv_ids]
    order_txt = [str(o) for o in order_ids]
    intent_txt = [str(r["id"]) for r in await conn.fetch(
        "SELECT id FROM order_intents WHERE customer_id = $1", cid)]
    # Outbox: tin CHUA gui toi chinh khach -> huy (khong gui cho nguoi da xoa); recovery chi replay dead_lettered.
    r = await conn.execute(
        "UPDATE outbox_events SET status = 'cancelled', cancelled_at = now(), last_error_code = 'data_deletion', "
        "lease_owner = NULL, lease_expires_at = NULL "
        "WHERE payload->>'customer_ref' = $1 AND status IN ('pending', 'retry_scheduled', 'dead_lettered')",
        psid)
    summary["outbox_cancelled"] = _tag_count(r)
    # Tin toi khach (moi trang thai): ref -> tombstone, bo noi dung tin/params (co the chua ten/dia chi).
    r = await conn.execute(
        "UPDATE outbox_events SET payload = (payload - 'text' - 'params' - $2::text[]) "
        "|| jsonb_build_object('customer_ref', $3::text) WHERE payload->>'customer_ref' = $1",
        psid, _OUTBOX_PII_KEYS, tomb)
    scrubbed = _tag_count(r)
    # Thong bao staff gan voi khach (lenh/don/hoi thoai/intent cua khach): giu de van hanh, bo ten/dia chi/tin.
    r = await conn.execute(
        "UPDATE outbox_events SET payload = payload - $1::text[] "
        "WHERE payload ?| $1::text[] AND ("
        "  command_id IN (SELECT id FROM command_executions WHERE customer_id = $2)"
        "  OR payload->>'customer_id' = $6"
        "  OR payload->>'conversation_id' = ANY($3::text[])"
        "  OR payload->>'order_id' = ANY($4::text[])"
        "  OR payload->>'intent_id' = ANY($5::text[]))",
        _OUTBOX_PII_KEYS, cid, conv_txt, order_txt, intent_txt, str(cid))
    summary["outbox_scrubbed"] = scrubbed + _tag_count(r)
    # Command bus: actor/scope/causation = psid that -> tombstone; bo ten (request_payload allowlist); go FK.
    r = await conn.execute(
        "UPDATE command_executions SET conversation_id = NULL, "
        "actor_id = CASE WHEN actor_id = $2 THEN $3 ELSE actor_id END, "
        "causation_id = CASE WHEN causation_id = $2 THEN $3 ELSE causation_id END, "
        "idempotency_scope = CASE WHEN right(idempotency_scope, length($2) + 1) = ':' || $2 "
        "  THEN left(idempotency_scope, length(idempotency_scope) - length($2)) || $3 ELSE idempotency_scope END, "
        "request_payload = request_payload - 'customer_name' - 'phone_masked' - 'psid' "
        "WHERE customer_id = $1 OR conversation_id = ANY($4::bigint[])",
        cid, psid, tomb, conv_ids)
    summary["commands_scrubbed"] = _tag_count(r)
    # Order intent: bo draft ten/SDT/dia chi + go FK; intent con mo -> CANCELLED (identity cu khong con).
    r = await conn.execute(
        "UPDATE order_intents SET conversation_id = NULL, draft_customer_name = NULL, draft_phone = NULL, "
        "draft_address = NULL, "
        "terminal_reason = CASE WHEN state = ANY($2::text[]) THEN 'data_deletion' ELSE terminal_reason END, "
        "state_version = CASE WHEN state = ANY($2::text[]) THEN state_version + 1 ELSE state_version END, "
        "state = CASE WHEN state = ANY($2::text[]) THEN 'CANCELLED' ELSE state END "
        "WHERE customer_id = $1 OR conversation_id = ANY($3::bigint[])",
        cid, _OPEN_INTENT_STATES, conv_ids)
    summary["order_intents_scrubbed"] = _tag_count(r)
    # M7 hoi thoai fulfillment: customer_ref -> tombstone (worker nhac/deadline khong con gui toi ChatID that).
    r = await conn.execute(
        "UPDATE fulfillment_conversations SET customer_ref = $2, updated_at = now() "
        "WHERE customer_ref = $1 OR order_id = ANY($3::bigint[])",
        psid, tomb, order_ids)
    summary["fulfillment_refs_tombstoned"] = _tag_count(r)


async def _clear_redis(psid: str, summary: dict) -> None:
    redis = await aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        deleted = await redis.delete(f"chat:{psid}", f"profile:{psid}")
        summary["profile_cache_cleared"] = bool(deleted)
        extra = [f"nlu_state:{psid}", f"del_pending:{psid}"]
        async for k in redis.scan_iter(match=f"addr_clarify:{psid}:*", count=200):
            extra.append(k)
        summary["redis_keys_deleted"] = deleted + await redis.delete(*extra)
        # dead-letter giu raw webhook event (sender/recipient + text) -> bo dung cac event cua khach nay.
        removed = 0
        for raw in await redis.lrange(_DEAD_LETTER_KEY, 0, -1):
            try:
                ev = (json.loads(raw) or {}).get("event") or {}
            except (ValueError, AttributeError):
                continue
            ids = {(ev.get("sender") or {}).get("id"), (ev.get("recipient") or {}).get("id")}
            if psid in ids:
                removed += await redis.lrem(_DEAD_LETTER_KEY, 0, raw)
        summary["dead_letters_removed"] = removed
    finally:
        await redis.aclose()


async def _collect_pii(conn, cid: int) -> list[str]:
    """Ten/SDT/dia chi cua khach o ho so + nguoi nhan cac don + draft intent (ca bien the SDT chi chu so)."""
    rows = await conn.fetch(
        "SELECT name AS a, phone AS b, address AS c FROM customers WHERE id = $1 "
        "UNION ALL SELECT shipping_name, shipping_phone, shipping_address FROM orders WHERE customer_id = $1 "
        "UNION ALL SELECT draft_customer_name, draft_phone, draft_address FROM order_intents WHERE customer_id = $1",
        cid)
    vals: list[str] = []
    for r in rows:
        for v in (r["a"], r["b"], r["c"]):
            if isinstance(v, str) and v.strip():
                vals.append(v.strip())
        if isinstance(r["b"], str):
            digits = "".join(ch for ch in r["b"] if ch.isdigit())
            if digits:
                vals.append(digits)
    return [v for v in dict.fromkeys(vals) if len(v) >= 5]


_REDIS_ATTEMPTS = 3
_REDIS_KEY_PREFIXES = ("chat:", "profile:", "nlu_state:", "del_pending:", "addr_clarify:")


async def _clear_redis_with_retry(psid: str, summary: dict) -> bool:
    for attempt in range(1, _REDIS_ATTEMPTS + 1):
        try:
            await _clear_redis(psid, summary)
            return True
        except Exception as e:  # noqa: BLE001 - DB da commit; Redis loi -> thu lai roi chuyen redis_pending
            print(f"[data_deletion] Redis cleanup loi lan {attempt}/{_REDIS_ATTEMPTS} "
                  f"psid={mask_ref(psid)}: {safe_exc(e)}")
            if attempt < _REDIS_ATTEMPTS:
                await asyncio.sleep(0.2 * attempt)
    return False


async def _complete_redis_pending(conn, hmacs: list[str] | None, by: str) -> int:
    """Danh dau request redis_pending (cua cac subject_hmac nay, hoac TAT CA khi hmacs=None) da xong Redis."""
    r = await conn.execute(
        "UPDATE data_deletion_requests SET status = 'completed', completed_at = now(), subject_hmac = NULL, "
        "detail = coalesce(detail, '{}'::jsonb) || jsonb_build_object('redis_completed_by', $2::text) "
        "WHERE status = 'redis_pending' AND ($1::text[] IS NULL OR subject_hmac = ANY($1::text[]))", hmacs, by)
    return _tag_count(r)


def _ref_of_key(key: str) -> str | None:
    for p in _REDIS_KEY_PREFIXES:
        if key.startswith(p):
            rest = key[len(p):]
            if p == "addr_clarify:":  # addr_clarify:<sender_id>:<fp> (sender_id co the chua ':' — 'tg:<id>')
                rest = rest.rsplit(":", 1)[0] if ":" in rest else ""
            return rest or None
    return None


async def retry_redis_pending() -> dict:
    """Worker (cron): hoan tat Redis cleanup cho request 'redis_pending' (DB da xoa, customer da tombstone) MA KHONG can
    psid tho — quet key Redis/dead-letter, ghep theo subject_hmac. Quet tron 1 luot thanh cong -> moi key cua cac khach
    dang cho da bi xoa (hoac khong con) -> danh dau completed. Redis van loi -> giu redis_pending, luot sau thu lai."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT subject_hmac FROM data_deletion_requests "
                                "WHERE status = 'redis_pending' AND subject_hmac IS NOT NULL")
    targets = {r["subject_hmac"] for r in rows}
    if not targets:
        return {"pending": 0}
    stats = {"pending": len(targets), "keys_deleted": 0, "dead_letters_removed": 0}
    redis = await aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        for p in _REDIS_KEY_PREFIXES:
            async for k in redis.scan_iter(match=f"{p}*", count=500):
                ref = _ref_of_key(k)
                if ref and subject_hmac(ref) in targets:
                    stats["keys_deleted"] += await redis.delete(k)
        for raw in await redis.lrange(_DEAD_LETTER_KEY, 0, -1):
            try:
                ev = (json.loads(raw) or {}).get("event") or {}
            except (ValueError, AttributeError):
                continue
            ids = {(ev.get("sender") or {}).get("id"), (ev.get("recipient") or {}).get("id")}
            if any(i and subject_hmac(str(i)) in targets for i in ids):
                stats["dead_letters_removed"] += await redis.lrem(_DEAD_LETTER_KEY, 0, raw)
    finally:
        await redis.aclose()
    async with pool.acquire() as conn:
        stats["completed"] = await _complete_redis_pending(conn, sorted(targets), "worker")
    return stats


async def _delete_customer_data(psid: str, confirmation_code: str) -> dict:
    """Xoa/an danh toan bo du lieu cua 1 psid trong 1 transaction (Postgres) +
    xoa cache Redis. Idempotent: khong co customer thi la no-op. Tra ve summary
    (dem da xoa gi) de bao lai cho khach khi tu xoa qua chat."""
    summary = {
        "customer_found": False,
        "messages_deleted": 0,
        "conversations_deleted": 0,
        "escalations_deleted": 0,
        "orders_anonymized": 0,
        "m4_samples_deleted": 0,
        "outbox_cancelled": 0,
        "outbox_scrubbed": 0,
        "commands_scrubbed": 0,
        "order_intents_scrubbed": 0,
        "fulfillment_refs_tombstoned": 0,
        "profile_cache_cleared": False,
        "redis_keys_deleted": 0,
        "dead_letters_removed": 0,
    }
    tomb = tombstone(confirmation_code)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            # FOR UPDATE: 2 yeu cau xoa dong thoi cung psid -> yeu cau sau doi, doc lai thay psid da tombstone
            # -> no-op (idempotent, khong tombstone 2 lan).
            cust = await conn.fetchrow(
                "SELECT id, external_chat_id FROM customers WHERE psid = $1 FOR UPDATE", psid)
            if cust is not None:
                summary["customer_found"] = True
                cid = cust["id"]
                conv_ids = [r["id"] for r in await conn.fetch(
                    "SELECT id FROM conversations WHERE customer_id = $1", cid)]
                order_ids = [r["id"] for r in await conn.fetch(
                    "SELECT id FROM orders WHERE customer_id = $1", cid)]
                # Gia tri PII (ten/SDT/dia chi) TRUOC khi null — de ham DSR quet ca truong JSON/tu do o kho bat bien.
                pii = await _collect_pii(conn, cid)
                await _scrub_operational_stores(conn, cid=cid, psid=psid, tomb=tomb, conv_ids=conv_ids,
                                                order_ids=order_ids, summary=summary)
                # Con truoc: messages + escalations -> conversations
                r = await conn.execute(
                    "DELETE FROM messages WHERE conversation_id IN "
                    "(SELECT id FROM conversations WHERE customer_id = $1)",
                    cid,
                )
                summary["messages_deleted"] = _tag_count(r)
                r = await conn.execute(
                    "DELETE FROM escalations WHERE conversation_id IN "
                    "(SELECT id FROM conversations WHERE customer_id = $1)",
                    cid,
                )
                summary["escalations_deleted"] = _tag_count(r)
                r = await conn.execute("DELETE FROM conversations WHERE customer_id = $1", cid)
                summary["conversations_deleted"] = _tag_count(r)
                # I-B M4 Stage 0P (Deletion Propagation Map muc #17, migration 039): xoa sample
                # zone theo customer_ref (= customers.id::text) — LOC TRUC TIEP, KHONG JOIN sang
                # conversations/messages (da xoa o tren) nen KHONG orphan du chay truoc/sau buoc
                # nao. Vo dieu kien — DSR la tham quyen cuoi cung bat ke pending-check/race o
                # collector tra gi truoc do (F-M4-0P-02B). Guard to_regclass: migration 039 la
                # dev/test scope (CA Design Acceptance), CHUA ap dung production — thieu bang thi
                # bo qua, KHONG lam vo luong xoa du lieu chinh (backward-compat, dung pattern
                # audit_service.audit_exists()).
                if await conn.fetchval(
                    "SELECT to_regclass('public.m4_shadow_review_samples') IS NOT NULL"
                ):
                    r = await conn.execute(
                        "DELETE FROM m4_shadow_review_samples WHERE customer_ref = $1",
                        str(cid),
                    )
                    summary["m4_samples_deleted"] = _tag_count(r)
                # An danh don hang (giu lai cho ke toan, bo PII)
                r = await conn.execute(
                    "UPDATE orders SET shipping_name = NULL, shipping_phone = NULL, "
                    "shipping_address = NULL WHERE customer_id = $1",
                    cid,
                )
                summary["orders_anonymized"] = _tag_count(r)
                # An danh customer + cat lien ket PSID/ChatID that (CA 405 §2.1: psid VA external_chat_id cung
                # tombstone theo yeu cau -> giu NOT NULL + UNIQUE(channel, external_chat_id), ChatID cu tu do).
                await conn.execute(
                    "UPDATE customers SET name = NULL, phone = NULL, address = NULL, "
                    "current_address_resolution_id = NULL, psid = $2, external_chat_id = $2 WHERE id = $1",
                    cid,
                    tomb,
                )
                # CA 415 §3.2: kho bat bien/append-only (audit, so don/kho, dia chi, GHN snapshot, journal M7, payment/
                # provider events...) -> DUONG QUYEN HEP duy nhat: ham SECURITY DEFINER (migration 077) chi chay khi
                # customer DA tombstone trong CUNG transaction nay; tu ghi audit 'dsr.anonymize'. Loi -> rollback ca DSR.
                refs = [r for r in dict.fromkeys([psid, cust["external_chat_id"]]) if r]
                imm = await conn.fetchval("SELECT dsr_anonymize_identity($1, $2::text[], $3, $4, $5::text[])",
                                          cid, refs, tomb, confirmation_code, pii)
                summary["immutable_anonymized"] = json.loads(imm) if isinstance(imm, str) else imm
    return summary


async def process_deletion(psid: str) -> dict:
    """Sinh confirmation_code, chay xoa inline, ghi trang thai. Tra ve
    {confirmation_code, summary} (summary=None neu loi).

    Xoa chay inline (nhanh voi 1 khach) nen khi tra ve thi du lieu da xoa xong.
    Loi khi xoa DB -> danh dau 'failed' (transaction rollback, khong xoa gi) nhung VAN tra code.
    CA 415 §3.5: DB da commit nhung Redis loi (sau retry) -> 'redis_pending' + subject_hmac; lan goi lai cung psid
    (callback lap / khach nhan lai) hoac worker retry_redis_pending hoan tat Redis va chuyen 'completed'."""
    confirmation_code = secrets.token_hex(8)
    await _record_request(confirmation_code, "received")
    summary = None
    try:
        summary = await _delete_customer_data(psid, confirmation_code)
    except Exception as e:  # noqa: BLE001 - khong duoc lam vo response callback/chat
        print(f"[data_deletion] Loi xoa du lieu psid={mask_ref(psid)}: {safe_exc(e)}")
        await _record_request(confirmation_code, "failed")
        return {"confirmation_code": confirmation_code, "summary": None}
    redis_ok = await _clear_redis_with_retry(psid, summary)
    summary["redis_pending"] = not redis_ok
    if not redis_ok:
        await _record_request(confirmation_code, "redis_pending", subject_hmac(psid))
        return {"confirmation_code": confirmation_code, "summary": summary}
    await _record_request(confirmation_code, "completed")
    # Request truoc cua CUNG subject con redis_pending (DB da xoa) -> Redis vua don xong -> hoan tat luon.
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            summary["pending_completed"] = await _complete_redis_pending(conn, [subject_hmac(psid)], "repeat_request")
    except Exception as e:  # noqa: BLE001
        print(f"[data_deletion] Khong cap nhat duoc request redis_pending: {safe_exc(e)}")
    return {"confirmation_code": confirmation_code, "summary": summary}


# ---- Self-service qua chat: nhan dien keyword + bao cao cho khach ----
# Bo dau CA HAI phia khi so khop (bai hoc tieng Viet CLAUDE.md): khach co the go
# co dau ("XOA DU LIEU") hoac khong dau ("xoa du lieu").
def _strip_accents(s: str) -> str:
    s = s.lower().strip().replace("đ", "d")
    nfd = unicodedata.normalize("NFD", s)
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn")


def is_delete_request(text: str) -> bool:
    """Khach chu dong xin xoa du lieu (buoc 1 - chi hoi xac nhan, KHONG xoa)."""
    return "xoa du lieu" in _strip_accents(text)


def is_delete_confirm(text: str) -> bool:
    """Khach xac nhan xoa (buoc 2 - moi thuc su xoa). Kiem tra TRUOC is_delete_request
    vi 'xac nhan xoa du lieu' chua ca hai cum."""
    return "xac nhan xoa" in _strip_accents(text)


def confirm_prompt() -> str:
    """Cau hoi xac nhan o buoc 1."""
    return (
        "Dạ, anh/chị muốn xóa toàn bộ dữ liệu cá nhân của mình tại 3S Coffee phải không ạ?\n\n"
        "Việc này sẽ xóa: toàn bộ lịch sử trò chuyện, tên đã lưu, và thông tin cá nhân "
        "trong đơn hàng — và KHÔNG THỂ khôi phục.\n\n"
        "Nếu chắc chắn, anh/chị nhắn lại đúng cụm: XÁC NHẬN XÓA\n"
        "Nếu không muốn xóa nữa, anh/chị chỉ cần bỏ qua tin nhắn này ạ."
    )


def customer_deletion_report(result: dict) -> str:
    """Soan tin bao khach sau khi xoa (buoc 2), liet ke da xoa gi."""
    code = result.get("confirmation_code", "")
    s = result.get("summary")
    if s is None:
        return (
            "Dạ, em gặp trục trặc kỹ thuật khi xóa dữ liệu. Đội ngũ 3S Coffee sẽ kiểm tra và "
            f"xử lý yêu cầu của anh/chị ngay ạ. Mã tham chiếu: {code}."
        )
    if not s.get("customer_found"):
        return (
            "Dạ, hệ thống không tìm thấy dữ liệu cá nhân nào của anh/chị để xóa (có thể đã được "
            f"xóa trước đó). Mã tham chiếu: {code}."
        )
    lines = [
        "Dạ, em đã xóa dữ liệu của anh/chị xong ạ ✅",
        "",
        "Những gì đã được xóa:",
        f"- Toàn bộ lịch sử trò chuyện ({s.get('messages_deleted', 0)} tin nhắn)",
        "- Tên hồ sơ đã lưu và bộ nhớ tạm hội thoại",
    ]
    if s.get("orders_anonymized"):
        lines.append(
            f"- Thông tin cá nhân trong {s['orders_anonymized']} đơn hàng "
            "(đơn được giữ lại theo quy định kế toán nhưng đã ẩn tên, SĐT, địa chỉ)"
        )
    lines += [
        "",
        f"Mã xác nhận: {code}",
        f"Tra trạng thái: {status_url(code)}",
        "",
        "Dữ liệu đã xóa không thể khôi phục. Cảm ơn anh/chị đã tin tưởng 3S Coffee.",
    ]
    return "\n".join(lines)


def status_url(confirmation_code: str) -> str:
    return f"{PUBLIC_BASE_URL}/datadeletion/status?code={confirmation_code}"
