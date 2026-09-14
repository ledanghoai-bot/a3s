"""M7 VietQR tu sinh — unit (logic thuan, CA Directive 272 §3.3). Encode tat dinh + decode nguoc + CRC + validate."""
import pytest

from app.services.payment import vietqr as vq


def _mk(**kw):
    base = dict(bin_code="970415", account_number="0071000123456", amount_vnd=230000, add_info="3SCF 154")
    base.update(kw)
    return vq.build_payload(**base)


def test_crc_known_vector():
    # CRC-16/CCITT-FALSE("123456789") = 0x29B1 (check value chuan)
    assert vq.crc16_ccitt_false(b"123456789") == 0x29B1


def test_payload_structure_and_roundtrip():
    p = _mk()
    assert p.startswith("000201010212")
    assert "0010A000000727" in p and "0208QRIBFTTA" in p and "5303704" in p and "5802VN" in p
    d = vq.decode(p)
    assert d.crc_ok
    assert d.bin_code == "970415"
    assert d.account_number == "0071000123456"  # so 0 dau giu nguyen
    assert d.amount_vnd == 230000
    assert d.add_info == "3SCF 154"
    assert d.service == "QRIBFTTA" and d.currency == "704" and d.country == "VN" and d.initiation == "12"


def test_deterministic_same_input_same_payload():
    assert _mk() == _mk()
    assert _mk(amount_vnd=230001) != _mk()


def test_leading_zero_account_preserved_and_amount_exact():
    for acct in ("0001", "000123456789", "9704150000000001"):
        d = vq.decode(_mk(account_number=acct))
        assert d.account_number == acct
    for amt in (1, 999, 1000000, 1234567890123):
        assert vq.decode(_mk(amount_vnd=amt)).amount_vnd == amt


def test_crc_tamper_detected():
    p = _mk()
    bad = p[:-1] + ("0" if p[-1] != "0" else "1")
    assert vq.decode(bad).crc_ok is False
    # sua noi dung giua chung -> CRC sai
    tampered = p.replace("3SCF 154", "3SCF 155")
    assert vq.decode(tampered).crc_ok is False


@pytest.mark.parametrize("kw", [
    dict(bin_code="97041"), dict(bin_code="97041A"), dict(bin_code=970415),
    dict(account_number=""), dict(account_number="12 34"), dict(account_number="x" * 20), dict(account_number=123),
    dict(amount_vnd=0), dict(amount_vnd=-1), dict(amount_vnd=True), dict(amount_vnd=1.5), dict(amount_vnd="230000"),
    dict(add_info=""), dict(add_info="3SCF 154 " + "x" * 20), dict(add_info="Đơn 154"), dict(add_info="a;b"),
])
def test_invalid_inputs_fail_closed(kw):
    with pytest.raises(vq.VietQRError):
        _mk(**kw)


def test_decode_rejects_non_vietqr():
    with pytest.raises(vq.VietQRError):
        vq.decode("hello")
    with pytest.raises(vq.VietQRError):
        vq.decode("00020101021238100006B0000000006304ABCD")  # GUID khac


def test_png_optional_lib():
    # segno co the chua cai trong moi truong test; None la hop le (fallback text), bytes phai la PNG.
    out = vq.png_bytes(_mk())
    assert out is None or out[:8] == b"\x89PNG\r\n\x1a\n"
