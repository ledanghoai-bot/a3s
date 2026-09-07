"""M5 upgrade (Directive 214 §6.C + Q3): _maybe_bind_gate_e phai bind resolution REQUEST-SCOPED
(env.verified_resolution_id) va FAIL-CLOSED khi khong co — KHONG con doc customers.current_address_
resolution_id (pointer cu) -> sua F2 (dia chi request fail thi khong bind pointer cu khac phuong).

Test THUAN logic quyet dinh: bind_in_order_tx bi monkeypatch thanh recorder, settings monkeypatch,
conn=None (khong con doc DB trong _maybe_bind_gate_e). Chay async qua asyncio.run (repo khong dung
pytest-asyncio).
"""
import asyncio

import pytest

from app.config import settings
from app.services.address import order_binding
from app.services.command import order_service
from app.services.command.envelope import Actor


class _Env:
    def __init__(self, verified_resolution_id):
        self.verified_resolution_id = verified_resolution_id
        self.command_id = "cmd-test"
        self.actor = Actor("customer", "tg:5913051767")


def _setup(monkeypatch, *, gate_e=True, kill=False, scope="1"):
    monkeypatch.setattr(settings, "enable_gate_e_order_wiring", gate_e)
    monkeypatch.setattr(settings, "gate_e_kill_switch", kill)
    monkeypatch.setattr(settings, "gate_e_canary_customer_ids", scope)
    calls = []

    async def _rec(conn, *, order_id, resolution_id, actor, reason, ticket):
        calls.append({"order_id": order_id, "resolution_id": resolution_id})

    monkeypatch.setattr(order_binding, "bind_in_order_tx", _rec)
    return calls


def test_binds_request_scoped_resolution(monkeypatch):
    calls = _setup(monkeypatch)
    asyncio.run(order_service._maybe_bind_gate_e(None, _Env("R-NEW"), 5, 1))
    assert len(calls) == 1
    assert calls[0]["resolution_id"] == "R-NEW" and calls[0]["order_id"] == 5


def test_fail_closed_without_request_resolution(monkeypatch):
    # F2 core: khong co verified_resolution_id (dia chi request chua verify) -> BindingError, KHONG bind.
    # Truoc day doc customers.current_address_resolution_id -> bind nham resolution phuong CU.
    calls = _setup(monkeypatch)
    with pytest.raises(order_binding.BindingError):
        asyncio.run(order_service._maybe_bind_gate_e(None, _Env(None), 5, 1))
    assert calls == []


def test_out_of_scope_passthrough(monkeypatch):
    calls = _setup(monkeypatch, scope="999")
    asyncio.run(order_service._maybe_bind_gate_e(None, _Env("R-NEW"), 5, 1))
    assert calls == []  # ngoai canary scope -> legacy passthrough, khong bind


def test_kill_switch_blocks(monkeypatch):
    calls = _setup(monkeypatch, kill=True)
    asyncio.run(order_service._maybe_bind_gate_e(None, _Env("R-NEW"), 5, 1))
    assert calls == []


def test_gate_e_off_passthrough(monkeypatch):
    calls = _setup(monkeypatch, gate_e=False)
    asyncio.run(order_service._maybe_bind_gate_e(None, _Env("R-NEW"), 5, 1))
    assert calls == []
