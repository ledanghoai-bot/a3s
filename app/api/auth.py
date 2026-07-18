"""Dependency xac thuc dung chung cho cac router noi bo (admin.py, dashboard.py).

Tu Bat 4 (17/7): thay the hoan toan co che token tinh don gian (ADMIN_API_TOKEN
dung chung) bang dang nhap that theo tung nhan vien (session token rieng,
xem app/services/auth_service.py). Bien ADMIN_API_TOKEN trong config KHONG con
duoc dung o day nua (van de trong config.py/.env de tuong thich nguoc, khong
gay loi neu con set, chi la khong con tac dung).
"""

from fastapi import Header, HTTPException

from app.services import auth_service


async def require_staff_session(authorization: str | None = Header(default=None)) -> dict:
    """Dependency ap dung cho moi route can dang nhap - doc header chuan
    'Authorization: Bearer <token>'. Tra ve dict {id, username, name, token}
    neu hop le - route nao can biet AI dang thao tac (vd logout) khai bao
    truc tiep `staff: dict = Depends(require_staff_session)` de lay du lieu
    nay, khong chi dung o muc router-level dependencies=[...]."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Thieu token dang nhap (header Authorization)")
    token = authorization.removeprefix("Bearer ").strip()
    staff = await auth_service.validate_session(token)
    if staff is None:
        raise HTTPException(status_code=401, detail="Token khong hop le hoac da het han, dang nhap lai")
    return staff
