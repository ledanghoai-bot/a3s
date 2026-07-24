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
  - AN DANH customer: bo name/phone/address, doi psid -> 'deleted:<code>' de
    cat lien ket voi PSID that (giu lai dong de khoa ngoai orders con hop le).
  - XOA cache Redis: chat:<psid>, profile:<psid>.

Khoa ngoai KHONG co ON DELETE CASCADE -> phai xoa dung thu tu (con truoc cha).
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
        "profile_cache_cleared": False,
    }
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            cust = await conn.fetchrow("SELECT id FROM customers WHERE psid = $1", psid)
            if cust is not None:
                summary["customer_found"] = True
                cid = cust["id"]
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
                # An danh don hang (giu lai cho ke toan, bo PII)
                r = await conn.execute(
                    "UPDATE orders SET shipping_name = NULL, shipping_phone = NULL, "
                    "shipping_address = NULL WHERE customer_id = $1",
                    cid,
                )
                summary["orders_anonymized"] = _tag_count(r)
                # An danh customer + cat lien ket PSID that
                await conn.execute(
                    "UPDATE customers SET name = NULL, phone = NULL, address = NULL, "
                    "psid = $2 WHERE id = $1",
                    cid,
                    f"deleted:{confirmation_code}",
                )

    # Redis (ngoai transaction DB). sender_id Messenger = psid (khong prefix).
    redis = await aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        deleted = await redis.delete(f"chat:{psid}", f"profile:{psid}")
        summary["profile_cache_cleared"] = bool(deleted)
    finally:
        await redis.aclose()
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
        print(f"[data_deletion] Loi xoa du lieu psid={psid}: {e}")
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
