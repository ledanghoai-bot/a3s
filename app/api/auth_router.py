"""Router rieng cho login/logout/me/quan ly tai khoan nhan vien (issue #8,
Bat 4). KHAC voi dashboard.py/admin.py - KHONG ap dung dependency o cap
router, vi /login phai goi duoc TRUOC khi co token. Tung route can dang nhap
tu khai bao Depends(require_staff_session) rieng.

Mount tai prefix /dashboard/auth trong app/main.py.
"""

from fastapi import APIRouter, Depends, HTTPException

from app.api.auth import require_staff_session
from app.services import auth_service

router = APIRouter(prefix="/dashboard/auth", tags=["auth"])


@router.post("/login")
async def login(body: dict) -> dict:
    username = (body or {}).get("username")
    password = (body or {}).get("password")
    if not username or not password:
        raise HTTPException(status_code=422, detail="Thieu username hoac password")
    staff = await auth_service.authenticate(username, password)
    if staff is None:
        raise HTTPException(status_code=401, detail="Sai username hoac password")
    token = await auth_service.create_session(staff["id"])
    return {"token": token, "username": staff["username"], "name": staff["name"]}


@router.post("/logout")
async def logout(staff: dict = Depends(require_staff_session)) -> dict:
    await auth_service.delete_session(staff["token"])
    return {"logged_out": True}


@router.get("/me")
async def me(staff: dict = Depends(require_staff_session)) -> dict:
    return {"id": staff["id"], "username": staff["username"], "name": staff["name"]}


# --- Quan ly tai khoan nhan vien --------------------------------------------
# Bat ky staff nao dang dang nhap deu lam duoc (chua co phan quyen chi tiet
# theo role - phu hop quy mo doi nho hien tai, ghi ro trong docs la gioi han
# da biet, co the mo rong sau neu can).


@router.get("/staff")
async def list_staff(_: dict = Depends(require_staff_session)) -> list[dict]:
    return await auth_service.list_staff_users()


@router.post("/staff")
async def create_staff(body: dict, _: dict = Depends(require_staff_session)) -> dict:
    username = (body or {}).get("username")
    password = (body or {}).get("password")
    name = (body or {}).get("name", "")
    if not username or not password:
        raise HTTPException(status_code=422, detail="Thieu username hoac password")
    if len(password) < 6:
        raise HTTPException(status_code=422, detail="Mat khau can toi thieu 6 ky tu")
    try:
        return await auth_service.create_staff_user(username, password, name)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.patch("/staff/{staff_id}")
async def update_staff_active(
    staff_id: int, body: dict, _: dict = Depends(require_staff_session)
) -> dict:
    is_active = (body or {}).get("is_active")
    if is_active is None:
        raise HTTPException(status_code=422, detail="Thieu truong 'is_active'")
    try:
        await auth_service.set_staff_active(staff_id, bool(is_active))
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"id": staff_id, "is_active": bool(is_active)}
