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


def test_valid_allowlist_whitespace_dedupe_canonical(monkeypatch):
    # canonical IDs + whitespace + duplicate hop le -> canonical dedupe set (CA 289 §2.4)
    _set(monkeypatch, master=True, scope="tester", ids=" 1 , 2 ,1, 3 , 2 ,")
    assert S.allowlist_valid() is True and S.tester_ids() == {1, 2, 3}
    assert S.m7_enabled_for(1) and S.m7_enabled_for(3) and S.m7_enabled_for(4) is False


def test_malformed_allowlist_fail_closed_entirely(monkeypatch):
    # CA 289-01: BAT KY token rac nao -> toan bo allowlist rong, KHONG ai eligible (khong giu token dung).
    for bad in ("1,bad,2", "1,-5,2", "1,0,2", "1,2x", "1, abc ,2", "1,01,2", "1,+2,3", "1,1.0,2"):
        _set(monkeypatch, master=True, scope="tester", ids=bad)
        assert S.allowlist_valid() is False, bad
        assert S.tester_ids() == set(), bad
        # master ON + scope tester + malformed -> tat ca (ke ca token "dung" 1/2/3) deu False
        assert not any(S.m7_enabled_for(c) for c in (1, 2, 3, 5)), bad


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
    _set(monkeypatch, master=True, scope="tester", ids="7,7,3,5")
    rb = S.readback()
    assert rb["master"] is True and rb["scope"] == "tester" and rb["allowlist_valid"] is True
    assert rb["tester_count"] == 3  # {3,5,7}
    assert isinstance(rb["tester_hash"], str) and len(rb["tester_hash"]) == 12
    # no-leak = schema/key contract: readback KHONG mang raw allowlist value hay ID/PSID
    assert set(rb) == {"master", "scope", "allowlist_valid", "tester_count", "tester_hash"}
    for k in ("tester_ids", "ids", "customer_ids", "psid", "allowlist", "raw"):
        assert k not in rb


def test_readback_malformed_flags_invalid_no_leak(monkeypatch):
    # CA 289-01 §2.4: readback config malformed -> allowlist_valid False, 0 enrolled, khong lo raw value/IDs.
    _set(monkeypatch, master=True, scope="tester", ids="7,bad,3")
    rb = S.readback()
    assert rb["allowlist_valid"] is False and rb["tester_count"] == 0 and rb["tester_hash"] == ""
    assert set(rb) == {"master", "scope", "allowlist_valid", "tester_count", "tester_hash"}
    assert "7" not in str(rb.values()) and "bad" not in str(rb.values())


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
