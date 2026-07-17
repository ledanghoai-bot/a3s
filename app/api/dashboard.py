"""API JSON cho dashboard Next.js (issue #8). Tat ca endpoint deu yeu cau header
X-Admin-Token (xem app/api/auth.py).

CRUD san pham/FAQ va metrics (con lai cua checklist #8) CHUA lam trong phan nay
theo dung uu tien anh chon - xem ISSUES.md #8.
"""

import asyncpg
from fastapi import APIRouter, Depends, HTTPException

from app.api.auth import require_admin_token
from app.config import settings
from app.services import conversation_log, price_overrides, products as products_service
from app.services import knowledge_entries
from app.services import metrics
from app.services import orders as orders_service
from app.services import tools
from app.services.handoff import log_note, pause_bot, resume_bot

router = APIRouter(
    prefix="/dashboard", tags=["dashboard"], dependencies=[Depends(require_admin_token)]
)


def _db_url() -> str:
    return settings.database_url.replace("+asyncpg", "")


@router.get("/ping")
async def ping() -> dict:
    """Dung de frontend kiem tra token con hop le hay khong sau khi nhap."""
    return {"ok": True}


@router.get("/conversations")
async def list_conversations(limit: int = 200) -> list[dict]:
    """Danh sach hoi thoai, sap theo tin nhan gan nhat, kem preview + bot_paused
    + so luong note/approve CHUA xu ly (issue #8 - nang cap UX 16/7: nhan gon
    "/n(N)" "/a(N)" thay vi badge to, cot Action rieng cho ca hoi thoai da bo).
    """
    conn = await asyncpg.connect(_db_url())
    try:
        rows = await conn.fetch(
            """
            SELECT
                cu.psid, cu.name, cu.phone, c.bot_paused,
                (SELECT content FROM messages m WHERE m.conversation_id = c.id
                 ORDER BY m.created_at DESC LIMIT 1) AS last_message,
                (SELECT created_at FROM messages m WHERE m.conversation_id = c.id
                 ORDER BY m.created_at DESC LIMIT 1) AS last_message_at,
                (SELECT COUNT(*) FROM messages m2
                 WHERE m2.conversation_id = c.id AND m2.role = 'agent' AND m2.handled = FALSE
                ) AS unhandled_notes_count,
                (SELECT COUNT(*) FROM price_overrides po
                 WHERE po.customer_id = cu.id AND po.used = FALSE
                ) AS unused_overrides_count
            FROM conversations c
            JOIN customers cu ON cu.id = c.customer_id
            ORDER BY last_message_at DESC NULLS LAST
            LIMIT $1
            """,
            limit,
        )
        return [dict(r) for r in rows]
    finally:
        await conn.close()


@router.post("/notes/{message_id}/mark-handled")
async def mark_note_handled(message_id: int) -> dict:
    """Danh dau 1 note (tin nhan role='agent') la da xu ly - khong can popup
    xac nhan (theo yeu cau anh Hoai 16/7). Note van con nguyen trong DB va
    trong context bo cho bot doc, chi an khoi danh sach "chua xu ly" tren
    dashboard."""
    found = await conversation_log.mark_message_handled(message_id)
    if not found:
        raise HTTPException(status_code=404, detail=f"Khong tim thay note id={message_id}")
    return {"message_id": message_id, "handled": True}


@router.post("/overrides/{override_id}/mark-used")
async def mark_override_used_endpoint(override_id: int) -> dict:
    """Danh dau 1 phe duyet /approve la "da tao don". Frontend PHAI popup xac
    nhan truoc khi goi endpoint nay (theo yeu cau anh Hoai 16/7) - endpoint
    khong tu hoi lai, tin tuong client. Ban ghi VAN GIU nguyen trong DB, chi
    doi status -> hien "frozen" tren dashboard, khong bien mat."""
    await price_overrides.mark_override_used(override_id)
    return {"override_id": override_id, "used": True, "status": "used"}


@router.post("/overrides/{override_id}/reject")
async def reject_override_endpoint(override_id: int, body: dict) -> dict:
    """Tu choi 1 phe duyet vi ly do khac (khach doi y, sep huy...) - khac "da
    tao don". Frontend PHAI popup xac nhan + xin ly do truoc khi goi (theo
    yeu cau anh Hoai 16/7 lan 5)."""
    reason = (body or {}).get("reason")
    if not reason or not reason.strip():
        raise HTTPException(status_code=422, detail="Thieu ly do tu choi trong body")
    await price_overrides.reject_override(override_id, reason.strip())
    return {"override_id": override_id, "status": "rejected", "reject_reason": reason.strip()}


@router.get("/conversations/{psid}/messages")
async def get_conversation_messages(psid: str) -> list[dict]:
    """Toan bo lich su tin nhan cua 1 khach, sap theo thoi gian tang dan."""
    conn = await asyncpg.connect(_db_url())
    try:
        rows = await conn.fetch(
            """
            SELECT m.role, m.content, m.created_at
            FROM messages m
            JOIN conversations c ON c.id = m.conversation_id
            JOIN customers cu ON cu.id = c.customer_id
            WHERE cu.psid = $1
            ORDER BY m.created_at ASC
            """,
            psid,
        )
        return [dict(r) for r in rows]
    finally:
        await conn.close()


@router.post("/conversations/{psid}/pause")
async def pause_conversation(psid: str) -> dict:
    """Nhan vien chu dong tiep quan hoi thoai tu dashboard (khac escalate_to_human
    la LLM/khach tu kich hoat - day la nhan vien tu bam)."""
    await pause_bot(psid)
    return {"psid": psid, "bot_paused": True}


@router.post("/conversations/{psid}/resume")
async def resume_conversation(psid: str, body: dict | None = None) -> dict:
    """Body tuy chon: {"note": "gia dac biet 130k/hu cho 1000 hu, giao 5 ngay"}.
    Note se duoc ghi vao lich su hoi thoai (role='agent') VA bom nguoc vao
    context cua bot cho cac luot chat sau, de bot khong noi trai thoa thuan
    nhan vien/sep vua chot (issue #8 - xu ly tin nhan luc handover)."""
    found = await resume_bot(psid)
    if not found:
        raise HTTPException(status_code=404, detail=f"Khong tim thay hoi thoai cho psid {psid}")
    note = (body or {}).get("note")
    if note and note.strip():
        await log_note(psid, note)
    return {"psid": psid, "bot_paused": False}


@router.post("/conversations/{psid}/note")
async def add_note(psid: str, body: dict) -> dict:
    """Them ghi chu BAT KY LUC NAO, doc lap voi pause/resume - vd staff dang
    thuong luong qua dien thoai trong khi bot van dang tra loi binh thuong,
    hoac muon bo sung them thong tin sau khi da resume roi (issue #8)."""
    note = (body or {}).get("note")
    if not note or not note.strip():
        raise HTTPException(status_code=422, detail="Thieu truong 'note' trong body")
    await log_note(psid, note)
    return {"psid": psid, "note_added": True}


@router.get("/orders")
async def get_orders(limit: int = 200) -> list[dict]:
    return await orders_service.list_orders(limit=limit)


@router.get("/products")
async def get_products() -> list[dict]:
    """Danh sach san pham gon nhe, dung cho dropdown trong form tao don
    (ca ban trong khung chat va khu vuc tao don doc lap - issue #8)."""
    return await orders_service.list_products_brief()


@router.get("/conversations/{psid}/order_draft")
async def get_order_draft(psid: str) -> dict:
    """Gom san du lieu de tu dien form tao don + hien thi trong khung chat mo
    rong (issue #8 - nang cap 16/7 lan 5: hien TOAN BO lich su, khong an note/
    approve da xu ly, chi doi trang thai "frozen" o phia frontend):
    - customer: ten/sdt/dia chi da luu tu don truoc (neu co)
    - active_override: phe duyet CHUA DUNG gan nhat (dung tu dien form, giu
      nguyen logic cu)
    - overrides: TOAN BO phe duyet (active/used/rejected) - de hien tung dong
      rieng, staff van xem lai duoc lich su da xu ly
    - notes: TOAN BO note (da xu ly lan chua) - tuong tu
    """
    conn = await asyncpg.connect(_db_url())
    try:
        customer = await conn.fetchrow(
            "SELECT name, phone, address FROM customers WHERE psid = $1", psid
        )
    finally:
        await conn.close()

    active_override = await price_overrides.get_latest_unused_override(psid)
    overrides = await price_overrides.list_all_overrides(psid)
    notes = await conversation_log.list_all_agent_messages(psid)

    return {
        "customer": dict(customer) if customer else {},
        "active_override": active_override,
        "overrides": overrides,
        "notes": notes,
    }


@router.post("/conversations/{psid}/create_order")
async def create_order_via_bot(psid: str, body: dict) -> dict:
    """'Goi bot tao don' - goi THANG dung ham create_order ma AI tool dang
    dung (app/services/tools.py), nen van kiem tra day du price_overrides,
    bac gia chuan, gioi han MAX_AUTO_QUANTITY - chi khac la staff bam tu
    dashboard thay vi cho LLM tu quyet dinh goi luc nao.
    """
    required = ["customer_name", "phone", "address", "sku", "quantity"]
    missing = [f for f in required if not body.get(f)]
    if missing:
        raise HTTPException(status_code=422, detail=f"Thieu truong: {', '.join(missing)}")
    result = await tools.create_order(
        psid=psid,
        customer_name=body["customer_name"],
        phone=body["phone"],
        address=body["address"],
        sku=body["sku"],
        quantity=int(body["quantity"]),
    )
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/conversations/{psid}/create_order_manual")
async def create_order_manual_for_conversation(psid: str, body: dict) -> dict:
    """'NV tao don' gan voi 1 hoi thoai co san - bo qua toan bo validate bac
    gia/gioi han so luong cua create_order (AI tool), staff tu nhap don gia
    va tu chiu trach nhiem."""
    required = ["customer_name", "phone", "address", "sku", "quantity", "unit_price_vnd"]
    missing = [f for f in required if not body.get(f)]
    if missing:
        raise HTTPException(status_code=422, detail=f"Thieu truong: {', '.join(missing)}")
    result = await orders_service.create_order_manual(
        customer_name=body["customer_name"],
        phone=body["phone"],
        address=body["address"],
        sku=body["sku"],
        quantity=int(body["quantity"]),
        unit_price_vnd=int(body["unit_price_vnd"]),
        psid=psid,
    )
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/orders/manual")
async def create_order_manual_standalone(body: dict) -> dict:
    """Khu vuc tao don HOAN TOAN DOC LAP, khong gan voi hoi thoai Messenger nao
    (vd don qua dien thoai/tai quay) - issue #8. Tu sinh psid gia 'manual:...'.
    """
    required = ["customer_name", "phone", "address", "sku", "quantity", "unit_price_vnd"]
    missing = [f for f in required if not body.get(f)]
    if missing:
        raise HTTPException(status_code=422, detail=f"Thieu truong: {', '.join(missing)}")
    result = await orders_service.create_order_manual(
        customer_name=body["customer_name"],
        phone=body["phone"],
        address=body["address"],
        sku=body["sku"],
        quantity=int(body["quantity"]),
        unit_price_vnd=int(body["unit_price_vnd"]),
        psid=None,
    )
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.patch("/orders/{order_id}/status")
async def patch_order_status(order_id: int, body: dict) -> dict:
    """Body: {"status": "confirmed"}. Chi cho phep chuyen dung thu tu
    new -> confirmed -> shipped -> done (hoac 'cancelled' tu bat ky buoc nao
    truoc 'done') - xem app/services/orders.py:validate_transition."""
    new_status = body.get("status")
    if not new_status:
        raise HTTPException(status_code=422, detail="Thieu truong 'status' trong body")
    try:
        return await orders_service.update_order_status(order_id, new_status)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ---------------------------------------------------------------------------
# CRUD San pham (issue #8, Bat 2) - du lieu CO CAU TRUC ma tool doc truc tiep,
# KHONG di qua RAG. Xem app/services/products.py cho ghi chu day du ve pham vi.
# ---------------------------------------------------------------------------


@router.get("/products/full")
async def get_products_full() -> list[dict]:
    """Danh sach san pham DAY DU kem bac gia long vao - dung cho trang CRUD
    san pham tren dashboard. Khac `GET /products` (brief) dang dung cho
    dropdown trong OrderForm - KHONG doi endpoint do de tranh pha vo OrderForm.
    """
    return await products_service.list_products_full()


@router.post("/products")
async def create_product_endpoint(body: dict) -> dict:
    required = ["sku", "name", "price_vnd", "stock"]
    missing = [f for f in required if body.get(f) in (None, "")]
    if missing:
        raise HTTPException(status_code=422, detail=f"Thieu truong: {', '.join(missing)}")
    try:
        return await products_service.create_product(
            sku=body["sku"],
            name=body["name"],
            description=body.get("description", ""),
            price_vnd=int(body["price_vnd"]),
            stock=int(body["stock"]),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/products/{product_id}")
async def update_product_endpoint(product_id: int, body: dict) -> dict:
    """KHONG nhan `sku` - xem ghi chu trong products.py:update_product ve ly
    do sku la immutable sau khi tao."""
    required = ["name", "price_vnd", "stock"]
    missing = [f for f in required if body.get(f) in (None, "")]
    if missing:
        raise HTTPException(status_code=422, detail=f"Thieu truong: {', '.join(missing)}")
    try:
        return await products_service.update_product(
            product_id=product_id,
            name=body["name"],
            description=body.get("description", ""),
            price_vnd=int(body["price_vnd"]),
            stock=int(body["stock"]),
        )
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/products/{product_id}")
async def delete_product_endpoint(product_id: int) -> dict:
    try:
        await products_service.delete_product(product_id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"product_id": product_id, "deleted": True}


@router.put("/products/{product_id}/tiers")
async def replace_price_tiers_endpoint(product_id: int, body: dict) -> dict:
    """Body: {"tiers": [{"min_qty": 5, "unit_price_vnd": 160000}, ...]}.
    Thay TOAN BO bac gia cua san pham nay bang danh sach moi (xem
    products.py:replace_price_tiers)."""
    tiers = body.get("tiers")
    if tiers is None or not isinstance(tiers, list):
        raise HTTPException(status_code=422, detail="Thieu truong 'tiers' (danh sach) trong body")
    try:
        updated = await products_service.replace_price_tiers(product_id, tiers)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"product_id": product_id, "price_tiers": updated}


# ---------------------------------------------------------------------------
# CRUD FAQ (issue #8, Bat 2) - tu dong dong bo RAG khi sua/xoa. Xem
# app/services/knowledge_entries.py cho ghi chu day du.
# ---------------------------------------------------------------------------


@router.get("/faq")
async def list_faq_endpoint() -> list[dict]:
    return await knowledge_entries.list_faq()


@router.post("/faq")
async def create_faq_endpoint(body: dict) -> dict:
    question = body.get("question")
    answer = body.get("answer")
    if not question or not answer:
        raise HTTPException(status_code=422, detail="Thieu 'question' hoac 'answer' trong body")
    return await knowledge_entries.create_faq(question.strip(), answer.strip())


@router.patch("/faq/{entry_id}")
async def update_faq_endpoint(entry_id: int, body: dict) -> dict:
    question = body.get("question")
    answer = body.get("answer")
    if not question or not answer:
        raise HTTPException(status_code=422, detail="Thieu 'question' hoac 'answer' trong body")
    try:
        return await knowledge_entries.update_faq(entry_id, question.strip(), answer.strip())
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/faq/{entry_id}")
async def delete_faq_endpoint(entry_id: int) -> dict:
    found = await knowledge_entries.delete_faq(entry_id)
    if not found:
        raise HTTPException(status_code=404, detail=f"Khong tim thay FAQ id={entry_id}")
    return {"id": entry_id, "deleted": True}


# ---------------------------------------------------------------------------
# Metrics/Analytics (issue #8, Bat 3) - tan dung hoan toan du lieu san co,
# KHONG them bang moi. Xem app/services/metrics.py cho ghi chu day du.
# ---------------------------------------------------------------------------


@router.get("/metrics/messages-per-day")
async def get_messages_per_day(days: int = 14) -> list[dict]:
    return await metrics.list_messages_per_day(days=days)


@router.get("/metrics/conversion-rate")
async def get_conversion_rate_endpoint() -> dict:
    return await metrics.get_conversion_rate()


@router.get("/metrics/unanswered-questions")
async def get_unanswered_questions(limit: int = 20) -> list[dict]:
    return await metrics.list_unanswered_questions(limit=limit)
