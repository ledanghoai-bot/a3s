"""CRUD san pham + bac gia qua dashboard (issue #8, Bat 2).

Luu y quan trong ve pham vi: bang `products`/`price_tiers` la du lieu CO CAU
TRUC ma tool (search_products/check_stock/create_order trong app/services/tools.py)
doc truc tiep - KHONG di qua RAG.

Tu 17/7 ("Lop 2" - dong bo RAG tu dong theo tung san pham, xem ISSUES-VI.md):
moi san pham CO 1 knowledge_chunk rieng, tu dong tao/sua/xoa khi CRUD qua day -
giong het pattern da lam cho FAQ (app/services/knowledge_entries.py). Truong
`description` staff nhap khi tao/sua san pham SE duoc dung de tao noi dung RAG
nay - khac voi noi dung tinh trong data/knowledge/product_profile.md (van
khong tu dong dong bo, van phai sua rieng neu can).

Tu issue #9 (Bat 1): dung POOL dung chung (`app/db_pool.py`) - day la duong
goi nhieu nhat moi luot chat (get_sku_summary_text chay o MOI tin nhan), nen
duoc uu tien chuyen sang pool cung conversation_log.py.
"""

import asyncpg

from app.db_pool import get_pool
from app.services.embedder import embed_async

PRODUCT_SOURCE_LABEL = "dashboard:product"


def _vec_str(vec: list[float]) -> str:
    return "[" + ",".join(str(x) for x in vec) + "]"


def _product_embedding_text(sku: str, name: str, description: str) -> str:
    text = f"{sku} - {name}"
    if description:
        text += f": {description}"
    return text


async def list_products_full() -> list[dict]:
    """Danh sach san pham kem bac gia long vao (dung cho trang CRUD tren
    dashboard) - khac ham list_products_brief() trong orders.py (chi tra ve
    sku/ten/ton kho/gia le, dung cho dropdown OrderForm, khong can bac gia)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        products = await conn.fetch(
            "SELECT id, sku, name, description, price_vnd, stock, created_at FROM products ORDER BY id"
        )
        result = []
        for p in products:
            tiers = await conn.fetch(
                "SELECT id, min_qty, unit_price_vnd FROM price_tiers WHERE product_id = $1 ORDER BY min_qty",
                p["id"],
            )
            item = dict(p)
            item["price_tiers"] = [dict(t) for t in tiers]
            result.append(item)
        return result


async def get_sku_summary_text() -> str:
    """Tra ve 1 dong text gon liet ke TOAN BO SKU dang co - dung de BOM THANG
    vao system prompt moi luot chat (xem orchestrator.py), KHONG phu thuoc vao
    viec LLM co tu quyet dinh goi search_products hay khong.

    Day la "Lop 1" (luoi an toan ve SU TON TAI cua SKU, cuc ngan, khong phinh
    du co nhieu san pham). Chi tiet/mo ta san pham dung "Lop 2" qua RAG (xem
    logic tao/xoa knowledge_chunk trong create_product/update_product ben duoi).

    Ly do can Lop 1 (bug 17/7): du prompt/tool schema da nhac "LUON goi
    search_products", DeepSeek van tung tra loi sai/khang dinh sai "chi co 1
    SKU" khi khach hoi lai nhieu lan trong cung 1 hoi thoai - bom thang danh
    sach SKU vao context la nguon that KHONG phu thuoc hanh vi goi tool cua LLM.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT sku, name FROM products ORDER BY id")
        if not rows:
            return "Hien khong co san pham nao trong he thong."
        items = ", ".join(f"{r['sku']} ({r['name']})" for r in rows)
        return f"He thong hien co {len(rows)} SKU: {items}."


async def create_product(sku: str, name: str, description: str, price_vnd: int, stock: int) -> dict:
    """Tao san pham moi + tu dong tao 1 knowledge_chunk RAG rieng cho san pham
    nay ("Lop 2" - issue #8, 17/7). Tinh embedding TRUOC khi mo transaction de
    khong giu connection/transaction mo qua lau trong luc goi model embedding
    (CPU-bound, xem app/services/embedder.py)."""
    content = _product_embedding_text(sku, name, description)
    vec_str = _vec_str(await embed_async(content))

    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            async with conn.transaction():
                product_id = await conn.fetchval(
                    """
                    INSERT INTO products (sku, name, description, price_vnd, stock)
                    VALUES ($1, $2, $3, $4, $5) RETURNING id
                    """,
                    sku,
                    name,
                    description,
                    price_vnd,
                    stock,
                )
                await conn.execute(
                    """
                    INSERT INTO knowledge_chunks (source, content, embedding, product_id)
                    VALUES ($1, $2, $3::vector, $4)
                    """,
                    PRODUCT_SOURCE_LABEL,
                    content,
                    vec_str,
                    product_id,
                )
        except asyncpg.UniqueViolationError:
            raise ValueError(f"SKU '{sku}' da ton tai, dung SKU khac.")
        return {"id": product_id, "sku": sku, "name": name, "description": description,
                "price_vnd": price_vnd, "stock": stock, "price_tiers": []}


async def update_product(product_id: int, name: str, description: str, price_vnd: int, stock: int) -> dict:
    """Sua san pham - KHONG cho sua `sku` (immutable sau khi tao) vi sku la
    khoa tool dung de tra cuu (search_products/check_stock/create_order) - doi
    sku giua chung co the lam LLM/khach dang dung sku cu bi loi khong tim thay
    san pham.

    "Lop 2": XOA knowledge_chunk RAG cu cua san pham nay roi TAO LAI (khong
    UPDATE embedding tai cho) - tranh truong hop content moi nhung embedding
    cu bi lech nhau, giong het pattern update_faq() trong knowledge_entries.py.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT sku FROM products WHERE id = $1", product_id)
        if row is None:
            raise LookupError(f"Khong tim thay san pham id={product_id}")
        sku = row["sku"]

    content = _product_embedding_text(sku, name, description)
    vec_str = _vec_str(await embed_async(content))

    async with pool.acquire() as conn:
        async with conn.transaction():
            result = await conn.execute(
                "UPDATE products SET name = $1, description = $2, price_vnd = $3, stock = $4 WHERE id = $5",
                name,
                description,
                price_vnd,
                stock,
                product_id,
            )
            if result == "UPDATE 0":
                raise LookupError(f"Khong tim thay san pham id={product_id}")

            await conn.execute("DELETE FROM knowledge_chunks WHERE product_id = $1", product_id)
            await conn.execute(
                """
                INSERT INTO knowledge_chunks (source, content, embedding, product_id)
                VALUES ($1, $2, $3::vector, $4)
                """,
                PRODUCT_SOURCE_LABEL,
                content,
                vec_str,
                product_id,
            )
        return {"id": product_id, "name": name, "description": description,
                "price_vnd": price_vnd, "stock": stock}


async def delete_product(product_id: int) -> None:
    """Xoa san pham - se BI TU CHOI boi rang buoc khoa ngoai (khong ON DELETE
    CASCADE tren order_items/price_tiers) neu san pham da co trong don hang -
    day la thiet ke CO CHU DICH, tranh xoa nham san pham da co lich su don
    hang that. knowledge_chunks cua san pham ("Lop 2") thi TU XOA qua
    ON DELETE CASCADE (migration 009), khong can xoa tay o day."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            result = await conn.execute("DELETE FROM products WHERE id = $1", product_id)
        except asyncpg.ForeignKeyViolationError:
            raise ValueError(
                "Khong the xoa: san pham nay da co don hang hoac bac gia lien quan. "
                "Chi co the sua thong tin (vd dat stock=0), khong xoa duoc."
            )
        if result == "DELETE 0":
            raise LookupError(f"Khong tim thay san pham id={product_id}")


async def replace_price_tiers(product_id: int, tiers: list[dict]) -> list[dict]:
    """Thay TOAN BO bac gia cua 1 san pham bang danh sach moi (xoa het bac cu,
    insert lai bac moi trong 1 transaction) - don gian hon PATCH tung dong,
    tranh loi UNIQUE(product_id, min_qty) khi doi thu tu/gia tri min_qty."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        product = await conn.fetchrow("SELECT id FROM products WHERE id = $1", product_id)
        if product is None:
            raise LookupError(f"Khong tim thay san pham id={product_id}")

        async with conn.transaction():
            await conn.execute("DELETE FROM price_tiers WHERE product_id = $1", product_id)
            for t in tiers:
                await conn.execute(
                    "INSERT INTO price_tiers (product_id, min_qty, unit_price_vnd) VALUES ($1, $2, $3)",
                    product_id,
                    int(t["min_qty"]),
                    int(t["unit_price_vnd"]),
                )

        rows = await conn.fetch(
            "SELECT id, min_qty, unit_price_vnd FROM price_tiers WHERE product_id = $1 ORDER BY min_qty",
            product_id,
        )
        return [dict(r) for r in rows]
