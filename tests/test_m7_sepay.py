"""M7-C0 SePay connector — unit (logic thuan): auth Test Mode, parse envelope, extract code."""
import json

import pytest

from app.services.providers import sepay as sp


def _raw(**kw):
    base = {"id": 92704, "gateway": "VietinBank", "transactionDate": "2026-09-13 20:02:37",
            "accountNumber": "0071000123456", "code": None, "content": "3SCF 154 chuyen tien",
            "transferType": "in", "transferAmount": 230000, "accumulated": 19077000, "subAccount": None,
            "referenceCode": "MBVCB.3278907687", "description": ""}
    base.update(kw)
    return json.dumps(base).encode("utf-8")


def test_verify_test_auth():
    assert sp.verify_test_auth("Apikey abc123", "abc123")
    assert sp.verify_test_auth("apikey abc123", "abc123")
    assert not sp.verify_test_auth("Bearer abc123", "abc123")
    assert not sp.verify_test_auth("Apikey wrong", "abc123")
    assert not sp.verify_test_auth(None, "abc123")
    assert not sp.verify_test_auth("Apikey abc123", "")     # thieu cau hinh -> fail-closed


def test_parse_envelope_normalizes():
    ev = sp.parse_envelope(_raw())
    assert ev.provider == "sepay" and ev.provider_event_id == "92704" and ev.direction == "in"
    assert ev.account_number == "0071000123456" and ev.amount_vnd == 230000 and ev.reference == "MBVCB.3278907687"
    assert "accumulated" not in ev.raw_minimal and ev.raw_minimal["content"].startswith("3SCF 154")
    assert len(ev.payload_hash) == 64


def test_parse_envelope_amount_forms_and_direction():
    assert sp.parse_envelope(_raw(transferAmount="230000")).amount_vnd == 230000
    assert sp.parse_envelope(_raw(transferAmount=230000.0)).amount_vnd == 230000
    assert sp.parse_envelope(_raw(transferAmount=230000.5)).amount_vnd is None
    assert sp.parse_envelope(_raw(transferAmount=True)).amount_vnd is None
    assert sp.parse_envelope(_raw(transferType="out")).direction == "out"
    assert sp.parse_envelope(_raw(transferType="")).direction == "unknown"


@pytest.mark.parametrize("raw", [b"", b"not json", b"[1,2]", json.dumps({"content": "x"}).encode(),
                                 json.dumps({"id": ""}).encode()])
def test_parse_envelope_rejects(raw):
    with pytest.raises(sp.SepayError):
        sp.parse_envelope(raw)


def test_extract_codes():
    assert sp.extract_codes(None, "3SCF 154") == [154]
    assert sp.extract_codes("3SCF154", None) == [154]
    assert sp.extract_codes(None, "CK 3scf 0154 tien hang") == [154]
    assert sp.extract_codes(None, "3SCF 154 3SCF 155") == [154, 155]     # trung/nhieu ma -> staff
    assert sp.extract_codes(None, "3SCF 154 va 3SCF 154") == [154]        # cung ma lap lai = 1
    assert sp.extract_codes(None, "chuyen tien mua ca phe") == []
    assert sp.extract_codes(None, "3SCF") == []
