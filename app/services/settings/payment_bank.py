"""CA Directive 306 + Review 308-01 — Bank/VietQR settings service (tách quyền per-field + CAS + command idempotency).

Bank tiếp tục dùng bảng `bank_accounts` (306 §6, KHÔNG migrate/encrypt GĐ này). Model: 1 active row, versioned bằng cách
tạo active mới + deactivate cũ. D306 bọc bằng:
- update_public: sửa bank/bin/holder/branch/is_test — quyền `manage_public`, GIỮ account_number hiện hành (omitted-keeps).
- replace_account: thay account_number — quyền `secret_write`, GIỮ public fields hiện hành.
Cả hai: expected_version CAS + command_key idempotency (dùng journal integration_commands của D305) + validate-before-mutation.
Historical payment_instructions BẤT BIẾN (snapshot account riêng) — đổi bank chỉ áp dụng instruction MỚI.
"""
from __future__ import annotations

from app.services import audit_service
from app.services.settings import integrations as _S


class BankSettingsError(_S.SettingsError):
    pass


def mask_bank(row) -> dict | None:
    if not row:
        return None
    acct = row["account_number"] or ""
    return {"bank": row["bank"], "bin": row["bin"], "holder_name": row["holder_name"], "branch": row["branch"],
            "account_last4": acct[-4:] if len(acct) >= 4 else None, "is_test": row["is_test"],
            "active": row["active"], "version": row["version"]}


def _valid_bin(v):
    if v in (None, ""):
        return None
    if not (isinstance(v, str) and v.isdigit() and len(v) == 6):
        raise BankSettingsError("bin phai 6 chu so (NAPAS BIN) hoac de trong")
    return v


def _valid_account(v):
    if not isinstance(v, str) or not v.strip():
        raise BankSettingsError("account_number rong")
    a = v.strip()
    if not (a.isdigit() and 6 <= len(a) <= 19):
        raise BankSettingsError("account_number phai 6-19 chu so")
    return a


def _valid_str_field(fields: dict, key: str, prev, *, required_nonempty: bool):
    """Validate DETERMINISTIC (315-04): field co mat phai dung kieu chuoi; sai kieu/rong -> reject (khong im lang giu prev)."""
    if key not in fields:
        return prev
    v = fields[key]
    if v is None and not required_nonempty:
        return None
    if not isinstance(v, str):
        raise BankSettingsError(f"{key} phai chuoi")
    v = v.strip()
    if required_nonempty and not v:
        raise BankSettingsError(f"{key} rong")
    return v


def _valid_is_test(fields: dict, prev):
    if "is_test" not in fields:
        return prev
    v = fields["is_test"]
    if not isinstance(v, bool):   # 315-04: KHONG bool("false")==True; phai boolean that
        raise BankSettingsError("is_test phai boolean")
    return v


async def get_active_bank(conn):
    return await conn.fetchrow(
        "SELECT id, bank, bin, holder_name, branch, account_number, is_test, active, version FROM bank_accounts "
        "WHERE active")


async def _new_active(conn, *, prev, account_number, bank, bin_code, holder_name, branch, is_test, actor, action):
    """Deactivate active cu (neu co) + insert active moi version+1. prev=None -> version 1 (create)."""
    new_version = (prev["version"] + 1) if prev else 1
    if prev:
        await conn.execute("UPDATE bank_accounts SET active=false, updated_at=now() WHERE id=$1", prev["id"])
    row = await conn.fetchrow(
        "INSERT INTO bank_accounts (bank, account_number, holder_name, branch, version, active, is_test, bin) "
        "VALUES ($1,$2,$3,$4,$5,true,$6,$7) RETURNING id, bank, bin, holder_name, branch, account_number, is_test, "
        "active, version", bank, account_number, holder_name, branch, new_version, is_test, bin_code)
    await audit_service.record(conn, actor_type="staff", action=action, actor_ref=actor,
                               entity_type="bank_accounts", entity_id=str(row["id"]),
                               after={"version": new_version, "is_test": is_test})   # KHONG account/plaintext
    return row


async def update_public(conn, *, fields: dict, expected_version: int, actor: str, command_key: str) -> dict:
    """Sua PUBLIC fields (bank/bin/holder/branch/is_test). Omitted-keeps. GIU account_number hien hanh. CAS + idempotency.
    Yeu cau da co active bank (khong tao account qua duong nay — account di duong secret_write)."""
    fp = _S._payload_fp("bank_public", None, {"v": expected_version, "f": {k: fields.get(k) for k in
                        ("bank", "bin", "holder_name", "branch", "is_test")}})

    async def _do():
        prev = await conn.fetchrow("SELECT * FROM bank_accounts WHERE active FOR UPDATE")
        if not prev:
            raise BankSettingsError("chua co tai khoan bank active — nhap account (secret_write) truoc")
        if prev["version"] != expected_version:
            raise _S.SettingsConflict("version conflict (bank da doi) — tai lai")
        # validate DETERMINISTIC truoc mutation (315-04): sai kieu -> reject, khong im lang giu prev/DB ep.
        bank = _valid_str_field(fields, "bank", prev["bank"], required_nonempty=True)
        holder = _valid_str_field(fields, "holder_name", prev["holder_name"], required_nonempty=True)
        branch = _valid_str_field(fields, "branch", prev["branch"], required_nonempty=False)
        is_test = _valid_is_test(fields, prev["is_test"])
        bin_code = _valid_bin(fields["bin"]) if "bin" in fields else prev["bin"]
        row = await _new_active(conn, prev=prev, account_number=prev["account_number"], bank=bank, bin_code=bin_code,
                                holder_name=holder, branch=branch, is_test=is_test, actor=actor,
                                action="bank.update_public")
        return mask_bank(row)

    return await _S._run_command(conn, command_key=command_key, action="bank_public", integration_id=None,
                                 payload_fp=fp, fn=_do)


async def replace_account(conn, *, account_number: str, expected_version: int, actor: str, command_key: str,
                          create: dict | None = None) -> dict:
    """Thay account_number (secret_write). GIU public fields hien hanh. Neu chua co active bank -> tao moi (create dict
    bat buoc: bank/holder/bin/branch/is_test). CAS + idempotency + validate-before-mutation. Historical instruction bat bien."""
    acct = _valid_account(account_number)   # fail TRUOC moi mutation (308-01)
    fp = _S._payload_fp("bank_account", None, {"v": expected_version, "acct_fp": _S._c.fingerprint(acct)})

    async def _do():
        prev = await conn.fetchrow("SELECT * FROM bank_accounts WHERE active FOR UPDATE")
        if prev:
            if prev["version"] != expected_version:
                raise _S.SettingsConflict("version conflict (bank da doi) — tai lai")
            row = await _new_active(conn, prev=prev, account_number=acct, bank=prev["bank"], bin_code=prev["bin"],
                                    holder_name=prev["holder_name"], branch=prev["branch"], is_test=prev["is_test"],
                                    actor=actor, action="bank.replace_account")
        else:
            if expected_version not in (0, None):
                raise _S.SettingsConflict("chua co bank active — expected_version phai 0 de tao moi")
            c = create or {}
            if not (c.get("bank") and c.get("holder_name")):
                raise BankSettingsError("tao bank moi can bank + holder_name")
            is_test = c["is_test"] if isinstance(c.get("is_test"), bool) else False   # KHONG ep chuoi -> bool
            row = await _new_active(conn, prev=None, account_number=acct, bank=c["bank"].strip(),
                                    bin_code=_valid_bin(c.get("bin")), holder_name=c["holder_name"].strip(),
                                    branch=c.get("branch"), is_test=is_test, actor=actor, action="bank.create")
        return mask_bank(row)

    return await _S._run_command(conn, command_key=command_key, action="bank_account", integration_id=None,
                                 payload_fp=fp, fn=_do)


async def clear_account(conn, *, expected_version: int, actor: str, command_key: str) -> dict:
    """CA 315-01: XOA (deactivate) tai khoan nhan hien hanh — explicit clear (blank/omitted KHONG phai clear).
    Deactivate active row (GIU row cho FK historical instruction — snapshot BAT BIEN). Sau clear KHONG co active bank
    -> generate_instruction fail-closed ('chua cau hinh tai khoan nhan'). CAS + command_key + audit redacted.
    Quyen secret_write (account-scoped, co the bat lai bang cach nhap account moi — khong phai purge vinh vien)."""
    fp = _S._payload_fp("bank_clear", None, {"v": expected_version})

    async def _do():
        prev = await conn.fetchrow("SELECT * FROM bank_accounts WHERE active FOR UPDATE")
        if not prev:
            raise _S.SettingsNotFound("khong co tai khoan bank active de xoa")
        if prev["version"] != expected_version:
            raise _S.SettingsConflict("version conflict (bank da doi) — tai lai")
        await conn.execute("UPDATE bank_accounts SET active=false, updated_at=now() WHERE id=$1", prev["id"])
        await audit_service.record(conn, actor_type="staff", action="bank.clear_account", actor_ref=actor,
                                   entity_type="bank_accounts", entity_id=str(prev["id"]),
                                   after={"cleared": True, "prev_version": prev["version"]})   # KHONG account
        return {"cleared": True, "prev_version": prev["version"]}

    return await _S._run_command(conn, command_key=command_key, action="bank_clear", integration_id=None,
                                 payload_fp=fp, fn=_do)
