"""I-B M4-S2/S3 — masking: thay PII bang placeholder truoc khi van ban roi trusted zone.

Placeholder:
- Dang tu do (khong binding):  `[PII_{SLOT}_{n}]`
- Dang S3 (spec §10, TRUSTED FLOW LUON DUNG): `[PII_{SLOT}_{n}_{tag8}]` voi
  tag8 = HMAC-SHA256(fp_key, "ph|{conversation_ref}|{slot}|{n}")[:8 hex] —
  placeholder BIND vao conversation + slot type. Bi sua/thieu/lap/cross-context
  -> rehydrate tu choi (fail closed).

Mapping placeholder->gia tri o SERVER-SIDE (khong bao gio gui kem cho model);
model chi duoc ECHO placeholder nguyen van trong response candidate.

Nguyen tac: mask CA tin nhan hien tai LAN moi turn history (user va assistant —
assistant co the da echo PII cua khach trong receipt truoc do).
"""

import hashlib
import hmac as hmac_mod
import re
from dataclasses import dataclass, field

from app.config import settings
from app.services.pii.crypto import _load_key
from app.services.pii.detector import detect
from app.services.pii.normalize import nfc

_PLACEHOLDER_RE = re.compile(
    r"\[PII_(PHONE|NAME|ADDRESS|NATIONAL_ID|BANK_ACCOUNT)_(\d{1,3})(_[0-9a-f]{8})?\]")


def _tag(conversation_ref: str, slot: str, n: int) -> str:
    """Integrity tag 8 hex — dung khoa fingerprint (fail-closed neu thieu khoa)."""
    key = _load_key(settings.m4_slot_fp_key_b64, "m4_slot_fp_key_b64")
    return hmac_mod.new(key, f"ph|{conversation_ref}|{slot}|{n}".encode(),
                        hashlib.sha256).hexdigest()[:8]


def make_placeholder(slot: str, n: int, conversation_ref: str | None = None) -> str:
    """Sinh placeholder chuan; co conversation_ref => kem integrity tag (S3)."""
    if conversation_ref is None:
        return f"[PII_{slot.upper()}_{n}]"
    return f"[PII_{slot.upper()}_{n}_{_tag(conversation_ref, slot, n)}]"


@dataclass
class MaskResult:
    masked_text: str
    # placeholder -> (slot_type, gia tri goc). CHI dung server-side.
    mapping: dict[str, tuple[str, str]] = field(default_factory=dict)


def mask_text(text: str, counters: dict[str, int] | None = None, *,
              conversation_ref: str | None = None) -> MaskResult:
    """Mask 1 doan van ban. `counters` dung chung khi mask nhieu turn de danh so
    placeholder khong trung nhau trong cung mot phien mask. Co conversation_ref
    => placeholder kem integrity tag (S3) bind vao hoi thoai."""
    text_nfc = nfc(text or "")
    result = detect(text_nfc)
    counters = counters if counters is not None else {}
    out: list[str] = []
    mapping: dict[str, tuple[str, str]] = {}
    cursor = 0
    for span in result.spans:  # spans da sort theo start, khong overlap
        slot = span.slot_type.value
        counters[slot] = counters.get(slot, 0) + 1
        ph = make_placeholder(slot, counters[slot], conversation_ref)
        out.append(text_nfc[cursor:span.start])
        out.append(ph)
        mapping[ph] = (slot, text_nfc[span.start:span.end])
        cursor = span.end
    out.append(text_nfc[cursor:])
    return MaskResult(masked_text="".join(out), mapping=mapping)


def mask_history(history: list[dict], *, conversation_ref: str | None = None,
                 ) -> tuple[list[dict], dict[str, tuple[str, str]]]:
    """Mask moi turn {role, content}; tra (history da mask, mapping gop).
    Counter placeholder chia se toan phien de khong trung so giua cac turn."""
    counters: dict[str, int] = {}
    merged: dict[str, tuple[str, str]] = {}
    masked: list[dict] = []
    for turn in history:
        r = mask_text(str(turn.get("content", "")), counters,
                      conversation_ref=conversation_ref)
        merged.update(r.mapping)
        masked.append({"role": turn.get("role", "user"), "content": r.masked_text})
    return masked, merged


def find_placeholders(text: str) -> list[str]:
    """Liet ke placeholder (dung format) xuat hien trong van ban."""
    return [m.group(0) for m in _PLACEHOLDER_RE.finditer(text or "")]


def rehydrate_response(candidate: str, mapping: dict[str, tuple[str, str]], *,
                       conversation_ref: str | None = None) -> str | None:
    """Thay placeholder trong response candidate bang gia tri that (CHI de tra ve
    dung khach trong dung context). Fail-closed (spec §10 — sua/thieu/lap/
    cross-context deu reject):
    - placeholder khong ton tai trong mapping -> None (model bia/mangle/thieu);
    - chuoi giong-placeholder-nhung-sai-format ([PII_...]) -> None (bi sua);
    - cung placeholder xuat hien >1 lan -> None (lap);
    - co conversation_ref: integrity tag phai khop tag tinh lai cho DUNG hoi
      thoai nay -> placeholder duc tu conversation khac bi loai (cross-context),
      ke ca khi ai do tron nham mapping.
    """
    if candidate is None:
        return None
    known = find_placeholders(candidate)
    if len(known) != len(set(known)):
        return None  # lap
    for ph in known:
        if ph not in mapping:
            return None
        if conversation_ref is not None:
            m = _PLACEHOLDER_RE.fullmatch(ph)
            slot, n, tag = m.group(1).lower(), int(m.group(2)), m.group(3)
            expect = "_" + _tag(conversation_ref, slot, n)
            if tag != expect:
                return None  # khong tag / tag hoi thoai khac
    # bat ky chuoi [PII_...] nao KHONG khop format chuan -> nghi van mangle
    for frag in re.findall(r"\[PII_[^\]]*\]", candidate):
        if frag not in known:
            return None
    out = candidate
    for ph in known:
        out = out.replace(ph, mapping[ph][1])
    return out
