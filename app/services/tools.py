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


def _serving_info(net_weight_g, serving_size_g, default_price_vnd, tiers) -> dict | None:
    """Quy doi don gia moi ly tu du lieu DB (quyet dinh PO 23/7/2026).

    So ly/hu va don gia ly KHONG duoc hardcode trong system_prompt.md nua -
    tinh tu products.net_weight_g / products.serving_size_g (migration 012).
    Theo KB V2 (SKL-PRD-004): muong di kem, 1 muong ~ 1g.
    Tra ve None neu san pham chua co du lieu dinh luong (2 cot NULL) - tool
    khi do khong tra serving_info va bot khong duoc tu bia so ly.
    """
    if not net_weight_g or not serving_size_g:
        return None
    size = float(serving_size_g)  # asyncpg tra NUMERIC ve Decimal - ep float de JSON-serializable
    if size <= 0:
        return None
    servings = int(net_weight_g / size)
    if servings <= 0:
        return None
    return {
        "net_weight_g": net_weight_g,
        "serving_size_g": size,
        "servings_per_unit_approx": servings,
        "price_per_serving_vnd_approx": (
            round(default_price_vnd / servings) if default_price_vnd else None
        ),
        "price_per_serving_by_tier": [
            {
                "min_qty": t["min_qty"],
                "price_per_serving_vnd_approx": round(t["unit_price_vnd"] / servings),
            }
            for t in tiers
        ],
        "note": (
            f"Dung khi khach che dat: quy ve don gia moi ly. 1 don vi "
            f"{net_weight_g}g pha duoc KHOANG {servings} ly (dinh luong tham "
            f"khao ~{size:g}g/ly; theo KB 1 muong ~ 1g). Luon noi 'khoang/xap "
            f"xi', KHONG khang dinh so ly chinh xac - khach thich dam co the "
            f"dung nhieu muong hon nen so ly thuc te it hon."
        ),
    }


async def search_products(query: str | None = None) -> dict:
    """Tra ve danh sach san pham dang ban kem bang gia theo bac so luong.

    BAT BUOC goi tool nay truoc khi tra loi bat ky cau hoi nao ve gia cu the,
    mo ta san pham, khuyen mai, hoac bien the san pham (dung theo system_prompt.md).
    """
    conn = await asyncpg.connect(_db_url())
    try:
        products = await conn.fetch(
            "SELECT id, sku, name, description, price_vnd, stock, "
            "net_weight_g, serving_size_g FROM products"
        )
        result = []
        for p in products:
            tiers = await conn.fetch(
                "SELECT min_qty, unit_price_vnd FROM price_tiers "
                "WHERE product_id = $1 ORDER BY min_qty",
                p["id"],
            )
            item = {
                "sku": p["sku"],
                "name": p["name"],
                "description": p["description"],
                "stock": p["stock"],
                "price_vnd_default": p["price_vnd"],
                "price_tiers_vnd_per_unit": [
                    {"min_qty": t["min_qty"], "unit_price_vnd": t["unit_price_vnd"]}
                    for t in tiers
                ],
                "note": (
                    f"Neu khong co bac gia nao khop so luong khach hoi, DUNG "
                    f"'price_vnd_default' lam gia mac dinh (khong duoc noi la "
                    f"'chua co gia' chi vi price_tiers_vnd_per_unit rong - san pham "
                    f"van co gia le binh thuong). Tren {MAX_AUTO_QUANTITY} hu: KHONG "
                    "tu bao gia, phai goi escalate_to_human."
                ),
            }
            # PO 23/7: quy doi don gia ly la DU LIEU (tu DB), khong hardcode
            # trong prompt. Chi tra serving_info khi san pham co du dinh luong.
            serving = _serving_info(
                p["net_weight_g"], p["serving_size_g"], p["price_vnd"], tiers
            )
            if serving:
                item["serving_info"] = serving
            result.append(item)
        return {
            "products": result,
            "note": (
                f"Day la DANH SACH DAY DU va DUY NHAT ({len(result)} san pham) - "
                "khong co san pham nao khac ngoai danh sach nay. Neu khach hoi ve "
                "1 san pham/bien the KHONG co trong danh sach tren, phai noi that "
                "la chua co, TUYET DOI KHONG duoc bia them."
            ),
        }
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

        # Thong bao don moi cho admin qua Telegram (ngoai transaction, boc
        # try/except - don DA commit, loi thong bao khong duoc lam create_order
        # tra ve error nham).
        try:
            await handoff.notify_admin_new_order({
                "order_id": order_id,
                "customer_name": customer_name,
                "phone": phone_clean,
                "address": address,
                "sku": sku,
                "quantity": quantity,
                "unit_price_vnd": unit_price,
                "total_vnd": total,
                "status": "new",
            })
        except Exception as e:  # noqa: BLE001 - thong bao phu, khong chan tao don
            print(f"[tools] notify_admin_new_order loi (bo qua): {e}")

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
                "hoac bien the san pham. Ket qua kem 'serving_info' (so ly pha duoc moi "
                "don vi + don gia moi ly da tinh san) - BAT BUOC dung du lieu nay khi "
                "quy doi don gia ly (vd khach che dat), KHONG tu tinh/tu nho so ly."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "Tu khoa tim san pham (vd ten, kich co, dong goi). De trong "
                            "neu can toan bo danh sach san pham dang ban - LUON goi tool "
                            "nay de lay danh sach MOI NHAT, KHONG gia dinh so luong san "
                            "pham dua vao lan goi truoc hay kien thuc nen trong prompt."
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
                    "sku": {"type": "string", "description": "Ma san pham, vd '3S-100G'. Lay tu ket qua search_products, KHONG tu bia."},
                    "quantity": {"type": "integer", "description": "So luong don vi muon mua (hu/tui/goi tuy san pham)."},
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
