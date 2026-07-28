"""I-B M4-S2 — masking: thay PII bang placeholder truoc khi van ban roi trusted zone.

Placeholder S2: `[PII_{SLOT}_{n}]` (vd [PII_PHONE_1]) — n danh so theo thu tu xuat
hien trong TUNG turn. Mapping placeholder->gia tri o SERVER-SIDE (khong bao gio
gui kem cho model). S3 se bo sung integrity tag bind conversation (spec §10);
S2 da chan: placeholder la hop den voi model — model chi duoc ECHO nguyen van
trong response candidate, moi echo sai/khong ton tai bi tu choi khi rehydrate.

Nguyen tac: mask CA tin nhan hien tai LAN moi turn history (user va assistant —
assistant co the da echo PII cua khach trong receipt truoc do).
"""

import re
from dataclasses import dataclass, field

from app.services.pii.detector import detect
from app.services.pii.normalize import nfc

_PLACEHOLDER_RE = re.compile(r"\[PII_(PHONE|NAME|ADDRESS|NATIONAL_ID|BANK_ACCOUNT)_(\d{1,3})\]")


@dataclass
class MaskResult:
    masked_text: str
    # placeholder -> (slot_type, gia tri goc). CHI dung server-side.
    mapping: dict[str, tuple[str, str]] = field(default_factory=dict)


def mask_text(text: str, counters: dict[str, int] | None = None) -> MaskResult:
    """Mask 1 doan van ban. `counters` dung chung khi mask nhieu turn de danh so
    placeholder khong trung nhau trong cung mot phien mask."""
    text_nfc = nfc(text or "")
    result = detect(text_nfc)
    counters = counters if counters is not None else {}
    out: list[str] = []
    mapping: dict[str, tuple[str, str]] = {}
    cursor = 0
    for span in result.spans:  # spans da sort theo start, khong overlap
        slot = span.slot_type.value
        counters[slot] = counters.get(slot, 0) + 1
        ph = f"[PII_{slot.upper()}_{counters[slot]}]"
        out.append(text_nfc[cursor:span.start])
        out.append(ph)
        mapping[ph] = (slot, text_nfc[span.start:span.end])
        cursor = span.end
    out.append(text_nfc[cursor:])
    return MaskResult(masked_text="".join(out), mapping=mapping)


def mask_history(history: list[dict]) -> tuple[list[dict], dict[str, tuple[str, str]]]:
    """Mask moi turn {role, content}; tra (history da mask, mapping gop).
    Counter placeholder chia se toan phien de khong trung so giua cac turn."""
    counters: dict[str, int] = {}
    merged: dict[str, tuple[str, str]] = {}
    masked: list[dict] = []
    for turn in history:
        r = mask_text(str(turn.get("content", "")), counters)
        merged.update(r.mapping)
        masked.append({"role": turn.get("role", "user"), "content": r.masked_text})
    return masked, merged


def find_placeholders(text: str) -> list[str]:
    """Liet ke placeholder (dung format) xuat hien trong van ban."""
    return [m.group(0) for m in _PLACEHOLDER_RE.finditer(text or "")]


def rehydrate_response(candidate: str, mapping: dict[str, tuple[str, str]]) -> str | None:
    """Thay placeholder trong response candidate bang gia tri that (CHI de tra ve
    dung khach trong dung context). Fail-closed:
    - placeholder khong ton tai trong mapping -> None (model bia/mangle);
    - chuoi giong-placeholder-nhung-sai-format ([PII_...]) -> None.
    S3 se siet them integrity tag; hop dong fail-closed giu nguyen.
    """
    if candidate is None:
        return None
    known = find_placeholders(candidate)
    for ph in known:
        if ph not in mapping:
            return None
    # bat ky chuoi [PII_...] nao KHONG khop format chuan -> nghi van mangle
    for frag in re.findall(r"\[PII_[^\]]*\]", candidate):
        if frag not in known:
            return None
    out = candidate
    for ph in known:
        out = out.replace(ph, mapping[ph][1])
    return out
