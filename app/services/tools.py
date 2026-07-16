"""Tool that (function calling) cho LLM: search_products, check_stock,
create_order, escalate_to_human.

Dung asyncpg thuan, giong cach app/services/rag.py dang lam - khong dung
SQLAlchemy ORM (repo chua co model nao, app/db.py hien khong duoc dung o dau).

Nguyen tac quan trong: LLM KHONG duoc tu bia gia/ton kho/da tao don hang -
moi thao tac lien quan du lieu kinh doanh PHAI di qua cac ham trong file nay,
dung theo dung mo ta trong system_prompt.md muc "Khi nao phai goi tool".

`psid` (Messenger page-scoped id cua khach) KHONG nam trong tool schema expose
cho LLM - orchestrator.py se tu dong bom vao khi thuc thi tool, tranh LLM
tu bia/nham lan sender_id.
"""

import re

import asyncpg

from app.config import settings
from app.services import handoff, price_overrides

PHONE_RE = re.compile(r"^(0|\+84)(3|5|7|8|9)\d{8}$")
MAX_AUTO_QUANTITY = 100  # tren nguong nay: khong tu chot don, phai escalate


def _db_url() -> str:
    return settings.database_url.replace("+asyncpg", "")


async def search_products(query: str | None = None) -> dict:
    """Tra ve danh sach san pham dang ban kem bang gia theo bac so luong.

    BAT BUOC goi tool nay truoc khi tra loi bat ky cau hoi nao ve gia cu the,
    mo ta san pham, khuyen mai, hoac bien the san pham (dung theo system_prompt.md).
    """
    conn = await asyncpg.connect(_db_url())
    try:
        products = await conn.fetch(
            "SELECT id, sku, name, description, price_vnd, stock FROM products"
        )
        result = []
        for p in products:
            tiers = await conn.fetch(
                "SELECT min_qty, unit_price_vnd FROM price_tiers "
                "WHERE product_id = $1 ORDER BY min_qty",
                p["id"],
            )
            result.append(
                {
                    "sku": p["sku"],
                    "name": p["name"],
                    "description": p["description"],
                    "stock": p["stock"],
                    "price_tiers_vnd_per_unit": [
                        {"min_qty": t["min_qty"], "unit_price_vnd": t["unit_price_vnd"]}
                        for t in tiers
                    ],
                    "note": (
                        f"Tren {MAX_AUTO_QUANTITY} hu: KHONG tu bao gia, "
                        "phai goi escalate_to_human."
                    ),
                }
            )
        return {"products": result}
    finally:
        await conn.close()


async def check_stock(sku: str, quantity: int) -> dict:
    """Kiem tra con du hang khong cho 1 sku + so luong cu the."""
    conn = await asyncpg.connect(_db_url())
    try:
        row = await conn.fetchrow("SELECT stock FROM products WHERE sku = $1", sku)
        if row is None:
            return {"error": f"Khong tim thay san pham voi sku '{sku}'"}
        return {
            "sku": sku,
            "requested_quantity": quantity,
            "current_stock": row["stock"],
            "available": row["stock"] >= quantity,
        }
    finally:
        await conn.close()


def _unit_price_for_quantity(tiers: list[asyncpg.Record], quantity: int) -> int | None:
    applicable = [t for t in tiers if t["min_qty"] <= quantity]
    if not applicable:
        return None
    return max(applicable, key=lambda t: t["min_qty"])["unit_price_vnd"]


async def create_order(
    psid: str,
    customer_name: str,
    phone: str,
    address: str,
    sku: str,
    quantity: int,
) -> dict:
    """Tao don hang THAT trong DB (bang orders + order_items) va tru ton kho.

    CHI duoc goi khi da co du ten, SDT, dia chi, san pham va so luong tu khach
    (dung theo system_prompt.md muc "Quy tac an toan"). Tu choi neu SDT sai
    dinh dang VN hoac so luong > MAX_AUTO_QUANTITY - TRU KHI co dung 1 phe duyet
    staff (price_overrides) khop CHINH XAC psid + quantity nay, xem
    app/services/price_overrides.py. LLM khong the tu tao phe duyet cho chinh no.
    """
    if quantity <= 0:
        return {"error": "So luong phai lon hon 0."}

    override = await price_overrides.get_active_override(psid, quantity)

    if quantity > MAX_AUTO_QUANTITY and not override:
        return {
            "error": (
                f"Don tren {MAX_AUTO_QUANTITY} hu khong duoc tu chot don. "
                "Goi escalate_to_human thay vi create_order, cho staff duyet gia "
                "qua lenh /approve tren Telegram truoc."
            )
        }
    phone_clean = phone.replace(" ", "").replace("-", "")
    if not PHONE_RE.match(phone_clean):
        return {"error": f"So dien thoai '{phone}' khong hop le, can dung so VN (vd 0912345678)."}

    conn = await asyncpg.connect(_db_url())
    try:
        async with conn.transaction():
            product = await conn.fetchrow(
                "SELECT id, price_vnd, stock FROM products WHERE sku = $1 FOR UPDATE", sku
            )
            if product is None:
                return {"error": f"Khong tim thay san pham voi sku '{sku}'"}
            if product["stock"] < quantity:
                return {
                    "error": (
                        f"Khong du hang: chi con {product['stock']}, "
                        f"khach can {quantity}."
                    )
                }

            if override:
                unit_price = override["unit_price_vnd"]
            else:
                tiers = await conn.fetch(
                    "SELECT min_qty, unit_price_vnd FROM price_tiers WHERE product_id = $1",
                    product["id"],
                )
                unit_price = _unit_price_for_quantity(tiers, quantity) or product["price_vnd"]
            total = unit_price * quantity

            customer = await conn.fetchrow("SELECT id FROM customers WHERE psid = $1", psid)
            if customer is None:
                customer_id = await conn.fetchval(
                    "INSERT INTO customers (psid, name, phone, address) "
                    "VALUES ($1, $2, $3, $4) RETURNING id",
                    psid, customer_name, phone_clean, address,
                )
            else:
                customer_id = customer["id"]
                await conn.execute(
                    "UPDATE customers SET name = $1, phone = $2, address = $3 WHERE id = $4",
                    customer_name, phone_clean, address, customer_id,
                )

            order_id = await conn.fetchval(
                "INSERT INTO orders "
                "(customer_id, status, total_vnd, shipping_name, shipping_phone, shipping_address) "
                "VALUES ($1, 'new', $2, $3, $4, $5) RETURNING id",
                customer_id, total, customer_name, phone_clean, address,
            )
            await conn.execute(
                "INSERT INTO order_items (order_id, product_id, quantity, unit_price_vnd) "
                "VALUES ($1, $2, $3, $4)",
                order_id, product["id"], quantity, unit_price,
            )
            await conn.execute(
                "UPDATE products SET stock = stock - $1 WHERE id = $2",
                quantity, product["id"],
            )

        if override:
            await price_overrides.mark_override_used(override["id"])

        return {
            "order_id": order_id,
            "status": "new",
            "sku": sku,
            "quantity": quantity,
            "unit_price_vnd": unit_price,
            "total_vnd": total,
            "customer_name": customer_name,
            "phone": phone_clean,
            "address": address,
            "note": (
                "Don da duoc ghi nhan. KHONG tu neu thoi gian giao hang cu the "
                "(chua co du lieu van chuyen that) - noi se co doi ngu xac nhan sau."
            ),
        }
    finally:
        await conn.close()


async def escalate_to_human(psid: str, reason: str, last_message: str = "") -> dict:
    """Chuyen hoi thoai cho nhan vien: danh dau bot_paused=TRUE tren conversation
    hien tai cua khach de bot ngung tu dong tra loi, log ly do vao bang
    escalations, va gui thong bao Telegram cho admin.

    `last_message` KHONG nam trong tool schema expose cho LLM - orchestrator tu
    bom vao (tin nhan hien tai cua khach) de admin co ngu canh ngay trong thong bao.
    """
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
            "SELECT id FROM conversations WHERE customer_id = $1 "
            "ORDER BY created_at DESC LIMIT 1",
            customer_id,
        )
        if conversation is None:
            conversation_id = await conn.fetchval(
                "INSERT INTO conversations (customer_id, bot_paused) "
                "VALUES ($1, TRUE) RETURNING id",
                customer_id,
            )
        else:
            conversation_id = conversation["id"]
            await conn.execute(
                "UPDATE conversations SET bot_paused = TRUE WHERE id = $1", conversation_id
            )
    finally:
        await conn.close()

    # Log + notify ngoai transaction chinh - loi o day (vd Telegram down) khong
    # duoc lam rollback viec danh dau bot_paused, vi do moi la phan quan trong nhat.
    try:
        await handoff.log_escalation(conversation_id, reason)
    except Exception as e:
        print(f"[tools] Ghi log escalation that bai: {e}")
    await handoff.notify_admin(psid, reason, last_message)

    return {
        "escalated": True,
        "conversation_id": conversation_id,
        "reason": reason,
        "note": "Da danh dau bot_paused=TRUE cho hoi thoai nay va bao admin.",
    }


# Schema OpenAI/DeepSeek function-calling. psid KHONG xuat hien o day - orchestrator
# tu bom vao khi thuc thi tool (xem docstring create_order/escalate_to_human).
TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "search_products",
            "description": (
                "Tra ve danh sach san pham dang ban kem bang gia theo bac so luong. "
                "BAT BUOC goi truoc khi tra loi ve gia cu the, mo ta san pham, khuyen mai, "
                "hoac bien the san pham."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "Tu khoa tim san pham, de trong neu chi can toan bo danh sach "
                            "(hien tai chi co 1 san pham nen thuong de trong)."
                        ),
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_stock",
            "description": "Kiem tra con du hang khong cho 1 san pham + so luong cu the.",
            "parameters": {
                "type": "object",
                "properties": {
                    "sku": {"type": "string", "description": "Ma san pham, vd '3S-100G'."},
                    "quantity": {"type": "integer", "description": "So luong khach muon mua."},
                },
                "required": ["sku", "quantity"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_order",
            "description": (
                "Tao don hang that trong he thong. CHI goi khi da co DU ca 4 thu: ten, "
                "so dien thoai, dia chi, va san pham + so luong muon mua. Khong goi neu "
                "con thieu bat ky thong tin nao - phai hoi lai khach truoc."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_name": {"type": "string", "description": "Ten nguoi nhan hang."},
                    "phone": {
                        "type": "string",
                        "description": "So dien thoai VN, vd 0912345678.",
                    },
                    "address": {"type": "string", "description": "Dia chi giao hang day du."},
                    "sku": {"type": "string", "description": "Ma san pham, vd '3S-100G'."},
                    "quantity": {"type": "integer", "description": "So luong hu muon mua."},
                },
                "required": ["customer_name", "phone", "address", "sku", "quantity"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "escalate_to_human",
            "description": (
                "Chuyen hoi thoai cho nhan vien xu ly. Goi khi: don >100 hu, khieu nai, "
                "cau hoi khong co du lieu de tra loi, hoac ban khong chac chan ve cau tra loi."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {
                        "type": "string",
                        "description": "Ly do escalate, ngan gon (vd 'khieu nai giao hang tre').",
                    }
                },
                "required": ["reason"],
            },
        },
    },
]
