"""I-B M4-S1 — crypto cho Trusted Slot Store: AES-256-GCM + AAD context binding.

Nguyen tac (spec §5/§8):
- Gia tri slot MA HOA O TANG APP truoc khi cham DB. AAD (associated data) v2 =
  canonical encoding CO LENGTH-PREFIX cua (customer_ref, conversation_ref,
  slot_type) + domain tag (xem _aad) -> mot row bi trao sang context khac
  (tamper truc tiep DB, retry/replay bind nham) se KHONG THE giai ma: fail closed
  ngay tai tang crypto, khong phu thuoc query filter dung hay sai. Khong dung
  delimiter noi chuoi (CA F-M4-S1-01: delimiter co the collision).
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

# v2 (CA F-M4-S1-01): AAD chuyen sang canonical LENGTH-PREFIX encoding — v1 dung
# delimiter "|" co the collision khi ref chua "|" ("a|b","c") vs ("a","b|c").
# Blob version nam o byte dau de forward-compatible; KHONG co du lieu v1 nao ton
# tai (dev-only, bang trong) nen v1 khong can duong doc lai — blob v1 bi tu choi.
_VERSION = b"v2"
_NONCE_LEN = 12
_KEY_LEN = 32
_MAX_REF_LEN = 128


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


def _validate_ref(value: str, name: str) -> bytes:
    """Constraint cho ref (CA F-M4-S1-01 correction 4): non-empty, <=128 byte
    UTF-8, khong ky tu NUL/control. Sai -> SlotCryptoError (fail closed)."""
    if not isinstance(value, str) or not value:
        raise SlotCryptoError(f"{name} rong hoac sai kieu")
    raw = value.encode("utf-8")
    if len(raw) > _MAX_REF_LEN:
        raise SlotCryptoError(f"{name} vuot {_MAX_REF_LEN} byte")
    if any(b < 0x20 for b in raw):
        raise SlotCryptoError(f"{name} chua ky tu control")
    return raw


def _aad(customer_ref: str, conversation_ref: str, slot_type: str) -> bytes:
    """Canonical unambiguous AAD (v2): domain-tag + length-prefix tung field —
    khong ton tai 2 bo (customer, conversation, slot_type) khac nhau cho ra cung
    byte AAD (delimiter collision cua v1 da bi loai)."""
    parts = (_validate_ref(customer_ref, "customer_ref"),
             _validate_ref(conversation_ref, "conversation_ref"),
             _validate_ref(slot_type, "slot_type"))
    out = [b"a3s-m4-slot-aad-v2"]
    for p in parts:
        out.append(len(p).to_bytes(4, "big"))
        out.append(p)
    return b"".join(out)


def encrypt_slot_value(plaintext: str, *, customer_ref: str,
                       conversation_ref: str, slot_type: str) -> bytes:
    """Ma hoa gia tri slot, BIND vao context. Blob: v2 || nonce(12) || ct+tag."""
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


# ---------------------------------------------------------------------------
# Stage 0P sample zone (F-M4-0P-04, CLOSED AT DESIGN LEVEL) — crypto RIENG,
# KHONG tai dung nguyen trang AAD cua slot store. "slot_type" khong co y nghia
# voi 1 tin nhan tho (khong phai gia tri 1 slot) nen dung sample_id (UUID, DUY
# NHAT moi row) thay the — moi row co AAD KHONG THE trung nhau, manh hon
# slot_type von lap lai giua nhieu row cua slot store. Khoa RIENG
# (m4_sample_key_b64), tach biet hoan toan Slot Store ke ca khi rotate khoa.
# ---------------------------------------------------------------------------

_SAMPLE_VERSION = b"v1"


def _sample_aad(customer_ref: str, conversation_ref: str, sample_id: str) -> bytes:
    """AAD domain rieng cho sample zone — cung ky thuat length-prefix canonical
    voi _aad() nhung domain tag va bo field khac (F-M4-0P-04)."""
    parts = (_validate_ref(customer_ref, "customer_ref"),
             _validate_ref(conversation_ref, "conversation_ref"),
             _validate_ref(sample_id, "sample_id"))
    out = [b"a3s-m4-shadow-sample-aad-v1"]
    for p in parts:
        out.append(len(p).to_bytes(4, "big"))
        out.append(p)
    return b"".join(out)


def encrypt_sample_value(plaintext: str, *, customer_ref: str,
                         conversation_ref: str, sample_id: str) -> bytes:
    """Ma hoa 1 tin nhan mau cho Stage 0P. Blob: v1 || nonce(12) || ct+tag."""
    key = _load_key(settings.m4_sample_key_b64, "m4_sample_key_b64")
    nonce = os.urandom(_NONCE_LEN)
    ct = AESGCM(key).encrypt(nonce, plaintext.encode("utf-8"),
                             _sample_aad(customer_ref, conversation_ref, sample_id))
    return _SAMPLE_VERSION + nonce + ct


def decrypt_sample_value(blob: bytes, *, customer_ref: str,
                         conversation_ref: str, sample_id: str) -> str:
    """Giai ma NEU VA CHI NEU context khop AAD luc ma hoa — fail closed nhu
    decrypt_slot_value. SlotBindingError khi sai context/tamper."""
    key = _load_key(settings.m4_sample_key_b64, "m4_sample_key_b64")
    if (len(blob) < len(_SAMPLE_VERSION) + _NONCE_LEN + 16
            or blob[:len(_SAMPLE_VERSION)] != _SAMPLE_VERSION):
        raise SlotCryptoError("blob sai dinh dang")
    nonce = blob[len(_SAMPLE_VERSION):len(_SAMPLE_VERSION) + _NONCE_LEN]
    ct = blob[len(_SAMPLE_VERSION) + _NONCE_LEN:]
    try:
        pt = AESGCM(key).decrypt(nonce, ct,
                                 _sample_aad(customer_ref, conversation_ref, sample_id))
    except InvalidTag as e:
        raise SlotBindingError("context binding khong khop hoac du lieu bi sua") from e
    return pt.decode("utf-8")
