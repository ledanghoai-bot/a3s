"""CRC32C — doi chieu voi vector cong bo (RFC 3720 / iSCSI).

Ham nay tu viet thay vi them dependency, nen no PHAI duoc chung minh dung bang vector chuan chu
khong phai bang niem tin. Neu no sai, phep kiem toan ven voi Google KMS tro thanh vo nghia — te hon
la khong co, vi no tao cam giac an toan gia.
"""
from __future__ import annotations

import zlib

import pytest

from app.services.pii.crc32c import crc32c


@pytest.mark.parametrize(("du_lieu", "mong_doi"), [
    (b"123456789", 0xE3069283),   # vector kinh dien cua CRC32C
    (b"", 0x00000000),
    (b"\x00" * 32, 0x8A9136AA),   # RFC 3720 B.4
    (b"\xff" * 32, 0x62A8AB43),   # RFC 3720 B.4
])
def test_vector_chuan(du_lieu: bytes, mong_doi: int) -> None:
    assert crc32c(du_lieu) == mong_doi


def test_khong_phai_crc32_ieee() -> None:
    """Chan nham lan tai hai: `zlib.crc32` la CRC-32 IEEE, KHONG phai CRC32C (Castagnoli).

    Dung nham se lam Google KMS tu choi moi request, hoac te hon — neu ai do 'sua' bang cach bo
    kiem tra — lam phep kiem toan ven im lang tro thanh vo dung.
    """
    assert crc32c(b"123456789") != zlib.crc32(b"123456789")


def test_ket_qua_luon_la_32_bit_khong_dau() -> None:
    for n in (0, 1, 255, 4096):
        gt = crc32c(bytes(range(256)) * (n // 256 + 1))
        assert 0 <= gt <= 0xFFFFFFFF


def test_nhay_voi_thay_doi_mot_bit() -> None:
    goc = b'{"sample_id":"11111111-1111-1111-1111-111111111111","v":1}'
    doi = bytearray(goc)
    doi[0] ^= 0x01
    assert crc32c(goc) != crc32c(bytes(doi))
