"""I-B M4-S1: unit test crypto Slot Store — binding, fail-closed, fingerprint.

Thuan logic (khong DB). Khoa test la synthetic, sinh co dinh trong test.
Gia tri PII trong test la so/ten BIA.
"""

import base64

import pytest

from app.config import settings
from app.services.pii.crypto import (
    SlotBindingError,
    SlotCryptoNotConfigured,
    decrypt_slot_value,
    encrypt_slot_value,
    fingerprint,
    normalize_for_fingerprint,
)

_KEY1 = base64.b64encode(bytes(range(32))).decode()
_KEY2 = base64.b64encode(bytes(range(1, 33))).decode()


@pytest.fixture(autouse=True)
def _keys():
    """Gan khoa synthetic cho moi test roi tra lai trang thai chua cau hinh."""
    old_k, old_f = settings.m4_slot_key_b64, settings.m4_slot_fp_key_b64
    settings.m4_slot_key_b64 = _KEY1
    settings.m4_slot_fp_key_b64 = _KEY2
    yield
    settings.m4_slot_key_b64, settings.m4_slot_fp_key_b64 = old_k, old_f


_CTX = dict(customer_ref="cust-A", conversation_ref="conv-1", slot_type="phone")


class TestEncryptDecrypt:
    def test_roundtrip_dung_context(self):
        blob = encrypt_slot_value("0912345678", **_CTX)
        assert decrypt_slot_value(blob, **_CTX) == "0912345678"
        assert b"0912345678" not in blob  # khong plaintext trong blob

    @pytest.mark.parametrize("field,value", [
        ("customer_ref", "cust-B"),
        ("conversation_ref", "conv-2"),
        ("slot_type", "name"),
    ])
    def test_sai_bat_ky_thanh_phan_context_nao_deu_fail(self, field, value):
        blob = encrypt_slot_value("0912345678", **_CTX)
        ctx = dict(_CTX)
        ctx[field] = value
        with pytest.raises(SlotBindingError):
            decrypt_slot_value(blob, **ctx)

    def test_tamper_blob_fail(self):
        blob = bytearray(encrypt_slot_value("0912345678", **_CTX))
        blob[-1] ^= 0x01
        with pytest.raises(SlotBindingError):
            decrypt_slot_value(bytes(blob), **_CTX)

    def test_thieu_khoa_fail_closed(self):
        settings.m4_slot_key_b64 = ""
        with pytest.raises(SlotCryptoNotConfigured):
            encrypt_slot_value("x", **_CTX)

    def test_khoa_sai_do_dai_fail_closed(self):
        settings.m4_slot_key_b64 = base64.b64encode(b"short").decode()
        with pytest.raises(SlotCryptoNotConfigured):
            encrypt_slot_value("x", **_CTX)

    def test_loi_khong_lo_plaintext(self):
        blob = encrypt_slot_value("0912345678", **_CTX)
        try:
            decrypt_slot_value(blob, customer_ref="cust-B",
                               conversation_ref="conv-1", slot_type="phone")
        except SlotBindingError as e:
            assert "0912345678" not in str(e)


class TestAADCanonical:
    """CA F-M4-S1-01: AAD v2 length-prefix — khong con delimiter collision."""

    def test_delimiter_collision_bi_chan(self):
        # v1 cu: ("a|b","c") va ("a","b|c") cho cung AAD "a|b|c|phone".
        # v2: length-prefix -> 2 context nay PHAI khac AAD, decrypt cheo fail.
        blob = encrypt_slot_value("0912345678", customer_ref="a|b",
                                  conversation_ref="c", slot_type="phone")
        with pytest.raises(SlotBindingError):
            decrypt_slot_value(blob, customer_ref="a",
                               conversation_ref="b|c", slot_type="phone")

    def test_collision_chieu_nguoc_lai(self):
        blob = encrypt_slot_value("0912345678", customer_ref="a",
                                  conversation_ref="b|c", slot_type="phone")
        with pytest.raises(SlotBindingError):
            decrypt_slot_value(blob, customer_ref="a|b",
                               conversation_ref="c", slot_type="phone")

    @pytest.mark.parametrize("bad_ref", ["", "x" * 129, "abc\x00def", "a\nb"])
    def test_ref_validation_fail_closed(self, bad_ref):
        from app.services.pii.crypto import SlotCryptoError
        with pytest.raises(SlotCryptoError):
            encrypt_slot_value("0912345678", customer_ref=bad_ref,
                               conversation_ref="conv-1", slot_type="phone")

    def test_blob_version_v1_bi_tu_choi(self):
        # blob v1 gia lap (khong co du lieu v1 that — dev-only, bang trong)
        from app.services.pii.crypto import SlotCryptoError
        fake_v1 = b"v1" + b"\x00" * 40
        with pytest.raises(SlotCryptoError):
            decrypt_slot_value(fake_v1, **_CTX)


class TestFingerprint:
    def test_dinh_dang_32_hex_va_khong_lo_so(self):
        fp = fingerprint("0912345678", "phone")
        assert len(fp) == 32 and all(c in "0123456789abcdef" for c in fp)
        assert "0912345678" not in fp

    def test_chuan_hoa_phone_cung_fp(self):
        # cac bien the dinh dang cua CUNG mot so -> cung fingerprint
        fps = {fingerprint(v, "phone") for v in
               ["0912345678", "0912 345 678", "0912.345.678", "+84912345678", "84 912 345 678"]}
        assert len(fps) == 1

    def test_chuan_hoa_ten_dau_khong_dau_cung_fp(self):
        assert fingerprint("Nguyễn Văn  An", "name") == fingerprint("nguyen van an", "name")

    def test_khac_slot_type_khac_fp(self):
        assert fingerprint("123456789012", "phone") != fingerprint("123456789012", "national_id")

    def test_keyed_khac_khoa_khac_fp(self):
        fp1 = fingerprint("0912345678", "phone")
        settings.m4_slot_fp_key_b64 = _KEY1
        assert fingerprint("0912345678", "phone") != fp1

    def test_thieu_khoa_fp_fail_closed(self):
        settings.m4_slot_fp_key_b64 = ""
        with pytest.raises(SlotCryptoNotConfigured):
            fingerprint("0912345678", "phone")

    def test_normalize(self):
        assert normalize_for_fingerprint("+84 912-345.678", "phone") == "0912345678"
        assert normalize_for_fingerprint("  Số 12   Đường Lê Lợi ", "address") == "so 12 duong le loi"
