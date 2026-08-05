"""I-B M4-S1 — repository Trusted Slot Store (bang pii_slots, spec §8).

Convention theo command repository M1: MOI ham nhan san `conn` (asyncpg) — KHONG
tu mo connection, de caller gom vao transaction khi can.

Bat bien bao ve (map spec §8):
- Isolation: moi truy van deu filter DAY DU (customer_ref, conversation_ref);
  them tang crypto AAD — du query sai, gia tri van khong giai ma duoc o context khac.
- Retry/replay: UNIQUE (context, slot_type, fingerprint) + ON CONFLICT DO NOTHING
  -> luu lai cung gia tri trong cung context la no-op tra ve slot cu; context khac
  luon la row khac (khong bao gio re-bind).
- Row bat bien: khong ham UPDATE nao ton tai (DB cung REVOKE UPDATE voi runtime).
- Retention: expires_at bat buoc; resolve bo qua row het han; purge_expired DELETE.
- Log: CHI counts/enum/slot_type — khong plaintext, khong fingerprint, khong ref.

External model KHONG BAO GIO cham module nay (khong co duong import tu vendor
payload builder — kiem bang test tinh trong S2/S3).
"""

import json
from dataclasses import dataclass

from app.config import settings
from app.services.pii.crypto import (
    SlotBindingError,
    decrypt_slot_value,
    encrypt_slot_value,
    fingerprint,
)
from app.services.pii.taxonomy import DETECTOR_VERSION

_CONF_ORDER = {"high": 2, "medium": 1, "low": 0}


def _log(event: str, **fields) -> None:
    """1 dong JSON prefix [m4-slot] — chi id/enum/count, KHONG PII (mau observability M1)."""
    print("[m4-slot] " + json.dumps({"event": event, **fields}, ensure_ascii=False, sort_keys=True))


@dataclass
class StoredSlot:
    slot_id: str
    deduped: bool  # True = replay cung gia tri cung context (row co san)


async def store_slot(conn, *, customer_ref: str, conversation_ref: str, slot_type: str,
                     value: str, confidence: str, data_class: str, purpose_code: str,
                     source_message_ref: str | None = None,
                     detector_version: str = DETECTOR_VERSION,
                     ttl_hours: int | None = None) -> StoredSlot:
    """Luu 1 gia tri slot (ma hoa + bind context). Replay cung gia tri/context -> dedupe."""
    ttl = ttl_hours if ttl_hours is not None else settings.m4_slot_ttl_hours
    blob = encrypt_slot_value(value, customer_ref=customer_ref,
                              conversation_ref=conversation_ref, slot_type=slot_type)
    fp = fingerprint(value, slot_type)
    row = await conn.fetchrow(
        """
        INSERT INTO pii_slots (customer_ref, conversation_ref, slot_type, encrypted_value,
                               normalized_fingerprint, source_message_ref, detector_version,
                               confidence, expires_at, data_class, purpose_code)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8, now() + make_interval(hours => $9), $10, $11)
        ON CONFLICT (customer_ref, conversation_ref, slot_type, normalized_fingerprint)
        DO NOTHING
        RETURNING slot_id
        """,
        customer_ref, conversation_ref, slot_type, blob, fp, source_message_ref,
        detector_version, confidence, ttl, data_class, purpose_code,
    )
    if row is not None:
        _log("m4_slot_stored", slot_type=slot_type, confidence=confidence,
             data_class=data_class, deduped=False)
        return StoredSlot(slot_id=str(row["slot_id"]), deduped=False)
    existing = await conn.fetchrow(
        "SELECT slot_id FROM pii_slots WHERE customer_ref=$1 AND conversation_ref=$2 "
        "AND slot_type=$3 AND normalized_fingerprint=$4",
        customer_ref, conversation_ref, slot_type, fp,
    )
    _log("m4_slot_stored", slot_type=slot_type, confidence=confidence,
         data_class=data_class, deduped=True)
    return StoredSlot(slot_id=str(existing["slot_id"]), deduped=True)


async def resolve_slot(conn, *, customer_ref: str, conversation_ref: str, slot_type: str,
                       min_confidence: str = "low") -> str | None:
    """Lay gia tri slot MOI NHAT con han, DUNG context, du confidence.

    Khong co/het han/thieu confidence -> None. Giai ma that bai (nghi van
    cross-context/tamper) -> None + ALERT log (fail closed, spec §5.8) —
    KHONG BAO GIO tra gia tri tu context khac.
    """
    rows = await conn.fetch(
        """
        SELECT slot_id, encrypted_value, confidence FROM pii_slots
        WHERE customer_ref=$1 AND conversation_ref=$2 AND slot_type=$3
          AND expires_at > now()
        ORDER BY captured_at DESC, slot_id
        """,
        customer_ref, conversation_ref, slot_type,
    )
    need = _CONF_ORDER[min_confidence]
    for row in rows:
        if _CONF_ORDER[row["confidence"]] < need:
            continue
        try:
            return decrypt_slot_value(
                bytes(row["encrypted_value"]), customer_ref=customer_ref,
                conversation_ref=conversation_ref, slot_type=slot_type,
            )
        except SlotBindingError:
            # Row nam dung filter context nhung AAD khong khop => du lieu bi doi
            # context sau khi ghi (tamper/bug). Fail closed + alert, thu row khac
            # KHONG lam: dung ngay de khong che lap su co.
            _log("m4_slot_binding_alert", slot_type=slot_type, severity="P1")
            return None
    return None


async def purge_expired(conn) -> int:
    """Xoa row het han (retention §8). Tra so luong — log counts-only."""
    result = await conn.execute("DELETE FROM pii_slots WHERE expires_at <= now()")
    count = int(result.split()[-1]) if result.startswith("DELETE") else 0
    _log("m4_slot_purged", count=count)
    return count
