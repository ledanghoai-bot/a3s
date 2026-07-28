"""I-B M4-S1 — crypto cho Trusted Slot Store: AES-256-GCM + AAD context binding.

Nguyen tac (spec §5/§8):
- Gia tri slot MA HOA O TANG APP truoc khi cham DB. AAD (associated data) =
  customer_ref|conversation_ref|slot_type -> mot row bi trao sang context khac
  (tamper truc tiep DB, retry/replay bind nham) se KHONG THE giai ma: fail closed
  ngay tai tang crypto, khong phu thuoc query filter dung hay sai.
- Fingerprint = HMAC-SHA256 CO KHOA cua gia tri da chuan hoa: dung de dedupe
  replay trong CUNG context; khong co khoa thi khong the suy nguoc/doi chieu
  -> KHONG phai public identifier (§8).
- Khoa doc tu settings (base64, 32 byte). THIEU KHOA = FAIL CLOSED (raise
  SlotCryptoNotConfigured) — khong bao gio fallback sang luu plaintext.
- Moi exception cua module KHONG chua plaintext gia tri slot.
"""

import base64
import hashlib
import hmac
import os
import re

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import settings
from app.services.pii.normalize import fold, nfc

_VERSION = b"v1"
_NONCE_LEN = 12
_KEY_LEN = 32


class SlotCryptoError(Exception):
    """Loi crypto chung — message KHONG BAO GIO chua plaintext."""


class SlotCryptoNotConfigured(SlotCryptoError):
    """Thieu/sai khoa trong settings — fail closed, khong luu gi."""


class SlotBindingError(SlotCryptoError):
    """Giai ma that bai vi context (AAD) khong khop — nghi van cross-context."""


def _load_key(b64_value: str, name: str) -> bytes:
    if not b64_value:
        raise SlotCryptoNotConfigured(f"{name} chua duoc cau hinh")
    try:
        key = base64.b64decode(b64_value, validate=True)
    except Exception as e:
        raise SlotCryptoNotConfigured(f"{name} khong phai base64 hop le") from e
    if len(key) != _KEY_LEN:
        raise SlotCryptoNotConfigured(f"{name} phai la {_KEY_LEN} byte sau khi decode")
    return key


def _aad(customer_ref: str, conversation_ref: str, slot_type: str) -> bytes:
    return f"{customer_ref}|{conversation_ref}|{slot_type}".encode()


def encrypt_slot_value(plaintext: str, *, customer_ref: str,
                       conversation_ref: str, slot_type: str) -> bytes:
    """Ma hoa gia tri slot, BIND vao context. Blob: v1 || nonce(12) || ct+tag."""
    key = _load_key(settings.m4_slot_key_b64, "m4_slot_key_b64")
    nonce = os.urandom(_NONCE_LEN)
    ct = AESGCM(key).encrypt(nonce, plaintext.encode("utf-8"),
                             _aad(customer_ref, conversation_ref, slot_type))
    return _VERSION + nonce + ct


def decrypt_slot_value(blob: bytes, *, customer_ref: str,
                       conversation_ref: str, slot_type: str) -> str:
    """Giai ma NEU VA CHI NEU context khop AAD luc ma hoa. Sai context/tamper ->
    SlotBindingError (fail closed) — caller tra None + alert, KHONG doan tiep."""
    key = _load_key(settings.m4_slot_key_b64, "m4_slot_key_b64")
    if len(blob) < len(_VERSION) + _NONCE_LEN + 16 or blob[:len(_VERSION)] != _VERSION:
        raise SlotCryptoError("blob sai dinh dang")
    nonce = blob[len(_VERSION):len(_VERSION) + _NONCE_LEN]
    ct = blob[len(_VERSION) + _NONCE_LEN:]
    try:
        pt = AESGCM(key).decrypt(nonce, ct,
                                 _aad(customer_ref, conversation_ref, slot_type))
    except InvalidTag as e:
        raise SlotBindingError("context binding khong khop hoac du lieu bi sua") from e
    return pt.decode("utf-8")


def normalize_for_fingerprint(value: str, slot_type: str) -> str:
    """Chuan hoa truoc khi HMAC de replay cung gia tri (khac dau/khoang trang/
    dinh dang) ra CUNG fingerprint trong cung context."""
    if slot_type == "phone":
        digits = re.sub(r"\D", "", value)
        if digits.startswith("84") and len(digits) >= 11:
            digits = "0" + digits[2:]
        return digits
    if slot_type in ("national_id", "bank_account"):
        return re.sub(r"\D", "", value)
    # name/address: fold dau + gop khoang trang (CLAUDE.md §6 — fold CA HAI PHIA)
    return re.sub(r"\s+", " ", fold(nfc(value))).strip()


def fingerprint(value: str, slot_type: str) -> str:
    """HMAC-SHA256 keyed, 32 hex — khop CHECK constraint cua pii_slots."""
    key = _load_key(settings.m4_slot_fp_key_b64, "m4_slot_fp_key_b64")
    norm = normalize_for_fingerprint(value, slot_type)
    return hmac.new(key, f"{slot_type}:{norm}".encode(), hashlib.sha256).hexdigest()[:32]
