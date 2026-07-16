"""Quan ly don hang cho dashboard (issue #8): liet ke + cap nhat trang thai +
tao don thu cong (staff tu nhap, bo qua validate bac gia/gioi han so luong).

Dung asyncpg thuan, cung convention voi cac service khac.
"""

import json
import uuid

import asyncpg

from app.config import settings

_STAGES = ["new", "confirmed", "shipped", "done"]


def _db_url() -> str:
    return settings.database_url.replace("+asyncpg", "")


def validate_transition(current: str, new: str) -> None:
    """Raise ValueError neu chuyen trang thai khong hop le.

    Quy tac: cac buoc new -> confirmed -> shipped -> done phai di theo dung
    thu tu (khong nhay coc, khong lui). 'cancelled' cho phep tu bat ky trang
    thai nao TRU 'done' (da giao xong thi khong huy nguoc duoc nua).
    """
    if new == current:
        return
    if new == "cancelled":
        if current == "done":
            raise ValueError("Khong the huy don da giao xong (done).")
        return
    if new not in _STAGES:
        raise ValueError(f"Trang thai khong hop le: {new}")
    if current == "cancelled":
        raise ValueError("Don da huy, khong the doi sang trang thai khac.")
    if current not in _STAGES:
        raise ValueError(f"Trang thai hien tai khong hop le: {current}")
    if _STAGES.index(new) < _STAGES.index(current):
        raise ValueError(f"Khong the chuyen nguoc tu '{current}' ve '{new}'.")


async def list_orders(limit: int = 200) -> list[dict]:
    conn = await asyncpg.connect(_db_url())
    try:
        rows = await conn.fetch(
            """
            SELECT
                o.id, o.status, o.total_vnd, o.shipping_name, o.shipping_phone,
                o.shipping_address, o.created_at,
                (
                    SELECT json_agg(json_build_object(
                        'sku', p.sku, 'quantity', oi.quantity, 'unit_price_vnd', oi.unit_price_vnd
                    ))
                    FROM order_items oi
                    JOIN products p ON p.id = oi.product_id
                    WHERE oi.order_id = o.id
                ) AS items
            FROM orders o
            ORDER BY o.created_at DESC
            LIMIT $1
            """,
            limit,
        )
        result = []
        for r in rows:
            d = dict(r)
            d["items"] = json.loads(d["items"]) if d["items"] else []
            result.append(d)
        return result
    finally:
        await conn.close()


async def update_order_status(order_id: int, new_status: str) -> dict:
    conn = await asyncpg.connect(_db_url())
    try:
        row = await conn.fetchrow("SELECT status FROM orders WHERE id = $1", order_id)
        if row is None:
            raise LookupError(f"Khong tim thay don hang id={order_id}")
        validate_transition(row["status"], new_status)
        await conn.execute("UPDATE orders SET status = $1 WHERE id = $2", new_status, order_id)
        return {"id": order_id, "status": new_status}
    finally:
        await conn.close()


async def list_products_brief() -> list[dict]:
    """Danh sach san pham gon nhe (sku/ten/ton kho/gia le) - dung cho dropdown
    trong form tao don thu cong tren dashboard."""
    conn = await asyncpg.connect(_db_url())
    try:
        rows = await conn.fetch("SELECT sku, name, stock, price_vnd FROM products ORDER BY sku")
        return [dict(r) for r in rows]
    finally:
        await conn.close()


async def create_order_manual(
    customer_name: str,
    phone: str,
    address: str,
    sku: str,
    quantity: int,
    unit_price_vnd: int,
    psid: str | None = None,
) -> dict:
    """Staff tu tao don qua dashboard, BO QUA toan bo validate bac gia/gioi han
    so luong ma create_order (AI tool) ap dung - dung cho don dam phan dac biet
    hoac don khong qua Messenger (dien thoai, tai quay). Van kiem tra ton kho
    that de khong ban vuot so luong dang co.

    Neu khong truyen psid (don khong gan voi hoi thoai Messenger nao - vd khu
    vuc "tao don ben ngoai khung chat"), tu sinh 1 psid gia dang
    'manual:<uuid ngan>' de thoa man rang buoc customers.psid UNIQUE NOT NULL -
    prefix 'manual:' danh dau ro day KHONG phai PSID Facebook that.
    """
    if quantity <= 0:
        return {"error": "So luong phai lon hon 0."}
    if unit_price_vnd <= 0:
        return {"error": "Don gia phai lon hon 0."}

    psid_to_use = psid or f"manual:{uuid.uuid4().hex[:12]}"

    conn = await asyncpg.connect(_db_url())
    try:
        async with conn.transaction():
            product = await conn.fetchrow(
                "SELECT id, stock FROM products WHERE sku = $1 FOR UPDATE", sku
            )
            if product is None:
                return {"error": f"Khong tim thay san pham voi sku '{sku}'"}
            if product["stock"] < quantity:
                return {
                    "error": f"Khong du hang: chi con {product['stock']}, can {quantity}."
                }

            customer = await conn.fetchrow(
                "SELECT id FROM customers WHERE psid = $1", psid_to_use
            )
            if customer is None:
                customer_id = await conn.fetchval(
                    "INSERT INTO customers (psid, name, phone, address) "
                    "VALUES ($1, $2, $3, $4) RETURNING id",
                    psid_to_use, customer_name, phone, address,
                )
            else:
                customer_id = customer["id"]
                await conn.execute(
                    "UPDATE customers SET name = $1, phone = $2, address = $3 WHERE id = $4",
                    customer_name, phone, address, customer_id,
                )

            total = unit_price_vnd * quantity
            order_id = await conn.fetchval(
                "INSERT INTO orders "
                "(customer_id, status, total_vnd, shipping_name, shipping_phone, shipping_address) "
                "VALUES ($1, 'new', $2, $3, $4, $5) RETURNING id",
                customer_id, total, customer_name, phone, address,
            )
            await conn.execute(
                "INSERT INTO order_items (order_id, product_id, quantity, unit_price_vnd) "
                "VALUES ($1, $2, $3, $4)",
                order_id, product["id"], quantity, unit_price_vnd,
            )
            await conn.execute(
                "UPDATE products SET stock = stock - $1 WHERE id = $2", quantity, product["id"]
            )

        return {
            "order_id": order_id,
            "psid": psid_to_use,
            "sku": sku,
            "quantity": quantity,
            "unit_price_vnd": unit_price_vnd,
            "total_vnd": total,
        }
    finally:
        await conn.close()
