"""M5 upgrade (CA Review 216-01): verified_resolution_id PHAI vao request_hash + stored_payload de
duplicate/conflict detection phan biet cung order nhung resolution KHAC. KHONG luu dia chi raw.
"""
from app.services.command.envelope import Actor, build_order_create_envelope

_RAW = {"customer_name": "Khach Test", "phone": "0900000000", "address": "31 Duong X, P. Ea Kao, Dak Lak",
        "sku": "SP1", "quantity": 2}


def _env(resolution_id):
    return build_order_create_envelope(
        raw_payload=dict(_RAW), actor=Actor("customer", "tg:1"), channel="telegram_customer",
        idempotency_key="k1", verified_resolution_id=resolution_id)


def test_hash_differs_by_resolution():
    # Cung order payload + idempotency key, resolution KHAC -> request_hash KHAC -> se conflict (216-01 #2).
    h_a = _env("R-AAAA").request_hash
    h_b = _env("R-BBBB").request_hash
    assert h_a != h_b


def test_hash_stable_same_resolution():
    # Cung order + cung resolution -> hash on dinh -> duplicate receipt (216-01 #1).
    assert _env("R-AAAA").request_hash == _env("R-AAAA").request_hash


def test_hash_none_resolution_matches_legacy():
    # Khong resolution -> hash khong doi so voi legacy (khong resolution) -> backward compatible.
    from app.services.command import registry
    legacy = registry.compute_request_hash(
        registry.ORDER_CREATE, registry.ORDER_CREATE_VERSION,
        registry.order_create_hash_input(registry.validate_order_create_payload(dict(_RAW))))
    assert _env(None).request_hash == legacy


def test_stored_payload_has_resolution_no_raw_address():
    env = _env("R-AAAA")
    assert env.stored_payload.get("verified_resolution_id") == "R-AAAA"
    # 216-01 + Memo 213: KHONG dia chi raw trong request_payload persisted
    assert "address" not in env.stored_payload
    assert "31 Duong X" not in str(env.stored_payload)
