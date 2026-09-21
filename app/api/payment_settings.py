"""CA Directive 306 + Review 308 — Payment Settings (tab Thanh toán). Bank/VietQR (bank_accounts, MASK account, tách
quyền per-field + CAS/idempotency — 308-01) + COD summary + SePay Test Mode (qua integrations provider='sepay') +
webhook/health readback redacted (308-05). Module gate: flag OFF -> 404 toàn surface (308-03). Không migrate/encrypt bank
(306 §6). Không đường bật SePay live."""
from __future__ import annotations

import asyncpg
from fastapi import APIRouter, Depends, HTTPException

# 308-03: dùng chung module gate D305 (flag OFF -> 404 toàn surface payment)
from app.api.auth import require_active_session, require_permission
from app.api.settings import require_settings_module
from app.config import settings
from app.services.settings import integrations as svc
from app.services.settings import payment_bank as banksvc

router = APIRouter(prefix="/dashboard/settings/payments", tags=["settings-payments"],
                   dependencies=[Depends(require_active_session), Depends(require_settings_module())])

_P_VIEW = "settings.integration.view"
_P_PUBLIC = "settings.integration.manage_public"
_P_SECRET = "settings.integration.secret_write"
_P_TEST = "settings.integration.test"


def _db_url() -> str:
    return settings.database_url.replace("+asyncpg", "")


def _actor(staff: dict) -> str:
    return staff.get("username") or f"staff:{staff.get('id')}"


def _map_err(e: Exception) -> HTTPException:
    if isinstance(e, svc.SettingsNotFound):
        return HTTPException(status_code=404, detail=str(e))
    if isinstance(e, svc.SettingsConflict):
        return HTTPException(status_code=409, detail=str(e))
    return HTTPException(status_code=400, detail=str(e))


def _cmd_key(body: dict) -> str:
    v = body.get("command_key")
    if not isinstance(v, str) or not v.strip():
        raise HTTPException(status_code=422, detail="thieu command_key (idempotency)")
    return v.strip()


def _expected_version(body: dict) -> int:
    v = body.get("expected_version")
    if isinstance(v, bool) or not isinstance(v, int):
        raise HTTPException(status_code=422, detail="expected_version phai so nguyen")
    return v


@router.get("", dependencies=[Depends(require_permission(_P_VIEW))])
async def overview() -> dict:
    conn = await asyncpg.connect(_db_url())
    try:
        bank = await banksvc.get_active_bank(conn)
        sepay = await svc.list_integrations(conn, kind="payment")
        # health counters REDACTED (chi count theo state, KHONG payload/account) — 308-05.
        counters = {}
        for r in await conn.fetch(
                "SELECT processing_state, count(*) c FROM provider_events WHERE provider='sepay' GROUP BY 1"):
            counters[r["processing_state"]] = r["c"]
        last_ev = await conn.fetchval(
            "SELECT max(received_at) FROM provider_events WHERE provider='sepay'")
        return {
            "bank_transfer": {"provider": "bank_transfer", "account": banksvc.mask_bank(bank),
                              "note": "Số tài khoản chỉ hiển thị 4 số cuối; server dùng để sinh VietQR. "
                                      "Đổi tài khoản chỉ áp dụng cho payment instruction MỚI; snapshot cũ bất biến."},
            "cod": {"provider": "cod", "readonly": True,
                    "note": "COD theo state machine giao/thu tiền (PR #70). Không phải cổng ngoài."},
            "sepay": {"live_locked": True, "integrations": sepay,
                      "webhook": {"endpoint": "/m7/webhooks/sepay", "auth_mode": "Apikey (Test Mode)",
                                  "connector_enabled": settings.m7_sepay_test_connector,
                                  "live_enabled": settings.sepay_live_enabled},
                      "health": {"event_counts": counters, "last_event_at": last_ev}},
        }
    finally:
        await conn.close()


@router.post("/bank/public", dependencies=[Depends(require_permission(_P_PUBLIC))])
async def update_bank_public(body: dict, staff: dict = Depends(require_active_session)) -> dict:
    """308-01: public fields (bank/bin/holder/branch/is_test) — quyền manage_public. Omitted-keeps; account GIỮ nguyên."""
    ev = _expected_version(body)
    ck = _cmd_key(body)
    fields = {k: body[k] for k in ("bank", "bin", "holder_name", "branch", "is_test") if k in body}
    if not fields:
        raise HTTPException(status_code=422, detail="khong co field public nao de sua")
    conn = await asyncpg.connect(_db_url())
    try:
        async with conn.transaction():
            return await banksvc.update_public(conn, fields=fields, expected_version=ev, actor=_actor(staff),
                                               command_key=ck)
    except svc.SettingsError as e:
        raise _map_err(e)
    finally:
        await conn.close()


@router.post("/bank/account", dependencies=[Depends(require_permission(_P_SECRET))])
async def replace_bank_account(body: dict, staff: dict = Depends(require_active_session)) -> dict:
    """308-01: thay/nhập account_number — quyền secret_write. GIỮ public fields; tạo mới cần create{bank,holder}."""
    account = body.get("account_number")
    if not isinstance(account, str) or not account.strip():
        raise HTTPException(status_code=422, detail="thieu account_number")
    ev = _expected_version(body)
    ck = _cmd_key(body)
    create = body.get("create") if isinstance(body.get("create"), dict) else None
    conn = await asyncpg.connect(_db_url())
    try:
        async with conn.transaction():
            return await banksvc.replace_account(conn, account_number=account, expected_version=ev,
                                                 actor=_actor(staff), command_key=ck, create=create)
    except svc.SettingsError as e:
        raise _map_err(e)
    finally:
        await conn.close()


@router.post("/bank/account/clear", dependencies=[Depends(require_permission(_P_SECRET))])
async def clear_bank_account(body: dict, staff: dict = Depends(require_active_session)) -> dict:
    """308-01/315-01: XÓA (deactivate) tài khoản nhận hiện hành — explicit clear (blank/omitted KHÔNG phải clear).
    Quyền secret_write. Historical instruction snapshot BẤT BIẾN; sau clear instruction mới fail-closed tới khi có account."""
    ev = _expected_version(body)
    ck = _cmd_key(body)
    conn = await asyncpg.connect(_db_url())
    try:
        async with conn.transaction():
            return await banksvc.clear_account(conn, expected_version=ev, actor=_actor(staff), command_key=ck)
    except svc.SettingsError as e:
        raise _map_err(e)
    finally:
        await conn.close()


@router.post("/vietqr-self-test", dependencies=[Depends(require_permission(_P_TEST))])
async def vietqr_self_test(body: dict, staff: dict = Depends(require_active_session)) -> dict:
    """Build+decode VietQR LOCAL từ active bank — verify CRC. KHÔNG chuyển tiền. 308-05: input sai kiểu -> 422 (KHÔNG
    silent-substitute amount/order_id)."""
    # amount_vnd: bắt buộc int > 0 (không ép 10000). order_id: bắt buộc int >= 1 (không ép 0).
    amount = body.get("amount_vnd")
    order_id = body.get("order_id")
    if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
        raise HTTPException(status_code=422, detail="amount_vnd phai so nguyen > 0")
    if isinstance(order_id, bool) or not isinstance(order_id, int) or order_id < 1:
        raise HTTPException(status_code=422, detail="order_id phai so nguyen >= 1")
    conn = await asyncpg.connect(_db_url())
    try:
        bank = await banksvc.get_active_bank(conn)
        if not bank or not bank["bin"]:
            raise HTTPException(status_code=400, detail="chua co bank active co BIN (khong sinh duoc VietQR)")
        # CA 323: prefix effective tu code_prefix (Dashboard), khong hard-code. Chua cau hinh -> 400.
        prefix = await svc.effective_sepay_prefix(conn)
        if not prefix:
            raise HTTPException(status_code=400, detail="chua cau hinh code_prefix (SePay integration) — nhap prefix truoc")
        from app.services.payment import payment_service as pay
        add_info = pay.transfer_content(order_id, prefix)
        return svc.vietqr_self_test(bin_code=str(bank["bin"]), account_number=bank["account_number"],
                                    amount_vnd=amount, add_info=add_info)
    finally:
        await conn.close()
