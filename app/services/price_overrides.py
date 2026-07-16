"""Staff duyet gia/so luong dac biet cho don hang lon (issue #8 - "ai se ghi don
hang" khi khach thuong luong qua nhan vien/sep).

Nguyen tac an toan: bang nay CHI duoc ghi qua lenh staff that (Telegram tu dung
TELEGRAM_ADMIN_CHAT_ID, hoac dashboard co token) - KHONG bao gio duoc LLM tu ghi.
create_order() trong tools.py chi duoc phep vuot MAX_AUTO_QUANTITY hoac dung gia
khac bang price_tiers khi co dung 1 ban ghi o day khop CHINH XAC ca psid va
quantity - LLM khong the tu "cap phep" cho chinh no.

Dung asyncpg thuan, cung convention voi cac service khac.
"""

import asyncpg

from app.config import settings
from app.services import conversation_log


def _db_url() -> str:
    return settings.database_url.replace("+asyncpg", "")


async def create_override(psid: str, quantity: int, unit_price_vnd: int, note: str = "") -> int:
    """Staff cap phep 1 lan cho dung 1 (psid, quantity) duoc mua voi don gia
    tuy chinh, bo qua bac gia chuan va gioi han so luong tu dong. Tra ve id
    ban ghi vua tao.

    QUAN TRONG: goi ensure_conversation() truoc - KHONG chi tao rieng customer
    nhu ban cu, vi dashboard liet ke hoi thoai bat dau tu bang `conversations`
    (FROM conversations JOIN customers), nen khach chi co customer ma chua co
    conversation se KHONG hien tren dashboard du da /approve thanh cong (bug
    da gap 15/7 - anh Hoai /approve cho khach chua tung chat/note truoc do).
    """
    await conversation_log.ensure_conversation(psid)

    conn = await asyncpg.connect(_db_url())
    try:
        customer = await conn.fetchrow("SELECT id FROM customers WHERE psid = $1", psid)
        customer_id = customer["id"]  # chac chan co roi vi ensure_conversation() da tao

        override_id = await conn.fetchval(
            """
            INSERT INTO price_overrides (customer_id, quantity, unit_price_vnd, note)
            VALUES ($1, $2, $3, $4) RETURNING id
            """,
            customer_id,
            quantity,
            unit_price_vnd,
            note,
        )
        return override_id
    finally:
        await conn.close()


async def get_active_override(psid: str, quantity: int) -> dict | None:
    """Tim 1 phe duyet CON HIEU LUC (used=FALSE) khop dung psid + quantity.
    Neu quantity khach/bot dua ra khong khop CHINH XAC voi so luong staff da
    duyet, tra ve None (khong duoc tu suy dien/lam tron)."""
    conn = await asyncpg.connect(_db_url())
    try:
        row = await conn.fetchrow(
            """
            SELECT po.id, po.unit_price_vnd, po.note
            FROM price_overrides po
            JOIN customers cu ON cu.id = po.customer_id
            WHERE cu.psid = $1 AND po.quantity = $2 AND po.used = FALSE
            ORDER BY po.created_at DESC
            LIMIT 1
            """,
            psid,
            quantity,
        )
        return dict(row) if row else None
    finally:
        await conn.close()


async def mark_override_used(override_id: int) -> None:
    """Danh dau da dung ("Da tao don"), tranh 1 phe duyet bi dung lai cho don
    khac ngoai y muon. Cap nhat ca `status='used'` de dashboard hien dung nhan
    (khac voi 'rejected') - `used=TRUE` van la nguon that cho logic tao don
    (create_order), khong doi."""
    conn = await asyncpg.connect(_db_url())
    try:
        await conn.execute(
            "UPDATE price_overrides SET used = TRUE, status = 'used' WHERE id = $1", override_id
        )
    finally:
        await conn.close()


async def reject_override(override_id: int, reason: str) -> None:
    """Tu choi 1 phe duyet vi ly do khac (khach doi y, sep huy...) - khac voi
    "da tao don". Van set used=TRUE de khong con dung duoc cho tao don nua,
    nhung status/reject_reason rieng de dashboard phan biet ro 2 truong hop
    (issue #8 - nang cap UX 16/7 lan 5).
    """
    conn = await asyncpg.connect(_db_url())
    try:
        await conn.execute(
            "UPDATE price_overrides SET used = TRUE, status = 'rejected', reject_reason = $1 WHERE id = $2",
            reason,
            override_id,
        )
    finally:
        await conn.close()


async def get_latest_unused_override(psid: str) -> dict | None:
    """Lay phe duyet CHUA DUNG gan nhat cua 1 khach, khong can biet truoc so
    luong (khac get_active_override() phai khop chinh xac quantity) - dung de
    tu dien san form tao don tren dashboard (issue #8 - lay du lieu tu /approve
    thay vi staff phai go lai tay).
    """
    conn = await asyncpg.connect(_db_url())
    try:
        row = await conn.fetchrow(
            """
            SELECT po.id, po.quantity, po.unit_price_vnd, po.note, po.created_at
            FROM price_overrides po
            JOIN customers cu ON cu.id = po.customer_id
            WHERE cu.psid = $1 AND po.used = FALSE
            ORDER BY po.created_at DESC
            LIMIT 1
            """,
            psid,
        )
        return dict(row) if row else None
    finally:
        await conn.close()


async def list_unused_overrides(psid: str) -> list[dict]:
    """Lay TAT CA phe duyet CHUA DUNG cua 1 khach, kem id de dashboard gan nut
    "Da tao don" cho tung dong rieng (issue #8 - nang cap UX 16/7)."""
    conn = await asyncpg.connect(_db_url())
    try:
        rows = await conn.fetch(
            """
            SELECT po.id, po.quantity, po.unit_price_vnd, po.note, po.created_at
            FROM price_overrides po
            JOIN customers cu ON cu.id = po.customer_id
            WHERE cu.psid = $1 AND po.used = FALSE
            ORDER BY po.created_at DESC
            """,
            psid,
        )
        return [dict(r) for r in rows]
    finally:
        await conn.close()


async def count_unused_overrides(psid: str) -> int:
    """So phe duyet chua dung - dung cho nhan "/a(N)" tren dashboard."""
    conn = await asyncpg.connect(_db_url())
    try:
        return await conn.fetchval(
            """
            SELECT COUNT(*)
            FROM price_overrides po
            JOIN customers cu ON cu.id = po.customer_id
            WHERE cu.psid = $1 AND po.used = FALSE
            """,
            psid,
        )
    finally:
        await conn.close()


async def list_all_overrides(psid: str) -> list[dict]:
    """Lay TOAN BO phe duyet cua 1 khach (moi trang thai: active/used/rejected),
    khong loc/an - de dashboard hien lai lich su du da xu ly xong (issue #8 -
    nang cap UX 16/7 lan 5, thay vi lam bien mat khoi giao dien nhu ban truoc).
    """
    conn = await asyncpg.connect(_db_url())
    try:
        rows = await conn.fetch(
            """
            SELECT po.id, po.quantity, po.unit_price_vnd, po.note, po.status,
                   po.reject_reason, po.created_at
            FROM price_overrides po
            JOIN customers cu ON cu.id = po.customer_id
            WHERE cu.psid = $1
            ORDER BY po.created_at DESC
            """,
            psid,
        )
        return [dict(r) for r in rows]
    finally:
        await conn.close()
