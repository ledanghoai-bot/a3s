"""Human handoff (issue #7/#8): kiem tra/bat lai bot_paused, thong bao admin qua
Telegram, nhan dien deterministic khi khach chu dong doi gap nguoi that, va
quy doi ma khach hang ngan (thay the PSID dai kho copy tren mobile).

Dung asyncpg thuan, cung convention voi rag.py/tools.py.
"""

import re

import asyncpg
import httpx

from app.config import settings
from app.services import conversation_log

# Cac cum tu pho bien khi khach CHU DONG doi gap nguoi that. Day la luoi an toan
# thu 2, khong phu thuoc hoan toan vao viec LLM co goi escalate_to_human dung luc
# hay khong (xem ghi chu "rui ro cao nhat" o ISSUES.md #7).
_HUMAN_REQUEST_RE = re.compile(
    r"g[ặa]p nh[âa]n vi[êe]n|g[ặa]p ng[ưu][ờo]i th[ậa]t|"
    r"n[óo]i chuy[ệe]n v[ớo]i nh[âa]n vi[êe]n|chuy[ểe]n nh[âa]n vi[êe]n|"
    r"g[ọo]i nh[âa]n vi[êe]n|cho g[ặa]p admin|g[ặa]p qu[ảa]n l[ýy]",
    re.IGNORECASE,
)

# Nhan dien 1 identifier staff go vao (/resume, /note, /approve) co hop le
# hay khong - CHAN truong hop staff go nham ca cum bot tu hien thi (vd "Ma KH:
# 4" - go ca chu "Ma" thay vi chi go so 4), tao nham customer/conversation
# rac voi psid la 1 tu tieng Viet (bug thuc te gap 16/7). Chi chap nhan: ma KH
# ngan (thuan so), hoac sender_id he thong that (tg:<so>, manual:<hex>, hoac
# PSID Facebook thuan so dai).
_TG_SENDER_RE = re.compile(r"^tg:\d+$")
_MANUAL_SENDER_RE = re.compile(r"^manual:[0-9a-f]+$")


def is_valid_identifier(raw: str) -> bool:
    """True neu chuoi staff go la ma KH/PSID hop le, False neu la rac (vd
    chua go nham chu tieng Viet thay vi chi go so)."""
    raw = raw.strip()
    if not raw:
        return False
    if raw.isdigit():
        return True
    if _TG_SENDER_RE.match(raw) or _MANUAL_SENDER_RE.match(raw):
        return True
    return False


def wants_human(text: str) -> bool:
    """True neu tin nhan chua cum tu doi gap nguoi that ro rang."""
    return bool(_HUMAN_REQUEST_RE.search(text))


def _db_url() -> str:
    return settings.database_url.replace("+asyncpg", "")


async def resolve_psid(identifier: str) -> str:
    """Cho phep staff dung MA KHACH HANG NGAN (customers.id, vd '42') thay vi
    PSID Facebook dai/kho copy tren mobile Telegram (issue #8 - nang cap UX).

    Neu identifier la chuoi so va khop voi 1 customers.id co that -> tra ve
    PSID tuong ung. Neu khong (vd da la PSID day du, hoac ma khong ton tai) ->
    tra ve nguyen identifier, coi nhu da la PSID (tuong thich nguoc).
    """
    if identifier.isdigit():
        conn = await asyncpg.connect(_db_url())
        try:
            row = await conn.fetchrow("SELECT psid FROM customers WHERE id = $1", int(identifier))
            if row:
                return row["psid"]
        finally:
            await conn.close()
    return identifier


async def get_short_code(psid: str) -> str | None:
    """Lay ma khach hang ngan (customers.id) tuong ung voi 1 psid, de hien thi
    trong thong bao Telegram thay vi PSID day du."""
    conn = await asyncpg.connect(_db_url())
    try:
        row = await conn.fetchrow("SELECT id FROM customers WHERE psid = $1", psid)
        return str(row["id"]) if row else None
    finally:
        await conn.close()


async def is_bot_paused(psid: str) -> bool:
    """True neu hoi thoai gan nhat cua khach dang bot_paused=TRUE (nhan vien da
    tiep quan). Khach moi/chua co conversation nao -> mac dinh False."""
    conn = await asyncpg.connect(_db_url())
    try:
        row = await conn.fetchrow(
            """
            SELECT c.bot_paused
            FROM conversations c
            JOIN customers cu ON cu.id = c.customer_id
            WHERE cu.psid = $1
            ORDER BY c.created_at DESC
            LIMIT 1
            """,
            psid,
        )
        return bool(row["bot_paused"]) if row else False
    finally:
        await conn.close()


async def pause_bot(psid: str, reason: str = "Nhan vien chu dong pause tu dashboard") -> bool:
    """Chieu nguoc cua resume_bot: nhan vien chu dong tiep quan hoi thoai tu
    dashboard (issue #8), khong qua escalate_to_human/LLM. Tao conversation moi
    neu khach chua tung co (vd nhan vien pause truoc ca khi khach nhan tin).
    Cung log vao escalations de nhat quan voi luong escalate qua tool."""
    conn = await asyncpg.connect(_db_url())
    try:
        customer = await conn.fetchrow("SELECT id FROM customers WHERE psid = $1", psid)
        if customer is None:
            customer_id = await conn.fetchval(
                "INSERT INTO customers (psid) VALUES ($1) RETURNING id", psid
            )
        else:
            customer_id = customer["id"]

        conversation = await conn.fetchrow(
            "SELECT id FROM conversations WHERE customer_id = $1 ORDER BY created_at DESC LIMIT 1",
            customer_id,
        )
        if conversation is None:
            conversation_id = await conn.fetchval(
                "INSERT INTO conversations (customer_id, bot_paused) VALUES ($1, TRUE) RETURNING id",
                customer_id,
            )
        else:
            conversation_id = conversation["id"]
            await conn.execute(
                "UPDATE conversations SET bot_paused = TRUE WHERE id = $1", conversation_id
            )
    finally:
        await conn.close()

    try:
        await log_escalation(conversation_id, reason)
    except Exception as e:
        print(f"[handoff] Ghi log pause thu cong that bai: {e}")
    return True


async def resume_bot(psid: str) -> bool:
    """Bat lai bot cho hoi thoai gan nhat cua khach. Tra ve True neu tim thay
    conversation de resume, False neu khach chua tung co conversation nao."""
    conn = await asyncpg.connect(_db_url())
    try:
        row = await conn.fetchrow(
            """
            SELECT c.id
            FROM conversations c
            JOIN customers cu ON cu.id = c.customer_id
            WHERE cu.psid = $1
            ORDER BY c.created_at DESC
            LIMIT 1
            """,
            psid,
        )
        if row is None:
            return False
        await conn.execute("UPDATE conversations SET bot_paused = FALSE WHERE id = $1", row["id"])
        return True
    finally:
        await conn.close()


async def get_customer_contact(psid: str) -> dict:
    """Lay ten/sdt khach da luu (neu co) de dinh kem vao thong bao admin."""
    conn = await asyncpg.connect(_db_url())
    try:
        row = await conn.fetchrow("SELECT name, phone FROM customers WHERE psid = $1", psid)
        return {"name": row["name"], "phone": row["phone"]} if row else {}
    finally:
        await conn.close()


async def log_escalation(conversation_id: int, reason: str) -> None:
    """Ghi log ly do escalate vao bang escalations (de sau nay xem lai, cai thien prompt)."""
    conn = await asyncpg.connect(_db_url())
    try:
        await conn.execute(
            "INSERT INTO escalations (conversation_id, reason) VALUES ($1, $2)",
            conversation_id,
            reason,
        )
    finally:
        await conn.close()


async def list_paused_conversations() -> list[dict]:
    """Liet ke tat ca hoi thoai dang bot_paused=TRUE, kem ten/sdt khach, ma khach
    hang ngan (customer_id) va ly do escalate gan nhat - dung cho trang admin UI
    va lenh /list tren Telegram."""
    conn = await asyncpg.connect(_db_url())
    try:
        rows = await conn.fetch(
            """
            SELECT
                cu.psid, cu.id AS customer_id, cu.name, cu.phone,
                (SELECT reason FROM escalations e WHERE e.conversation_id = c.id
                 ORDER BY e.created_at DESC LIMIT 1) AS reason,
                (SELECT created_at FROM escalations e WHERE e.conversation_id = c.id
                 ORDER BY e.created_at DESC LIMIT 1) AS escalated_at
            FROM conversations c
            JOIN customers cu ON cu.id = c.customer_id
            WHERE c.bot_paused = TRUE
            ORDER BY escalated_at DESC NULLS LAST
            """
        )
        return [dict(r) for r in rows]
    finally:
        await conn.close()


async def log_note(psid: str, note: str) -> None:
    """Ghi 1 ghi chu tuong minh (vd sep chot chinh sach dac biet qua dien thoai,
    ngoai Messenger nen khong the tu bat duoc) vao messages voi role='agent',
    danh dau ro la note noi bo. Dung chung 1 "kenh" voi tin nhan that cua nhan
    vien (xem tasks.py) de orchestrator chi can doc 1 nguon duy nhat.
    """
    conversation_id = await conversation_log.ensure_conversation(psid)
    await conversation_log.log_message(
        conversation_id, "agent", f"[Ghi chu noi bo] {note.strip()}"
    )


async def notify_admin(psid: str, reason: str, last_message: str) -> None:
    """Gui thong bao Telegram cho admin. Neu chua cau hinh TELEGRAM_BOT_TOKEN /
    TELEGRAM_ADMIN_CHAT_ID thi bo qua im lang - KHONG duoc raise loi lam gian
    doan luong tra loi khach chi vi thieu cau hinh thong bao."""
    if not settings.telegram_bot_token or not settings.telegram_admin_chat_id:
        print("[handoff] Telegram chua cau hinh (TELEGRAM_BOT_TOKEN/TELEGRAM_ADMIN_CHAT_ID), bo qua thong bao.")
        return

    contact = await get_customer_contact(psid)
    contact_line = ""
    if contact.get("name") or contact.get("phone"):
        contact_line = f"\nKhach: {contact.get('name') or '(chua co ten)'} - {contact.get('phone') or '(chua co sdt)'}"

    short_code = await get_short_code(psid)
    code_line = (
        f"\nMa so khach - CHI GO SO NAY vao lenh, KHONG go chu 'Ma KH': `{short_code}`"
        if short_code
        else ""
    )

    text = (
        "\U0001F514 3S Coffee - can nhan vien ho tro\n"
        f"PSID: `{psid}`{code_line}{contact_line}\n"
        f"Ly do: {reason}\n"
        f"Tin nhan gan nhat: {last_message[:300]}\n\n"
        "Bam nut ben duoi de resume ngay, hoac vao Trang > Hop thu tim theo ten/SDT de tra loi truoc."
    )

    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    reply_markup = {
        "inline_keyboard": [[{"text": "\u25b6\ufe0f Resume bot ngay", "callback_data": f"resume:{psid}"}]]
    }
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                url,
                json={
                    "chat_id": settings.telegram_admin_chat_id,
                    "text": text,
                    "parse_mode": "Markdown",
                    "reply_markup": reply_markup,
                },
            )
            resp.raise_for_status()
    except Exception as e:
        # Loi gui thong bao KHONG duoc lam sap luong tra loi khach - chi log.
        print(f"[handoff] Gui Telegram that bai: {e}")


def _fmt_vnd(n: object) -> str:
    """Dinh dang so tien kieu VN (170000 -> '170.000d'). Loi thi tra nguyen ban."""
    try:
        return f"{int(n):,}d".replace(",", ".")
    except (ValueError, TypeError):
        return str(n)


async def notify_admin_new_order(order: dict) -> None:
    """Gui thong bao Telegram cho admin khi co DON HANG MOI (goi tu create_order).
    Bao ve try/except - loi gui (vd Telegram down) KHONG duoc lam sap luong tao don:
    don da ghi vao DB roi, thong bao chi la phu."""
    if not settings.telegram_bot_token or not settings.telegram_admin_chat_id:
        print("[handoff] Telegram chua cau hinh, bo qua thong bao don moi.")
        return

    text = (
        "\U0001F6D2 3S Coffee - DON HANG MOI\n"
        f"Ma don: #{order.get('order_id')}\n"
        f"Khach: {order.get('customer_name') or '(chua co ten)'} - "
        f"{order.get('phone') or '(chua co sdt)'}\n"
        f"Dia chi: {order.get('address') or '(chua co)'}\n"
        f"San pham: {order.get('sku')} x {order.get('quantity')} @ "
        f"{_fmt_vnd(order.get('unit_price_vnd'))}\n"
        f"Tong: {_fmt_vnd(order.get('total_vnd'))}\n"
        f"Trang thai: {order.get('status', 'new')}"
    )
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                url,
                json={"chat_id": settings.telegram_admin_chat_id, "text": text},
            )
            resp.raise_for_status()
    except Exception as e:
        print(f"[handoff] Gui Telegram don moi that bai: {e}")
