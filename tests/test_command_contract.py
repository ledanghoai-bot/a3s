"""Unit tests cho command bus domain contract (I-B M1). Spec §6, §9.2, §13.1.

Thuan tuy — khong DB/HTTP. Map AC-M1-01/03/04/07 (envelope, idempotency, hash, receipt) + classifier.
"""
import pytest

from app.services.command import (
    Actor,
    CommandError,
    build_order_create_envelope,
    errors,
    hashing,
    idempotency,
    receipt,
    redaction,
    registry,
    retry,
)

VALID_RAW = {
    "customer_name": "Nguyen Van A",
    "phone": "0912345678",
    "address": "12 Le Loi, Q1, HCM",
    "sku": "3S-100G",
    "quantity": 1,
}


# ---------------- canonical hash (§6.1) ----------------

def test_canonical_json_key_order_independent():
    a = hashing.canonical_json({"b": 1, "a": 2, "c": [3, 2, 1]})
    b = hashing.canonical_json({"c": [3, 2, 1], "a": 2, "b": 1})
    assert a == b == '{"a":2,"b":1,"c":[3,2,1]}'


def test_request_hash_is_64_hex_and_stable_under_normalization():
    raw2 = dict(VALID_RAW, customer_name="  Nguyen Van A ", phone="09 1234-5678")
    n1 = registry.validate_order_create_payload(VALID_RAW)
    n2 = registry.validate_order_create_payload(raw2)
    h1 = registry.compute_request_hash("order.create", 1, registry.order_create_hash_input(n1))
    h2 = registry.compute_request_hash("order.create", 1, registry.order_create_hash_input(n2))
    assert h1 == h2
    assert len(h1) == 64 and all(c in "0123456789abcdef" for c in h1)


def test_request_hash_changes_on_business_field_change():
    base = registry.order_create_hash_input(registry.validate_order_create_payload(VALID_RAW))
    h = registry.compute_request_hash("order.create", 1, base)
    for field, val in [("sku", "3S-500G"), ("quantity", 2), ("phone", "0987654321")]:
        other = registry.validate_order_create_payload(dict(VALID_RAW, **{field: val}))
        h2 = registry.compute_request_hash("order.create", 1, registry.order_create_hash_input(other))
        assert h2 != h, f"hash phai doi khi {field} doi"


# ---------------- payload validation (§6, 422) ----------------

def test_validate_rejects_bad_quantity():
    with pytest.raises(CommandError) as e:
        registry.validate_order_create_payload(dict(VALID_RAW, quantity=0))
    assert e.value.code == errors.INVALID_QUANTITY
    with pytest.raises(CommandError):
        registry.validate_order_create_payload(dict(VALID_RAW, quantity=True))  # bool != int


def test_validate_rejects_bad_phone():
    with pytest.raises(CommandError) as e:
        registry.validate_order_create_payload(dict(VALID_RAW, phone="12345"))
    assert e.value.code == errors.INVALID_PHONE


def test_validate_rejects_missing_fields():
    for field in ("customer_name", "address", "sku"):
        with pytest.raises(CommandError) as e:
            registry.validate_order_create_payload(dict(VALID_RAW, **{field: "  "}))
        assert e.value.code == errors.INVALID_ENVELOPE


# ---------------- envelope (§6.1) ----------------

def test_build_envelope_valid():
    env = build_order_create_envelope(
        raw_payload=VALID_RAW, actor=Actor("staff", "7"), channel="dashboard",
        idempotency_key="a" * 16, customer_id=5,
    )
    assert env.command_type == "order.create" and env.command_version == 1
    assert env.idempotency_scope == "order.create:dashboard:7"
    assert len(env.request_hash) == 64
    # stored payload: masked phone, KHONG address raw
    assert env.stored_payload["phone_masked"] == "***678"
    assert "address" not in env.stored_payload
    # full payload (in-mem) van co address de service mutate
    assert env.payload["address"] == "12 Le Loi, Q1, HCM"
    # insert params map dung cot + request_payload = stored
    params = env.as_insert_params()
    assert params["request_payload"] == env.stored_payload
    assert params["status"] == "accepted" and params["actor_id"] == "7"


def test_build_envelope_rejects_bad_channel_and_actor():
    with pytest.raises(CommandError):
        build_order_create_envelope(raw_payload=VALID_RAW, actor=Actor("staff", "7"),
                                    channel="sms", idempotency_key="a" * 16)
    with pytest.raises(CommandError):
        build_order_create_envelope(raw_payload=VALID_RAW, actor=Actor("robot", "7"),
                                    channel="dashboard", idempotency_key="a" * 16)


def test_build_envelope_generates_ids_and_propagates_business_error():
    env = build_order_create_envelope(
        raw_payload=VALID_RAW, actor=Actor("customer", "psid-1"), channel="messenger",
        idempotency_key="k" * 20,
    )
    assert len(env.command_id) == 36 and len(env.correlation_id) == 36  # uuid4
    with pytest.raises(CommandError) as e:
        build_order_create_envelope(raw_payload=dict(VALID_RAW, quantity=-1),
                                    actor=Actor("customer", "psid-1"), channel="messenger",
                                    idempotency_key="k" * 20)
    assert e.value.code == errors.INVALID_QUANTITY


# ---------------- idempotency (§6.2) ----------------

def test_validate_api_key():
    with pytest.raises(CommandError) as e:
        idempotency.validate_api_key(None)
    assert e.value.code == errors.IDEMPOTENCY_KEY_REQUIRED
    with pytest.raises(CommandError) as e:
        idempotency.validate_api_key("short")
    assert e.value.code == errors.IDEMPOTENCY_KEY_INVALID
    with pytest.raises(CommandError):
        idempotency.validate_api_key("has space and !!" + "x" * 10)
    assert idempotency.validate_api_key("ABCdef0123456789._:-") == "ABCdef0123456789._:-"


def test_ai_stable_key_deterministic():
    k1 = idempotency.ai_stable_key(channel="messenger", provider_message_id="mid1",
                                   tool_call_id="tc1", command_type="order.create", version=1)
    k2 = idempotency.ai_stable_key(channel="messenger", provider_message_id="mid1",
                                   tool_call_id="tc1", command_type="order.create", version=1)
    k3 = idempotency.ai_stable_key(channel="messenger", provider_message_id="mid2",
                                   tool_call_id="tc1", command_type="order.create", version=1)
    assert k1 == k2 and k1 != k3 and len(k1) == 64


# ---------------- retry classifier + backoff (§9.2, §8.2) ----------------

@pytest.mark.parametrize("status,outcome,cred", [
    (200, retry.DELIVERED, False), (204, retry.DELIVERED, False),
    (408, retry.RETRYABLE, False), (425, retry.RETRYABLE, False), (429, retry.RETRYABLE, False),
    (500, retry.RETRYABLE, False), (503, retry.RETRYABLE, False),
    (400, retry.TERMINAL, False), (404, retry.TERMINAL, False), (422, retry.TERMINAL, False),
    (401, retry.TERMINAL, True), (403, retry.TERMINAL, True),
    (418, retry.TERMINAL, False),
])
def test_classify_http(status, outcome, cred):
    assert retry.classify_http(status) == (outcome, cred)


def test_classify_exception_and_should_retry():
    assert retry.classify_exception(is_timeout=True) == retry.UNKNOWN
    assert retry.classify_exception(is_timeout=False) == retry.RETRYABLE
    assert retry.should_retry(7, retry.RETRYABLE) is True
    assert retry.should_retry(8, retry.RETRYABLE) is False
    assert retry.should_retry(3, retry.UNKNOWN) is True
    assert retry.should_retry(1, retry.TERMINAL) is False


def test_backoff_bounds():
    assert retry.backoff_seconds(1, rng=lambda: 0.0) == 0.0
    assert 0.0 <= retry.backoff_seconds(1, rng=lambda: 0.5) < retry.BASE_SECONDS
    # attempt lon -> exp cap tai CAP_SECONDS
    assert retry.backoff_seconds(100, rng=lambda: 0.5) == pytest.approx(retry.CAP_SECONDS * 0.5)
    # Retry-After uu tien + cap 24h
    assert retry.backoff_seconds(1, retry_after=10) == 10
    assert retry.backoff_seconds(1, retry_after=100000) == retry.RETRY_AFTER_CAP_SECONDS


# ---------------- receipt (§6.4) ----------------

def test_receipt_succeeded_and_customer_message():
    r = receipt.build_order_create_receipt(
        command_id="11111111-1111-1111-1111-111111111111",
        correlation_id="c-1", outcome=receipt.SUCCEEDED,
        result_payload={"order_id": 123, "status": "new", "sku": "3S-100G",
                        "quantity": 1, "unit_price_vnd": 170000, "total_vnd": 170000},
        committed_at="2026-07-26T00:00:00Z",
    )
    assert r.receipt_id == "cmd_11111111-1111-1111-1111-111111111111"
    assert r.resource == {"type": "order", "id": 123, "display_id": "#123"}
    assert r.result["total_vnd"] == 170000
    assert receipt.customer_message(r) == "Đơn #123 đã được ghi nhận: 1 × 3S-100G, tổng 170.000đ."


def test_receipt_in_progress_no_amount_leak():
    r = receipt.build_order_create_receipt(
        command_id="x", correlation_id="c", outcome=receipt.IN_PROGRESS,
        result_payload=None, committed_at=None,
    )
    msg = receipt.customer_message(r)
    assert "170" not in msg and r.resource is None


def test_format_vnd():
    assert receipt.format_vnd(170000) == "170.000đ"
    assert receipt.format_vnd(0) == "0đ"
    assert receipt.format_vnd(1234567) == "1.234.567đ"


# ---------------- redaction (§7.4, §11.2) ----------------

def test_mask_phone():
    assert redaction.mask_phone("0912345678") == "***678"
    assert redaction.mask_phone("12") == "***"
    assert redaction.mask_phone(None) is None
    assert redaction.mask_phone("") == ""


def test_redact_generic_nested():
    out = redaction.redact_generic({
        "password": "secret", "phone": "0912345678", "ok": 1,
        "nested": {"token": "t", "keep": "v"}, "list": [{"api_key": "z"}],
    })
    assert out["password"] == "***REDACTED***"
    assert out["phone"] == "***REDACTED***"
    assert out["ok"] == 1
    assert out["nested"]["token"] == "***REDACTED***" and out["nested"]["keep"] == "v"
    assert out["list"][0]["api_key"] == "***REDACTED***"
