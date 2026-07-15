"""API JSON cho dashboard Next.js (issue #8). Tat ca endpoint deu yeu cau header
X-Admin-Token (xem app/api/auth.py).

CRUD san pham/FAQ va metrics (con lai cua checklist #8) CHUA lam trong phan nay
theo dung uu tien anh chon - xem ISSUES.md #8.
"""

import asyncpg
from fastapi import APIRouter, Depends, HTTPException

from app.api.auth import require_admin_token
from app.config import settings
from app.services import orders as orders_service
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
    """Danh sach hoi thoai, sap theo tin nhan gan nhat, kem preview + bot_paused."""
    conn = await asyncpg.connect(_db_url())
    try:
        rows = await conn.fetch(
            """
            SELECT
                cu.psid, cu.name, cu.phone, c.bot_paused,
                (SELECT content FROM messages m WHERE m.conversation_id = c.id
                 ORDER BY m.created_at DESC LIMIT 1) AS last_message,
                (SELECT created_at FROM messages m WHERE m.conversation_id = c.id
                 ORDER BY m.created_at DESC LIMIT 1) AS last_message_at
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
