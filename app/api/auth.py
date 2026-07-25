"""Dependency xac thuc dung chung cho cac router noi bo (admin.py, dashboard.py).

Tu Bat 4 (17/7): thay the hoan toan co che token tinh don gian (ADMIN_API_TOKEN
dung chung) bang dang nhap that theo tung nhan vien (session token rieng,
xem app/services/auth_service.py). Bien ADMIN_API_TOKEN trong config KHONG con
duoc dung o day nua (van de trong config.py/.env de tuong thich nguoc, khong
gay loi neu con set, chi la khong con tac dung).
"""

from fastapi import Depends, Header, HTTPException

from app.config import settings
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


def require_permission(permission_key: str):
    """Dependency factory server-side authorization (I-B M0.4, CA §5.8).

    Backward-compat: neu RBAC CHUA provisioned (DB truoc migration 016 + seed) -> DEGRADE ve hanh vi
    require_staff_session (cho qua) de khong lam vo dashboard o moi truong 012. Khi da provisioned +
    gan role -> enforce that: thieu quyen -> 403 (khac 401).

    STRICT MODE (settings.rbac_strict=True, CA-REVIEW-M0-DEV-002 §7.6): sau production cutover, KHONG
    degrade nua — chua provision/chua gan role -> 403 (fail-closed)."""
    async def _dep(staff: dict = Depends(require_staff_session)) -> dict:
        if not staff.get("rbac_provisioned"):
            if settings.rbac_strict:
                raise HTTPException(
                    status_code=403,
                    detail="RBAC strict: chua provision hoac tai khoan chua duoc gan role")
            return staff  # dev rollout: degrade
        if permission_key in staff.get("permissions", set()):
            return staff
        raise HTTPException(status_code=403, detail=f"Thieu quyen: {permission_key}")
    return _dep


async def require_active_session(staff: dict = Depends(require_staff_session)) -> dict:
    """Chan khi tai khoan dang o trang thai bat buoc doi mat khau (I-B M0.5, CA §12.4):
    session chi duoc goi /me, logout, change-password; business endpoint bi tu choi."""
    if staff.get("must_change_password"):
        raise HTTPException(
            status_code=403,
            detail="Yeu cau doi mat khau truoc khi dung nghiep vu",
            headers={"X-Password-Change-Required": "1"},
        )
    return staff
