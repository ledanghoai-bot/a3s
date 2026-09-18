"""CA Directive 305 §4 — crypto cho Shop Settings integrations: AES-256-GCM KEY RING + HMAC fingerprint.

Nguyen tac (theo mau app/services/pii/crypto.py, mo rong key ring cho rotation):
- Secret (GHN token, SePay key, account number) MA HOA o tang app truoc khi cham DB. DB chi giu ciphertext+tag +
  nonce + key_id + keyed fingerprint — KHONG BAO GIO plaintext.
- AAD (v1) = domain-tag + length-prefix canonical cua (integration_id, provider, key_name, version) -> mot row bi
  trao context (tamper DB / rotate nham) KHONG THE giai ma (fail closed tai crypto, khong phu thuoc query).
- KEY RING: `config_enc_keys` = "keyid:base64_32b,keyid2:...". `config_enc_key_current` = key_id GHI (write). Key cu chi
  DOC (rotation). Thieu/sai key / unknown key_id / auth-tag fail -> FAIL CLOSED (raise), message KHONG chua plaintext.
- Fingerprint = HMAC-SHA256 CO KHOA rieng (`config_secret_fp_key`) — TACH khoi encryption key (CA 304-01: khong SHA raw
  vi secret entropy thap co the doan offline).
- Key material CHI o env/secret manager, KHONG nhap qua Dashboard (CA 304-02).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import settings

_NONCE_LEN = 12
_KEY_LEN = 32
_TAG_LEN = 16
_MAX_FIELD = 128


class ConfigCryptoError(Exception):
    """Loi crypto chung — message KHONG BAO GIO chua plaintext secret."""


class ConfigCryptoNotConfigured(ConfigCryptoError):
    """Thieu/sai key ring hoac fp key — fail closed, khong luu/doc secret."""


class ConfigDecryptError(ConfigCryptoError):
    """Giai ma that bai (unknown key_id / auth-tag / blob sai) — nghi tamper/rotate nham."""


def _b64key(value: str, name: str) -> bytes:
    try:
        key = base64.b64decode(value, validate=True)
    except Exception as e:  # noqa: BLE001
        raise ConfigCryptoNotConfigured(f"{name} khong phai base64 hop le") from e
    if len(key) != _KEY_LEN:
        raise ConfigCryptoNotConfigured(f"{name} phai la {_KEY_LEN} byte sau decode")
    return key


def _key_ring() -> dict[str, bytes]:
    """Parse config_enc_keys -> {key_id: 32-byte}. Rong -> fail closed."""
    raw = (settings.config_enc_keys or "").strip()
    if not raw:
        raise ConfigCryptoNotConfigured("config_enc_keys chua cau hinh")
    ring: dict[str, bytes] = {}
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        if ":" not in item:
            raise ConfigCryptoNotConfigured("config_enc_keys sai dinh dang (can 'keyid:base64')")
        kid, b64 = item.split(":", 1)
        kid = kid.strip()
        if not kid:
            raise ConfigCryptoNotConfigured("config_enc_keys co key_id rong")
        ring[kid] = _b64key(b64.strip(), f"config_enc_keys[{kid}]")
    if not ring:
        raise ConfigCryptoNotConfigured("config_enc_keys rong sau parse")
    return ring


def current_key_id() -> str:
    kid = (settings.config_enc_key_current or "").strip()
    if not kid:
        raise ConfigCryptoNotConfigured("config_enc_key_current chua cau hinh")
    if kid not in _key_ring():
        raise ConfigCryptoNotConfigured("config_enc_key_current khong nam trong key ring")
    return kid


def _fp_key() -> bytes:
    v = (settings.config_secret_fp_key or "").strip()
    if not v:
        raise ConfigCryptoNotConfigured("config_secret_fp_key chua cau hinh")
    return _b64key(v, "config_secret_fp_key")


def _field(value, name: str) -> bytes:
    s = str(value)
    raw = s.encode("utf-8")
    if not raw or len(raw) > _MAX_FIELD or any(b < 0x20 for b in raw):
        raise ConfigCryptoError(f"{name} rong/qua dai/ky tu control")
    return raw


def _aad(*, integration_id: int, provider: str, key_name: str, version: int) -> bytes:
    """Canonical length-prefix AAD — khong 2 bo (integration_id, provider, key_name, version) khac nhau cho cung byte."""
    parts = (_field(integration_id, "integration_id"), _field(provider, "provider"),
             _field(key_name, "key_name"), _field(version, "version"))
    out = [b"a3s-settings-integration-secret-aad-v1"]
    for p in parts:
        out.append(len(p).to_bytes(4, "big"))
        out.append(p)
    return b"".join(out)


def encrypt_secret(plaintext: str, *, integration_id: int, provider: str, key_name: str,
                   version: int) -> tuple[str, bytes, bytes]:
    """Ma hoa bang CURRENT key. Tra (key_id, nonce, ciphertext[ct+tag]). Bind AAD."""
    if not isinstance(plaintext, str) or plaintext == "":
        raise ConfigCryptoError("plaintext secret rong")
    kid = current_key_id()
    key = _key_ring()[kid]
    nonce = os.urandom(_NONCE_LEN)
    ct = AESGCM(key).encrypt(nonce, plaintext.encode("utf-8"),
                             _aad(integration_id=integration_id, provider=provider, key_name=key_name, version=version))
    return kid, nonce, ct


def decrypt_secret(ciphertext: bytes, nonce: bytes, *, key_id: str, integration_id: int, provider: str,
                   key_name: str, version: int) -> str:
    """Giai ma bang key_id da ghi (rotation doc key cu). Unknown key_id / auth-tag fail -> ConfigDecryptError."""
    ring = _key_ring()
    key = ring.get(key_id)
    if key is None:
        raise ConfigDecryptError("key_id khong co trong key ring (fail closed)")
    if not nonce or len(nonce) != _NONCE_LEN or not ciphertext or len(ciphertext) < _TAG_LEN:
        raise ConfigDecryptError("nonce/ciphertext sai dinh dang")
    try:
        pt = AESGCM(key).decrypt(bytes(nonce), bytes(ciphertext),
                                 _aad(integration_id=integration_id, provider=provider, key_name=key_name,
                                      version=version))
    except InvalidTag as e:
        raise ConfigDecryptError("auth-tag/AAD khong khop (tamper hoac rotate nham)") from e
    return pt.decode("utf-8")


def fingerprint(plaintext: str) -> str:
    """HMAC-SHA256 keyed (CA 304-01) — 64 hex. Deterministic theo key; khong suy nguoc duoc neu khong co key."""
    return hmac.new(_fp_key(), plaintext.encode("utf-8"), hashlib.sha256).hexdigest()


def crypto_configured() -> bool:
    """True <=> key ring + current key + fp key deu hop le (dung cho readback source/health, KHONG lo key)."""
    try:
        current_key_id()
        _fp_key()
        return True
    except ConfigCryptoError:
        return False
