"""CA Directive 306 — Payment Settings (tab Thanh toán). Bank/VietQR (bank_accounts hiện hành, MASK account) + COD
summary + SePay Test Mode (qua integrations provider='sepay'). RBAC granular D305. Không migrate/encrypt bank GĐ này
(306 §6). Không đường bật SePay live."""
from __future__ import annotations

import asyncpg
from fastapi import APIRouter, Depends, HTTPException

from app.api.auth import require_active_session, require_permission
from app.config import settings
from app.services.payment import payment_service as pay
from app.services.settings import integrations as svc

router = APIRouter(prefix="/dashboard/settings/payments", tags=["settings-payments"],
                   dependencies=[Depends(require_active_session)])

_P_VIEW = "settings.integration.view"
_P_SECRET = "settings.integration.secret_write"
_P_TEST = "settings.integration.test"


def _db_url() -> str:
    return settings.database_url.replace("+asyncpg", "")


def _actor(staff: dict) -> str:
    return staff.get("username") or f"staff:{staff.get('id')}"


def _mask_bank(row) -> dict | None:
    if not row:
        return None
    acct = row["account_number"] or ""
    return {"bank": row["bank"], "bin": row["bin"], "holder_name": row["holder_name"], "branch": row["branch"],
            "account_last4": acct[-4:] if len(acct) >= 4 else None, "is_test": row["is_test"],
            "active": row["active"], "version": row["version"]}


@router.get("", dependencies=[Depends(require_permission(_P_VIEW))])
async def overview() -> dict:
    conn = await asyncpg.connect(_db_url())
    try:
        bank = await conn.fetchrow("SELECT bank, bin, holder_name, branch, account_number, is_test, active, version "
                                   "FROM bank_accounts WHERE active")
        sepay = await svc.list_integrations(conn, kind="payment")
        return {
            "bank_transfer": {"provider": "bank_transfer", "account": _mask_bank(bank),
                              "note": "Số tài khoản chỉ hiển thị 4 số cuối; server dùng để sinh VietQR."},
            "cod": {"provider": "cod", "readonly": True,
                    "note": "COD theo state machine giao/thu tiền (PR #70). Không phải cổng ngoài."},
            "sepay": {"live_locked": True, "integrations": sepay},
        }
    finally:
        await conn.close()


@router.post("/bank", dependencies=[Depends(require_permission(_P_SECRET))])
async def set_bank(body: dict, staff: dict = Depends(require_active_session)) -> dict:
    # Ghi tài khoản = viết field nhạy cảm -> secret_write. Bank tiếp tục dùng bank_accounts (306 §6, không migrate/encrypt).
    for f in ("bank", "account_number", "holder_name"):
        if not body.get(f):
            raise HTTPException(status_code=422, detail=f"thieu {f}")
    conn = await asyncpg.connect(_db_url())
    try:
        async with conn.transaction():
            row = await pay.set_bank_account(
                conn, bank=body["bank"], account_number=body["account_number"], holder_name=body["holder_name"],
                branch=body.get("branch"), is_test=bool(body.get("is_test", False)), actor=_actor(staff),
                bin_code=(str(body["bin"]).strip() if body.get("bin") else None))
        return _mask_bank(row)   # readback MASKED
    except pay.PaymentError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        await conn.close()


@router.post("/vietqr-self-test", dependencies=[Depends(require_permission(_P_TEST))])
async def vietqr_self_test(body: dict, staff: dict = Depends(require_active_session)) -> dict:
    """Build+decode VietQR LOCAL từ active bank (server-side account) — verify CRC + khớp. KHÔNG chuyển tiền."""
    conn = await asyncpg.connect(_db_url())
    try:
        bank = await conn.fetchrow("SELECT bin, account_number FROM bank_accounts WHERE active")
        if not bank or not bank["bin"]:
            raise HTTPException(status_code=400, detail="chưa có bank active có BIN (không sinh được VietQR)")
        amount = body.get("amount_vnd") if isinstance(body.get("amount_vnd"), int) else 10000
        add_info = pay.transfer_content(int(body.get("order_id") or 0))
        return svc.vietqr_self_test(bin_code=str(bank["bin"]), account_number=bank["account_number"],
                                    amount_vnd=int(amount), add_info=add_info)
    finally:
        await conn.close()
