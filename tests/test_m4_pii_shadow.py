"""I-B M4-S0: unit test shadow_scan — containment, flag OFF, metric PII-safe.

Hop dong (AC-M4-02 nen tang + Directive §8): flag OFF khong co code path;
detector loi khong bao gio lam vo flow; metric khong chua plaintext.
"""

import json

from app.config import settings
from app.services.pii import shadow as shadow_mod
from app.services.pii.detector import detect
from app.services.pii.shadow import build_shadow_metrics, shadow_scan


def _with_flag(value):
    """Bat/tat flag truc tiep tren settings (pattern evidence script M2)."""
    settings.m4_pii_shadow = value


def test_flag_off_khong_scan_khong_output(capsys):
    _with_flag(False)
    assert shadow_scan("sđt 0912345678") is None
    assert capsys.readouterr().out == ""


def test_flag_on_emit_metric_khong_plaintext(capsys):
    _with_flag(True)
    try:
        payload = shadow_scan("giao cho Nguyễn Văn An, sđt 0912345678, số 12 đường Lê Lợi quận 3")
    finally:
        _with_flag(False)
    out = capsys.readouterr().out
    assert payload is not None
    assert payload["slots"]["phone"]["count"] == 1
    assert payload["risk_class"] == "D1"
    # khong plaintext trong ca payload lan dong log
    for leak in ("0912345678", "Nguyễn", "Lê Lợi"):
        assert leak not in out and leak not in json.dumps(payload, ensure_ascii=False)
    assert out.startswith("[m4-shadow] ")


def test_detector_exception_bi_nuot(monkeypatch, capsys):
    _with_flag(True)

    def _boom(text):
        raise RuntimeError("noi dung nhay cam 0999888777")

    monkeypatch.setattr(shadow_mod, "detect", _boom)
    try:
        assert shadow_scan("tin nhan bat ky") is None  # KHONG raise
    finally:
        _with_flag(False)
    out = capsys.readouterr().out
    assert "m4_shadow_error" in out
    assert "RuntimeError" in out  # chi ten class
    assert "0999888777" not in out  # KHONG message cua exception


def test_build_metrics_max_confidence_va_vendor_block():
    r = detect("CCCD 079123456789, sđt 0912345678")
    payload = build_shadow_metrics(r, latency_ms=1.0, text_len=30)
    assert payload["risk_class"] == "D2"
    assert payload["vendor_would_block"] is True
    assert payload["slots"]["national_id"]["count"] == 1


def test_cac_flag_m4_mac_dinh_tat():
    # Directive §8: default OFF, missing config => OFF (pydantic default)
    from app.config import Settings
    fresh = Settings(_env_file=None)
    assert fresh.m4_pii_shadow is False
    assert fresh.m4_trusted_pii_path is False
