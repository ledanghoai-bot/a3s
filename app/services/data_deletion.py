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


async def _record_request(confirmation_code: str, status: str) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO data_deletion_requests (confirmation_code, status, completed_at)
            VALUES ($1, $2, CASE WHEN $2 = 'completed' THEN now() ELSE NULL END)
            ON CONFLICT (confirmation_code)
            DO UPDATE SET status = EXCLUDED.status, completed_at = EXCLUDED.completed_at
            """,
            confirmation_code,
            status,
        )


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
            cust = await conn.fetchrow("SELECT id FROM customers WHERE psid = $1 FOR UPDATE", psid)
            if cust is not None:
                summary["customer_found"] = True
                cid = cust["id"]
                conv_ids = [r["id"] for r in await conn.fetch(
                    "SELECT id FROM conversations WHERE customer_id = $1", cid)]
                order_ids = [r["id"] for r in await conn.fetch(
                    "SELECT id FROM orders WHERE customer_id = $1", cid)]
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

    # Redis (ngoai transaction DB). sender_id = psid (Messenger: PSID; Telegram: 'tg:<chat_id>').
    await _clear_redis(psid, summary)
    return summary


async def process_deletion(psid: str) -> dict:
    """Sinh confirmation_code, chay xoa inline, ghi trang thai. Tra ve
    {confirmation_code, summary} (summary=None neu loi).

    Xoa chay inline (nhanh voi 1 khach) nen khi tra ve thi du lieu da xoa xong.
    Loi khi xoa -> danh dau 'failed' nhung VAN tra code (callback/khach van can)."""
    confirmation_code = secrets.token_hex(8)
    await _record_request(confirmation_code, "received")
    summary = None
    try:
        summary = await _delete_customer_data(psid, confirmation_code)
        await _record_request(confirmation_code, "completed")
    except Exception as e:  # noqa: BLE001 - khong duoc lam vo response callback/chat
        print(f"[data_deletion] Loi xoa du lieu psid={mask_ref(psid)}: {safe_exc(e)}")
        await _record_request(confirmation_code, "failed")
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
