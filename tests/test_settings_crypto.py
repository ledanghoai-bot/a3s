"""CA Directive 305 §4/§9 — settings integrations crypto (AES-256-GCM key ring + HMAC fp). CI-safe, no DB."""
import base64

import pytest

from app.config import settings
from app.services.settings import crypto as C


def _k():
    return base64.b64encode(b"\x01" * 32).decode()


def _k2():
    return base64.b64encode(b"\x02" * 32).decode()


def _set(monkeypatch, *, keys=None, current="k1", fp=True):
    keys = keys if keys is not None else f"k1:{_k()}"
    monkeypatch.setattr(settings, "config_enc_keys", keys)
    monkeypatch.setattr(settings, "config_enc_key_current", current)
    monkeypatch.setattr(settings, "config_secret_fp_key", base64.b64encode(b"\x09" * 32).decode() if fp else "")


_CTX = dict(integration_id=7, provider="ghn", key_name="token", version=1)


def test_roundtrip(monkeypatch):
    _set(monkeypatch)
    kid, nonce, ct = C.encrypt_secret("SECRET-TOKEN-abc", **_CTX)
    assert kid == "k1"
    assert C.decrypt_secret(ct, nonce, key_id=kid, **_CTX) == "SECRET-TOKEN-abc"


def test_aad_context_tamper_fails(monkeypatch):
    _set(monkeypatch)
    kid, nonce, ct = C.encrypt_secret("tok", **_CTX)
    # đổi bất kỳ field AAD nào (integration_id/provider/key_name/version) -> fail closed
    for bad in ({**_CTX, "integration_id": 8}, {**_CTX, "provider": "sepay"},
                {**_CTX, "key_name": "api_key"}, {**_CTX, "version": 2}):
        with pytest.raises(C.ConfigDecryptError):
            C.decrypt_secret(ct, nonce, key_id=kid, **bad)


def test_ciphertext_tamper_fails(monkeypatch):
    _set(monkeypatch)
    kid, nonce, ct = C.encrypt_secret("tok", **_CTX)
    bad = bytes([ct[0] ^ 0xFF]) + ct[1:]
    with pytest.raises(C.ConfigDecryptError):
        C.decrypt_secret(bad, nonce, key_id=kid, **_CTX)


def test_unknown_key_id_fails(monkeypatch):
    _set(monkeypatch)
    kid, nonce, ct = C.encrypt_secret("tok", **_CTX)
    with pytest.raises(C.ConfigDecryptError):
        C.decrypt_secret(ct, nonce, key_id="nope", **_CTX)


def test_missing_keyring_failclosed(monkeypatch):
    _set(monkeypatch, keys="")
    assert C.crypto_configured() is False
    with pytest.raises(C.ConfigCryptoNotConfigured):
        C.encrypt_secret("tok", **_CTX)


def test_current_not_in_ring_failclosed(monkeypatch):
    _set(monkeypatch, keys=f"k1:{_k()}", current="k9")
    assert C.crypto_configured() is False
    with pytest.raises(C.ConfigCryptoNotConfigured):
        C.encrypt_secret("tok", **_CTX)


def test_key_rotation_read_old_write_current(monkeypatch):
    # ghi bằng k1, thêm k2 làm current: vẫn decrypt row cũ (key_id=k1) qua key ring; ghi mới dùng k2.
    _set(monkeypatch, keys=f"k1:{_k()}", current="k1")
    kid1, n1, ct1 = C.encrypt_secret("old", **_CTX)
    assert kid1 == "k1"
    _set(monkeypatch, keys=f"k1:{_k()},k2:{_k2()}", current="k2")
    assert C.decrypt_secret(ct1, n1, key_id="k1", **_CTX) == "old"      # đọc row cũ bằng key cũ trong ring
    kid2, n2, ct2 = C.encrypt_secret("new", **_CTX)
    assert kid2 == "k2"                                                  # ghi mới bằng current
    assert C.decrypt_secret(ct2, n2, key_id="k2", **_CTX) == "new"


def test_fingerprint_keyed_deterministic(monkeypatch):
    _set(monkeypatch)
    a = C.fingerprint("0071000123456")
    b = C.fingerprint("0071000123456")
    assert a == b and len(a) == 64                       # deterministic, HMAC-SHA256 hex
    assert a != C.fingerprint("0071000123457")
    # đổi fp key -> fingerprint khác (keyed, không phải SHA raw)
    monkeypatch.setattr(settings, "config_secret_fp_key", base64.b64encode(b"\x0a" * 32).decode())
    assert C.fingerprint("0071000123456") != a


def test_fingerprint_missing_key_failclosed(monkeypatch):
    _set(monkeypatch, fp=False)
    with pytest.raises(C.ConfigCryptoNotConfigured):
        C.fingerprint("x")
