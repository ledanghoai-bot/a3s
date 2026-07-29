"""I-B M4 Stage 0P: unit test crypto sample zone (F-M4-0P-04, CLOSED AT DESIGN LEVEL).

Thuan logic (khong DB). Khoa test synthetic co dinh trong test.
"""

import base64

import pytest

from app.config import settings
from app.services.pii.crypto import (
    SlotBindingError,
    SlotCryptoNotConfigured,
    decrypt_sample_value,
    encrypt_sample_value,
)

_KEY = base64.b64encode(bytes(range(32))).decode()

_CTX = dict(customer_ref="cust-A", conversation_ref="conv-1", sample_id="sample-1")


@pytest.fixture(autouse=True)
def _key():
    old = settings.m4_sample_key_b64
    settings.m4_sample_key_b64 = _KEY
    yield
    settings.m4_sample_key_b64 = old


class TestSampleCrypto:
    def test_roundtrip(self):
        blob = encrypt_sample_value("tin nhan mau cua khach", **_CTX)
        assert decrypt_sample_value(blob, **_CTX) == "tin nhan mau cua khach"
        assert b"tin nhan mau" not in blob

    def test_domain_tach_biet_slot_store(self):
        # blob sample KHONG giai ma duoc bang ham slot (khac domain tag, se raise
        # tag sai hoac SlotCryptoError do sai dinh dang version)
        from app.services.pii.crypto import decrypt_slot_value
        blob = encrypt_sample_value("x", **_CTX)
        with pytest.raises(Exception):
            decrypt_slot_value(blob, customer_ref="cust-A", conversation_ref="conv-1",
                               slot_type="phone")

    @pytest.mark.parametrize("field", ["customer_ref", "conversation_ref", "sample_id"])
    def test_sai_bat_ky_field_nao_deu_fail(self, field):
        blob = encrypt_sample_value("noi dung", **_CTX)
        ctx = dict(_CTX)
        ctx[field] = ctx[field] + "-khac"
        with pytest.raises(SlotBindingError):
            decrypt_sample_value(blob, **ctx)

    def test_moi_sample_id_aad_duy_nhat(self):
        # cung customer/conversation, KHAC sample_id -> khong the giai ma cheo
        blob1 = encrypt_sample_value("A", customer_ref="c", conversation_ref="v", sample_id="s1")
        with pytest.raises(SlotBindingError):
            decrypt_sample_value(blob1, customer_ref="c", conversation_ref="v", sample_id="s2")

    def test_tamper_fail(self):
        blob = bytearray(encrypt_sample_value("noi dung", **_CTX))
        blob[-1] ^= 0x01
        with pytest.raises(SlotBindingError):
            decrypt_sample_value(bytes(blob), **_CTX)

    def test_thieu_khoa_fail_closed(self):
        settings.m4_sample_key_b64 = ""
        with pytest.raises(SlotCryptoNotConfigured):
            encrypt_sample_value("x", **_CTX)

    def test_loi_khong_lo_plaintext(self):
        blob = encrypt_sample_value("noi dung nhay cam", **_CTX)
        try:
            decrypt_sample_value(blob, customer_ref="khac", conversation_ref="conv-1",
                                 sample_id="sample-1")
        except SlotBindingError as e:
            assert "noi dung nhay cam" not in str(e)

    def test_delimiter_collision_bi_chan(self):
        # ke thua thiet ke AAD v2 tu slot store (F-M4-S1-01) — kiem tra lai cho sample
        blob = encrypt_sample_value("x", customer_ref="a|b", conversation_ref="c", sample_id="s")
        with pytest.raises(SlotBindingError):
            decrypt_sample_value(blob, customer_ref="a", conversation_ref="b|c", sample_id="s")

    def test_exact_ciphertext_boundary_8030_bytes(self):
        # REV2 (CA Technical Review #1, T1-02): _SAMPLE_VERSION = b"v1" la 2 BYTE (khong phai 1
        # nhu gia dinh sai truoc do trong migration 039). Overhead dung = 2 (version) + 12
        # (nonce) + 16 (tag GCM) = 30. Plaintext dung DUNG 8000 byte (MAX_BYTES) -> ciphertext
        # PHAI dung 8030 byte — khoa boundary nay bang test de CHECK constraint DB (8030) khong
        # bao gio lech khoi thuc te crypto.py again.
        plaintext_8000_bytes = "a" * 8000  # ASCII, 1 byte/ky tu -> dung 8000 byte khi encode utf-8
        assert len(plaintext_8000_bytes.encode("utf-8")) == 8000
        blob = encrypt_sample_value(plaintext_8000_bytes, **_CTX)
        assert len(blob) == 8030
        assert decrypt_sample_value(blob, **_CTX) == plaintext_8000_bytes
