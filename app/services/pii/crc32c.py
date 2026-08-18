"""CRC32C (Castagnoli) — dung cho kiem toan ven end-to-end voi Google Cloud KMS.

VI SAO TU VIET THAY VI THEM DEPENDENCY
Chi can dung MOT ham, thuat toan da chuan hoa (RFC 3720), va co vector kiem chuan de doi chieu.
Them mot goi C-backed cho 15 dong nay se lam nang image va them mot thu phai theo doi ban va.
Doi lai, ban tu viet PHAI duoc chung minh dung — xem `tests/test_crc32c.py`, doi chieu voi cac
vector cong bo cua RFC 3720/iSCSI.

LUU Y: day KHONG phai `zlib.crc32` — do la CRC-32 (IEEE, poly 0xEDB88320). Google KMS dung CRC32C
(poly Castagnoli 0x82F63B78). Dung nham se lam moi request bi tu choi, hoac te hon, lam phep kiem
toan ven tro thanh vo nghia.
"""
from __future__ import annotations

_POLY = 0x82F63B78  # Castagnoli, dang phan chieu (reflected)

# Bang tra 256 muc, dung mot lan khi import.
_BANG: tuple[int, ...] = tuple(
    (lambda c: [c := (c >> 1) ^ (_POLY if c & 1 else 0) for _ in range(8)][-1])(i)
    for i in range(256)
)


def crc32c(du_lieu: bytes) -> int:
    """Tra ve CRC32C 32-bit khong dau cua `du_lieu`."""
    crc = 0xFFFFFFFF
    for byte in du_lieu:
        crc = _BANG[(crc ^ byte) & 0xFF] ^ (crc >> 8)
    return crc ^ 0xFFFFFFFF
