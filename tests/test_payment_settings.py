"""CA Directive 306 + Review 308 — Payment Settings + SePay S0.

CI-safe (TestClient, no DB): RBAC deny per-action, module-OFF 404 (308-03), VietQR no-silent-substitute (308-05).
DB (skipif): SePay readiness TRUNG THUC + negatives (308-02), bank field-level CAS/omitted-keeps/invalid-fail (308-01).
"""
import base64
import os

import pytest
from fastapi.testclient import TestClient

from app.api.auth import require_staff_session
from app.config import settings
from app.main import app
from app.services.settings import integrations as S


# ---------- pure ----------
def test_vietqr_self_test_ok_and_fail():
    r = S.vietqr_self_test(bin_code="970415", account_number="0071000123456", amount_vnd=10000, add_info="3SCF 42")
    assert r["ok"] is True and r["crc_valid"] is True and r["account_last4"] == "3456"
    bad = S.vietqr_self_test(bin_code="", account_number="x", amount_vnd=-1, add_info="")
    assert bad["ok"] is False and "error_class" in bad


# ---------- RBAC + module gate (CI-safe) ----------
def _client(perms, *, module_on=True):
    async def _fake():
        return {"id": 1, "username": "t", "rbac_provisioned": True, "permissions": set(perms)}
    app.dependency_overrides[require_staff_session] = _fake
    settings.settings_integrations_enabled = module_on
    return TestClient(app, raise_server_exceptions=False)


def _clear():
    app.dependency_overrides.pop(require_staff_session, None)
    settings.settings_integrations_enabled = False


_EP = [
    ("get", "/dashboard/settings/payments", None, "settings.integration.view"),
    ("post", "/dashboard/settings/payments/bank/public", {"expected_version": 1, "command_key": "k", "bank": "b"}, "settings.integration.manage_public"),
    ("post", "/dashboard/settings/payments/bank/account", {"expected_version": 1, "command_key": "k", "account_number": "0071000123456"}, "settings.integration.secret_write"),
    ("post", "/dashboard/settings/payments/vietqr-self-test", {"amount_vnd": 10000, "order_id": 1}, "settings.integration.test"),
]


@pytest.mark.parametrize("method,path,body,perm", _EP)
def test_payment_deny_without_perm(method, path, body, perm):
    c = _client([])
    try:
        r = getattr(c, method)(path, json=body) if body is not None else getattr(c, method)(path)
        assert r.status_code == 403, f"{path} nen 403 khi thieu {perm}, duoc {r.status_code}"
    finally:
        _clear()


@pytest.mark.parametrize("method,path,body", [(m, p, b) for (m, p, b, _) in _EP])
def test_payment_module_off_404(method, path, body):
    allp = ["settings.integration.view", "settings.integration.manage_public", "settings.integration.secret_write",
            "settings.integration.test"]
    c = _client(allp, module_on=False)
    try:
        r = getattr(c, method)(path, json=body) if body is not None else getattr(c, method)(path)
        assert r.status_code == 404, f"module OFF: {path} phai 404, duoc {r.status_code}"
    finally:
        _clear()


# 308-05: VietQR KHONG silent-substitute — amount/order_id sai kieu/thieu -> 422 (khong ep 10000/0).
@pytest.mark.parametrize("body", [
    {"order_id": 1},                       # thieu amount
    {"amount_vnd": "x", "order_id": 1},    # amount sai kieu
    {"amount_vnd": 0, "order_id": 1},      # amount <= 0
    {"amount_vnd": 10000},                 # thieu order_id
    {"amount_vnd": 10000, "order_id": 0},  # order_id < 1
])
def test_vietqr_rejects_invalid_input_422(body):
    c = _client(["settings.integration.test"])
    try:
        r = c.post("/dashboard/settings/payments/vietqr-self-test", json=body)
        assert r.status_code == 422, f"input sai phai 422 (khong ep), duoc {r.status_code}: {body}"
    finally:
        _clear()


# ---------- DB ----------
DB = os.environ.get("M6_TEST_DB") == "1"


def _crypto(monkeypatch):
    monkeypatch.setattr(settings, "config_enc_keys", f"k1:{base64.b64encode(b'A'*32).decode()}")
    monkeypatch.setattr(settings, "config_enc_key_current", "k1")
    monkeypatch.setattr(settings, "config_secret_fp_key", base64.b64encode(b'F'*32).decode())


async def _conn():
    import asyncpg
    return await asyncpg.connect(os.environ["DATABASE_URL"].replace("+asyncpg", ""))


def _ck():
    return "pt-" + os.urandom(8).hex()


@pytest.mark.skipif(not DB, reason="can DB")
@pytest.mark.asyncio
async def test_sepay_readiness_honest_and_negatives(monkeypatch):
    """308-02: readiness TRUNG THUC — not authenticated; negatives key_format / allowed_accounts_missing."""
    _crypto(monkeypatch)
    conn = await _conn()
    iid = None
    try:
        async with conn.transaction():
            it = await S.create_integration(conn, kind="payment", provider="sepay", label="SP", mode="test",
                                            config_public={"code_prefix": "3SCF"}, actor="po", command_key=_ck())
        iid = it["id"]
        # chua co key -> not_configured
        r0 = await S.sepay_readiness(conn, iid, actor="po")
        assert r0["ok"] is False and r0["error_class"] == "not_configured"
        # key qua ngan/malformed -> key_format fail
        d = await S.get_integration(conn, iid)
        async with conn.transaction():
            await S.write_secret(conn, iid, key_name="api_key", plaintext="short", expected_version=d["version"],
                                 actor="po", command_key=_ck())
        r1 = await S.sepay_readiness(conn, iid, actor="po")
        assert r1["ok"] is False and r1["error_class"] == "key_format"
        # key hop dinh dang nhung THIEU allowed_accounts -> allowed_accounts_missing
        d = await S.get_integration(conn, iid)
        async with conn.transaction():
            await S.write_secret(conn, iid, key_name="api_key", plaintext="SEPAYTESTKEY_abc123456789",
                                 expected_version=d["version"], actor="po", command_key=_ck())
        r2 = await S.sepay_readiness(conn, iid, actor="po")
        assert r2["ok"] is False and r2["error_class"] == "allowed_accounts_missing"
        # du cau hinh -> pass NHUNG authenticated=False (trung thuc)
        d = await S.get_integration(conn, iid)
        async with conn.transaction():
            await S.update_public(conn, iid, label=None, config_public={"code_prefix": "3SCF",
                                  "allowed_accounts": "0071000123456"}, expected_version=d["version"], actor="po",
                                  command_key=_ck())
        # update_public xoa last_test + secret van con -> can ghi lai secret? khong; readiness doc secret hien co.
        r3 = await S.sepay_readiness(conn, iid, actor="po")
        assert r3["ok"] is True and r3["authenticated"] is False and r3["verified"].startswith("stored")
    finally:
        if iid:
            async with conn.transaction():
                await conn.execute("DELETE FROM integration_commands WHERE integration_id=$1", iid)
                await conn.execute("DELETE FROM integration_secrets WHERE integration_id=$1", iid)
                await conn.execute("DELETE FROM integrations WHERE id=$1", iid)
        await conn.close()


@pytest.mark.skipif(not DB, reason="can DB")
@pytest.mark.asyncio
async def test_bank_field_level_cas_and_validation(monkeypatch):
    """308-01: create (secret_write) + update_public omitted-keeps + CAS conflict + invalid bin/account fail-before."""
    _crypto(monkeypatch)
    from app.services.settings import payment_bank as B
    conn = await _conn()
    try:
        await conn.execute("UPDATE bank_accounts SET active=false WHERE active")
        # invalid account -> fail TRUOC mutation
        with pytest.raises(B.BankSettingsError):
            async with conn.transaction():
                await B.replace_account(conn, account_number="abc", expected_version=0, actor="po", command_key=_ck())
        # create (chua co active) qua account path
        async with conn.transaction():
            m = await B.replace_account(conn, account_number="0071000123456", expected_version=0, actor="po",
                                        command_key=_ck(), create={"bank": "VCB", "holder_name": "H", "bin": "970415"})
        assert m["account_last4"] == "3456" and m["version"] >= 1
        v = m["version"]
        # invalid bin qua public -> fail TRUOC mutation
        with pytest.raises(B.BankSettingsError):
            async with conn.transaction():
                await B.update_public(conn, fields={"bin": "12"}, expected_version=v, actor="po", command_key=_ck())
        # update_public omitted-keeps: doi holder, GIU account
        async with conn.transaction():
            m2 = await B.update_public(conn, fields={"holder_name": "NEW HOLDER"}, expected_version=v, actor="po",
                                       command_key=_ck())
        assert m2["holder_name"] == "NEW HOLDER" and m2["account_last4"] == "3456" and m2["version"] == v + 1
        # CAS: dung expected_version cu -> conflict
        with pytest.raises(S.SettingsConflict):
            async with conn.transaction():
                await B.update_public(conn, fields={"holder_name": "X"}, expected_version=v, actor="po",
                                      command_key=_ck())
    finally:
        await conn.execute("UPDATE bank_accounts SET active=false WHERE active")
        await conn.close()


@pytest.mark.skipif(not DB, reason="can DB")
@pytest.mark.asyncio
async def test_bank_type_validation_reject_before_mutation(monkeypatch):
    """315-04: is_test phai boolean that (khong ep 'false'->True); bank sai kieu -> reject."""
    _crypto(monkeypatch)
    from app.services.settings import payment_bank as B
    conn = await _conn()
    try:
        await conn.execute("UPDATE bank_accounts SET active=false WHERE active")
        async with conn.transaction():
            m = await B.replace_account(conn, account_number="0071000123456", expected_version=0, actor="po",
                                        command_key=_ck(), create={"bank": "VCB", "holder_name": "H"})
        v = m["version"]
        with pytest.raises(B.BankSettingsError):   # is_test chuoi "false"
            async with conn.transaction():
                await B.update_public(conn, fields={"is_test": "false"}, expected_version=v, actor="po",
                                      command_key=_ck())
        with pytest.raises(B.BankSettingsError):   # bank sai kieu
            async with conn.transaction():
                await B.update_public(conn, fields={"bank": 123}, expected_version=v, actor="po", command_key=_ck())
    finally:
        await conn.execute("UPDATE bank_accounts SET active=false WHERE active")
        await conn.close()


@pytest.mark.skipif(not DB, reason="can DB")
@pytest.mark.asyncio
async def test_bank_clear_explicit_historical_immutable(monkeypatch):
    """315-01: explicit clear deactivate active; historical instruction snapshot BAT BIEN; instruction moi fail-closed."""
    _crypto(monkeypatch)
    import time as _t

    from app.services.payment import payment_service as PS
    from app.services.settings import payment_bank as B
    conn = await _conn()
    oid = None
    try:
        tag = f"BC-{int(_t.time()*1000)}"
        cid = await conn.fetchval("INSERT INTO customers(psid,name,phone) VALUES($1,'T','0900000000') RETURNING id",
                                  f"tg:{tag}")
        pidp = await conn.fetchval("INSERT INTO products(sku,name,price_vnd,stock,shipping_weight_g,sales_unit) "
                                   "VALUES($1,'CF',100000,999,300,'hu') RETURNING id", tag)
        oid = await conn.fetchval("INSERT INTO orders(customer_id,status,total_vnd,origin_channel) "
                                  "VALUES($1,'confirmed',230000,'telegram_customer') RETURNING id", cid)
        await conn.execute("INSERT INTO order_items(order_id,product_id,quantity,unit_price_vnd) VALUES($1,$2,1,230000)",
                           oid, pidp)
        await conn.execute("INSERT INTO payments(order_id,method,amount_due_vnd,status) "
                           "VALUES($1,'BANK_TRANSFER',230000,'awaiting')", oid)
        await conn.execute("UPDATE bank_accounts SET active=false WHERE active")
        async with conn.transaction():
            m = await B.replace_account(conn, account_number="0071000123456", expected_version=0, actor="po",
                                        command_key=_ck(), create={"bank": "VCB", "holder_name": "H", "bin": "970415"})
        # phat instruction (snapshot account)
        instr = await PS.generate_instruction(conn, oid, actor="t", command_key=f"{tag}:i")
        snap_before = await conn.fetchval("SELECT account_number_snapshot FROM payment_instructions WHERE id=$1",
                                          instr["id"])
        # clear (explicit) -> deactivate
        async with conn.transaction():
            r = await B.clear_account(conn, expected_version=m["version"], actor="po", command_key=_ck())
        assert r["cleared"] is True
        assert await B.get_active_bank(conn) is None   # khong con active
        # historical instruction snapshot BAT BIEN
        snap_after = await conn.fetchval("SELECT account_number_snapshot FROM payment_instructions WHERE id=$1",
                                         instr["id"])
        assert snap_after == snap_before == "0071000123456"
        # instruction MOI fail-closed (chua co active bank)
        with pytest.raises(PS.PaymentError):
            await PS.generate_instruction(conn, oid, actor="t", command_key=f"{tag}:i2")
        # clear lan 2 (khong con active) -> NotFound
        with pytest.raises(S.SettingsNotFound):
            async with conn.transaction():
                await B.clear_account(conn, expected_version=m["version"], actor="po", command_key=_ck())
    finally:
        await conn.execute("UPDATE bank_accounts SET active=false WHERE active")
        await conn.close()


@pytest.mark.skipif(not DB, reason="can DB")
@pytest.mark.asyncio
async def test_concurrent_bank_update_one_win(monkeypatch):
    """315-04: hai update_public dong thoi cung expected_version -> dung 1 thang, 1 conflict, 1 active row."""
    import asyncio
    _crypto(monkeypatch)
    from app.services.settings import payment_bank as B
    setup = await _conn()
    c1 = await _conn()
    c2 = await _conn()
    try:
        await setup.execute("UPDATE bank_accounts SET active=false WHERE active")
        async with setup.transaction():
            m = await B.replace_account(setup, account_number="0071000123456", expected_version=0, actor="po",
                                        command_key=_ck(), create={"bank": "VCB", "holder_name": "H"})
        v = m["version"]

        async def _upd(cc, name):
            try:
                async with cc.transaction():
                    return await B.update_public(cc, fields={"holder_name": name}, expected_version=v, actor="po",
                                                 command_key=_ck())
            except S.SettingsError:
                return "conflict"
        r1, r2 = await asyncio.gather(_upd(c1, "A"), _upd(c2, "B"))
        assert [r1, r2].count("conflict") == 1, f"phai dung 1 conflict, {r1},{r2}"
        n_active = await setup.fetchval("SELECT count(*) FROM bank_accounts WHERE active")
        assert n_active == 1
    finally:
        await setup.execute("UPDATE bank_accounts SET active=false WHERE active")
        await setup.close()
        await c1.close()
        await c2.close()
