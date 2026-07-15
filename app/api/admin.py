"""API noi bo cho nhan vien: bat lai bot sau khi da xu ly xong hoi thoai
(issue #7 - human handoff).

Bao ve bang header X-Admin-Token don gian - chua co he thong auth/dashboard
that (xem issue #8), day la giai phap tam thoi de co the resume bot ma khong
can vao thang DB. Nen goi tu Postman/curl hoac gan sau nay vao nut "Resume"
tren dashboard khi #8 lam xong.
"""

from fastapi import APIRouter, Header, HTTPException

from app.config import settings
from app.services.handoff import resume_bot

router = APIRouter(prefix="/admin", tags=["admin"])


def _check_token(x_admin_token: str | None) -> None:
    if not settings.admin_api_token or x_admin_token != settings.admin_api_token:
        raise HTTPException(status_code=401, detail="Token khong hop le hoac thieu header X-Admin-Token")


@router.post("/conversations/{psid}/resume")
async def resume_conversation(psid: str, x_admin_token: str | None = Header(default=None)) -> dict:
    """Bat lai bot cho 1 khach (bot_paused=FALSE). Goi sau khi nhan vien da
    tra loi/xu ly xong hoi thoai ngoai Messenger."""
    _check_token(x_admin_token)
    found = await resume_bot(psid)
    if not found:
        raise HTTPException(status_code=404, detail=f"Khong tim thay hoi thoai cho psid {psid}")
    return {"psid": psid, "bot_paused": False}
