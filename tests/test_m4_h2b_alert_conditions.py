"""F-APPLY-03B/03C/04A/04B — kiem tra sua loi partial apply 24-25/8/2026.

Authority mapping hien hanh: CA Review 28 muc 4 (thay Review 20 sau khi server bac
cloudkms_*/project — khong phai Monitoring descriptor; timeSeries thuc do ra global).

Kiem TINH tren van ban main.tf:
- 04B: 6 alert policy co dung so condition, dung exact resource.type theo mapping Review 28 muc 4,
  moi condition van tro dung metric, combiner OR, va CAM one_of (sai cu phap cho resource.type
  theo grammar https://docs.cloud.google.com/monitoring/api/v3/filters).
- 03B: pem_certificate phai boc trimspace; va trimspace-semantics (mo phong Go strings.TrimSpace)
  chi bo whitespace dau/cuoi, giu nguyen newline noi bo.
"""

import re
from pathlib import Path

MAIN_TF = (Path(__file__).resolve().parents[1] / "infra" / "gcp-kms" / "main.tf").read_text(
    encoding="utf-8")

# Mapping EXACT theo CA Review 28 muc 4 (F-APPLY-04B — sua tu Review 20 sau khi server bac
# cloudkms_*/project: khong phai Monitoring descriptor; timeSeries thuc do ra global) — doi mapping phai qua review.
MAPPING = {
    "m4_sign_operations": ["global"],
    "m4_key_state_changes": ["global"],
    "m4_auth_failures": ["audited_resource"],
    "m4_key_iam_changes": ["global"],
    "m4_identity_config_changes": ["global", "audited_resource"],
    "m4_audit_destination_changes": ["gcs_bucket", "global"],
}

POLICY_CUA_METRIC = {
    "m4_sign_operations": "sign_activity",
    "m4_key_state_changes": "key_state_changes",
    "m4_auth_failures": "auth_failures",
    "m4_key_iam_changes": "key_iam_changes",
    "m4_identity_config_changes": "identity_config_changes",
    "m4_audit_destination_changes": "audit_destination_changes",
}


def _khoi_policy(ten: str) -> str:
    m = re.search(
        r'resource "google_monitoring_alert_policy" "' + ten + r'" \{.*?\n\}\n', MAIN_TF, re.DOTALL)
    assert m, f"khong thay policy {ten}"
    return m.group(0)


def test_moi_policy_dung_so_condition_va_resource_type():
    for metric, types in MAPPING.items():
        khoi = _khoi_policy(POLICY_CUA_METRIC[metric])
        filters = re.findall(r'filter\s*=\s*"([^"\\]*(?:\\.[^"\\]*)*)"', khoi)
        assert len(filters) == len(types), (
            f"{metric}: co {len(filters)} condition, mapping doi {len(types)}")
        got = []
        for f in filters:
            # moi filter phai tro dung metric cua policy
            assert f"google_logging_metric.{metric}.name" in f, f"{metric}: filter tro sai metric: {f}"
            m = re.search(r'resource\.type=\\"([a-z_]+)\\"', f)
            assert m, f"{metric}: filter thieu resource.type: {f}"
            got.append(m.group(1))
        assert sorted(got) == sorted(types), f"{metric}: resource.type {got} != mapping {types}"


def test_combiner_or_va_cam_one_of():
    for metric in MAPPING:
        khoi = _khoi_policy(POLICY_CUA_METRIC[metric])
        assert 'combiner     = "OR"' in khoi or 'combiner = "OR"' in khoi, \
            f"{POLICY_CUA_METRIC[metric]}: thieu combiner OR"
    assert "one_of" not in MAIN_TF, (
        "one_of bi CAM: grammar Monitoring filter khong cho one_of voi resource.type "
        "(Review 19/20 — de xuat one_of da bi rut lai vi sai cu phap)")


def test_condition_da_type_co_display_name_phan_biet():
    for metric, types in MAPPING.items():
        if len(types) < 2:
            continue
        khoi = _khoi_policy(POLICY_CUA_METRIC[metric])
        names = re.findall(r'display_name = "([^"]+)"', khoi)
        conds = [n for n in names if any(f"[{t}]" in n for t in types)]
        assert len(conds) == len(types) == len(set(conds)), (
            f"{metric}: display_name cac condition phai phan biet theo type, thay: {names}")


def test_pem_dung_trimspace():
    assert "pem_certificate = trimspace(var.wif_ca_trust_anchor_pem)" in MAIN_TF, \
        "03B: pem_certificate phai boc trimspace(var.wif_ca_trust_anchor_pem)"
    assert not re.search(r"pem_certificate\s*=\s*var\.wif_ca_trust_anchor_pem\b", MAIN_TF), \
        "03B: khong duoc con dang tran (khong trimspace)"


def test_trimspace_semantics_giu_newline_noi_bo():
    # Mo phong dung Go strings.TrimSpace (= str.strip() voi whitespace ASCII/unicode):
    # PEM tong hop — KHONG dung chung chi that trong repo.
    pem = "-----BEGIN CERTIFICATE-----\nAAAA\nBBBB\n-----END CERTIFICATE-----\n"
    cat = pem.strip()
    assert cat == "-----BEGIN CERTIFICATE-----\nAAAA\nBBBB\n-----END CERTIFICATE-----"
    assert len(pem) - len(cat) == 1, "chi duoc mat dung 1 newline cuoi"
    assert cat.count("\n") == pem.count("\n") - 1, "newline noi bo phai giu nguyen"
    assert not cat.endswith("\n"), "plan input khong duoc co trailing LF"
    assert cat.startswith("-----BEGIN CERTIFICATE-----")
    assert cat.endswith("-----END CERTIFICATE-----")


def test_khong_co_alert_strategy_trong_metric_threshold_policy():
    # F-APPLY-04A: notification_rate_limit chi hop le cho log-based policy; moi policy o day la
    # metric-threshold nen alert_strategy bi cam hoan toan (server 400 neu co).
    assert "alert_strategy" not in MAIN_TF, "alert_strategy bi cam trong metric-threshold policy"
