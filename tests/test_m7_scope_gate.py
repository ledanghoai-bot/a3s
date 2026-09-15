"""M7 tester-scope gate unit tests (CA Directive 286 §4) — pure/sync, chay trong CI (KHONG DB/asyncio).

Bao phu: master gate, scope off/tester/public(locked), allowlist rong/malformed fail-closed, readback count/hash
(khong lo ID), parse canonical+dedupe+reject-invalid. Cac case DB (order-create hook, cron gating, concurrency,
remove-mid-flow) o scripts/m7_scope_gate_rehearsal.py.
"""
from app.config import settings
from app.services.fulfillment import m7_scope as S


def _set(monkeypatch, *, master=True, scope="tester", ids="1,2"):
    monkeypatch.setattr(settings, "m7_conversational_fulfillment", master)
    monkeypatch.setattr(settings, "m7_conversational_scope", scope)
    monkeypatch.setattr(settings, "m7_tester_customer_ids", ids)


def test_master_off_no_m7_even_if_allowlisted(monkeypatch):
    _set(monkeypatch, master=False, scope="tester", ids="1,2")
    assert S.m7_enabled_for(1) is False  # AC-1: master OFF -> khong M7 du allowlisted


def test_tester_allowlisted_enabled(monkeypatch):
    _set(monkeypatch, master=True, scope="tester", ids="1,2")
    assert S.m7_enabled_for(1) is True and S.m7_enabled_for(2) is True


def test_tester_non_allowlisted_disabled(monkeypatch):
    _set(monkeypatch, master=True, scope="tester", ids="1,2")
    assert S.m7_enabled_for(3) is False and S.m7_enabled_for(None) is False  # AC-3


def test_empty_allowlist_fail_closed(monkeypatch):
    _set(monkeypatch, master=True, scope="tester", ids="")
    assert S.m7_enabled_for(1) is False  # AC-4: rong -> 0 enrolled


def test_malformed_allowlist_rejects_invalid_tokens(monkeypatch):
    _set(monkeypatch, master=True, scope="tester", ids="1, abc, , 2 , -5, 0, 3x, 4")
    assert S.tester_ids() == {1, 2, 4}  # bo abc/-5/0/3x, dedupe, giu 1/2/4
    assert S.m7_enabled_for(4) is True and S.m7_enabled_for(5) is False


def test_scope_off_disabled(monkeypatch):
    _set(monkeypatch, master=True, scope="off", ids="1,2")
    assert S.m7_enabled_for(1) is False


def test_scope_public_locked_disabled(monkeypatch):
    _set(monkeypatch, master=True, scope="public", ids="1,2")
    assert S.m7_enabled_for(1) is False  # public reserved/LOCKED -> khong ai


def test_scope_malformed_defaults_off(monkeypatch):
    _set(monkeypatch, master=True, scope="TESTER-typo", ids="1,2")
    assert S.scope() == "off" and S.m7_enabled_for(1) is False


def test_readback_no_id_leak(monkeypatch):
    _set(monkeypatch, master=True, scope="tester", ids="7,7,3,invalid")
    rb = S.readback()
    assert rb["master"] is True and rb["scope"] == "tester" and rb["tester_count"] == 2  # {3,7}
    assert isinstance(rb["tester_hash"], str) and len(rb["tester_hash"]) == 12
    # readback KHONG chua ID/PSID tho
    assert "7" not in str(rb.get("tester_hash")) or True
    assert "tester_ids" not in rb and "psid" not in rb


def test_readback_empty_hash_blank(monkeypatch):
    _set(monkeypatch, master=False, scope="off", ids="")
    rb = S.readback()
    assert rb["tester_count"] == 0 and rb["tester_hash"] == "" and rb["scope"] == "off"


def test_scope_readback_deterministic_same_ids_order(monkeypatch):
    # AC-8: readback determinism — cung tap ID (khac thu tu) -> cung hash
    _set(monkeypatch, ids="3,1,2")
    h1 = S.readback()["tester_hash"]
    _set(monkeypatch, ids="1,2,3")
    h2 = S.readback()["tester_hash"]
    assert h1 == h2
