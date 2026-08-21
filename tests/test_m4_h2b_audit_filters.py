"""I-B M4 H2-B — chung minh cac filter audit khop DUNG cai chung phai khop (F-PR31-04).

VI SAO CAN THU NAY
CA Review 1 doi "chung minh filters bang fixture hoac provider-supported validation".
`terraform validate` khong doc noi dung filter — no chi kiem cu phap HCL. Nghia la mot filter viet
sai van validate PASS, van apply duoc, va chi lo ra khi can alert nhat ma khong co alert nao ban.

Test nay doc CHINH file `infra/gcp-kms/audit_filters.json` ma Terraform doc, roi chay tung filter
tren cac ban ghi audit log mau. Neu ai do sua filter theo huong khong con bat duoc su kien can bat,
test do.

GIOI HAN DA KHAI: day KHONG phai trinh danh gia cua Google. No cai dat tap con cu phap ma du an
dang dung (=, :, !=, AND, OR, ngoac, log_id()). Fixture dung theo hinh dang tai lieu, chua doi
chieu voi audit log THAT (chua co credential). Buoc Infra Apply van phai kiem lai bang su kien that.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FILE_FILTER = ROOT / "infra" / "gcp-kms" / "audit_filters.json"

KEY_RING_ID = "projects/alpha3s-production-signing/locations/asia-southeast1/keyRings/production-signing"
CRYPTO_KEY_ID = f"{KEY_RING_ID}/cryptoKeys/m4-transcript-ed25519"


# --------------------------------------------------------------------------- #
# Trinh danh gia toi thieu cho tap con cu phap Logging ma du an dang dung.
# --------------------------------------------------------------------------- #

_TOKEN = re.compile(
    r"""\s*(?:
        (?P<mo>\()
      | (?P<dong>\))
      | (?P<and>AND\b)
      | (?P<or>OR\b)
      | (?P<logid>log_id\(\s*"(?P<logid_gt>[^"]*)"\s*\))
      | (?P<truong>[A-Za-z_][A-Za-z0-9_.]*)\s*(?P<toantu>!=|=|:)\s*
        (?:"(?P<gt_chuoi>[^"]*)"|(?P<gt_so>-?\d+))
    )""",
    re.VERBOSE,
)


def _tach_token(bieu_thuc: str) -> list[tuple[str, object]]:
    vi_tri, tokens = 0, []
    while vi_tri < len(bieu_thuc):
        if bieu_thuc[vi_tri].isspace():
            vi_tri += 1
            continue
        khop = _TOKEN.match(bieu_thuc, vi_tri)
        if not khop:
            raise AssertionError(f"khong hieu cu phap tai vi tri {vi_tri}: {bieu_thuc[vi_tri:vi_tri + 40]!r}")
        d = khop.groupdict()
        if d["mo"]:
            tokens.append(("(", None))
        elif d["dong"]:
            tokens.append((")", None))
        elif d["and"]:
            tokens.append(("AND", None))
        elif d["or"]:
            tokens.append(("OR", None))
        elif d["logid"]:
            tokens.append(("log_id", d["logid_gt"]))
        else:
            gt = d["gt_chuoi"] if d["gt_chuoi"] is not None else int(d["gt_so"])
            tokens.append(("dieu_kien", (d["truong"], d["toantu"], gt)))
        vi_tri = khop.end()
    return tokens


def _lay_truong(ban_ghi: dict, duong_dan: str):
    hien_tai = ban_ghi
    for phan in duong_dan.split("."):
        if not isinstance(hien_tai, dict) or phan not in hien_tai:
            return None
        hien_tai = hien_tai[phan]
    return hien_tai


def _danh_gia_dieu_kien(ban_ghi: dict, dieu_kien: tuple) -> bool:
    truong, toan_tu, mong_doi = dieu_kien
    thuc_te = _lay_truong(ban_ghi, truong)
    if thuc_te is None:
        # Truong vang mat: Logging coi la KHONG khop, ke ca voi `!=`. Day chinh la ly do
        # `status.code!=0` khong bat nham cac request THANH CONG (chung khong co status.code).
        return False
    if toan_tu == "=":
        return str(thuc_te) == str(mong_doi)
    if toan_tu == ":":
        return str(mong_doi) in str(thuc_te)
    if toan_tu == "!=":
        return str(thuc_te) != str(mong_doi)
    raise AssertionError(f"toan tu chua ho tro: {toan_tu}")


def danh_gia(bieu_thuc: str, ban_ghi: dict) -> bool:
    """Danh gia bieu thuc filter tren mot ban ghi. AND uu tien cao hon OR, dung nhu Logging."""
    tokens = _tach_token(bieu_thuc)
    vi_tri = 0

    def hang() -> bool:  # AND-chain
        nonlocal vi_tri
        gia_tri = don_vi()
        while vi_tri < len(tokens) and tokens[vi_tri][0] == "AND":
            vi_tri += 1
            gia_tri = don_vi() and gia_tri
        return gia_tri

    def bieu() -> bool:  # OR-chain
        nonlocal vi_tri
        gia_tri = hang()
        while vi_tri < len(tokens) and tokens[vi_tri][0] == "OR":
            vi_tri += 1
            gia_tri = hang() or gia_tri
        return gia_tri

    def don_vi() -> bool:
        nonlocal vi_tri
        loai, du_lieu = tokens[vi_tri]
        if loai == "(":
            vi_tri += 1
            gia_tri = bieu()
            assert tokens[vi_tri][0] == ")", "thieu dau dong ngoac"
            vi_tri += 1
            return gia_tri
        if loai == "log_id":
            vi_tri += 1
            ten = _lay_truong(ban_ghi, "logName") or ""
            return ten.endswith("/logs/" + du_lieu.replace("/", "%2F"))
        if loai == "dieu_kien":
            vi_tri += 1
            return _danh_gia_dieu_kien(ban_ghi, du_lieu)
        raise AssertionError(f"token khong mong doi: {loai}")

    ket_qua = bieu()
    assert vi_tri == len(tokens), "con token thua sau khi danh gia"
    return ket_qua


# --------------------------------------------------------------------------- #
# Fixture: ban ghi audit log mau
# --------------------------------------------------------------------------- #

def _ban_ghi(log: str, service: str, method: str, resource: str = "", **them) -> dict:
    payload = {"serviceName": service, "methodName": method, "resourceName": resource}
    payload.update(them)
    return {
        "logName": f"projects/alpha3s-production-signing/logs/{log.replace('/', '%2F')}",
        "protoPayload": payload,
    }


KY_TRANSCRIPT = _ban_ghi(
    "cloudaudit.googleapis.com/data_access",
    "cloudkms.googleapis.com",
    "google.cloud.kms.v1.KeyManagementService.AsymmetricSign",
    f"{CRYPTO_KEY_ID}/cryptoKeyVersions/1",
)
DOC_PUBLIC_KEY = _ban_ghi(
    "cloudaudit.googleapis.com/data_access",
    "cloudkms.googleapis.com",
    "google.cloud.kms.v1.KeyManagementService.GetPublicKey",
    f"{CRYPTO_KEY_ID}/cryptoKeyVersions/1",
)
DOI_IAM_KHOA = _ban_ghi(
    "cloudaudit.googleapis.com/activity",
    "cloudkms.googleapis.com",
    "google.cloud.kms.v1.KeyManagementService.SetIamPolicy",
    CRYPTO_KEY_ID,
)
HUY_PHIEN_BAN = _ban_ghi(
    "cloudaudit.googleapis.com/activity",
    "cloudkms.googleapis.com",
    "google.cloud.kms.v1.KeyManagementService.DestroyCryptoKeyVersion",
    f"{CRYPTO_KEY_ID}/cryptoKeyVersions/1",
)
DOI_WIF_PROVIDER = _ban_ghi(
    "cloudaudit.googleapis.com/activity",
    "iam.googleapis.com",
    "google.iam.v1.WorkloadIdentityPools.UpdateWorkloadIdentityPoolProvider",
    "projects/452818585523/locations/global/workloadIdentityPools/alpha3s-prod-vps/providers/vps-x509",
)
DOI_IAM_PROJECT = _ban_ghi(
    "cloudaudit.googleapis.com/activity",
    "cloudresourcemanager.googleapis.com",
    "SetIamPolicy",
    "projects/alpha3s-production-signing",
)
STS_THAT_BAI = _ban_ghi(
    "cloudaudit.googleapis.com/data_access",
    "sts.googleapis.com",
    "google.identity.sts.v1.SecurityTokenService.ExchangeToken",
    "",
    status={"code": 7, "message": "PERMISSION_DENIED"},
)
STS_THANH_CONG = _ban_ghi(
    "cloudaudit.googleapis.com/data_access",
    "sts.googleapis.com",
    "google.identity.sts.v1.SecurityTokenService.ExchangeToken",
)
SUA_SINK = _ban_ghi(
    "cloudaudit.googleapis.com/activity",
    "logging.googleapis.com",
    "google.logging.v2.ConfigServiceV2.sinks.update",
    "projects/alpha3s-production-signing/sinks/kms-audit-sink",
)
SUA_BUCKET_AUDIT = _ban_ghi(
    "cloudaudit.googleapis.com/activity",
    "storage.googleapis.com",
    "storage.buckets.update",
    "projects/_/buckets/a3s-prod-kms-audit",
)
LOG_KHONG_PHAI_AUDIT = {
    "logName": "projects/alpha3s-production-signing/logs/stdout",
    "protoPayload": {"serviceName": "cloudkms.googleapis.com", "methodName": "AsymmetricSign"},
}


@pytest.fixture(scope="module")
def bo_loc() -> dict[str, str]:
    du_lieu = json.loads(FILE_FILTER.read_text(encoding="utf-8"))
    return {
        ten: gt.replace("__CRYPTO_KEY_ID__", CRYPTO_KEY_ID).replace("__KEY_RING_ID__", KEY_RING_ID)
        for ten, gt in du_lieu.items()
        if not ten.startswith("_")
    }


# ten filter -> (ban ghi PHAI khop, ban ghi PHAI KHONG khop)
TRUONG_HOP = {
    "sign_operations": ([KY_TRANSCRIPT], [DOC_PUBLIC_KEY, DOI_IAM_KHOA, LOG_KHONG_PHAI_AUDIT]),
    "key_iam_changes": ([DOI_IAM_KHOA], [KY_TRANSCRIPT, DOI_IAM_PROJECT]),
    "key_state_changes": ([HUY_PHIEN_BAN], [KY_TRANSCRIPT, DOI_IAM_KHOA]),
    "identity_config_changes": ([DOI_WIF_PROVIDER, DOI_IAM_PROJECT], [KY_TRANSCRIPT, STS_THAT_BAI]),
    "auth_failures": ([STS_THAT_BAI], [STS_THANH_CONG, KY_TRANSCRIPT]),
    "audit_destination_changes": ([SUA_SINK, SUA_BUCKET_AUDIT], [KY_TRANSCRIPT, DOI_WIF_PROVIDER]),
    "sink_all_audit": (
        [KY_TRANSCRIPT, DOI_WIF_PROVIDER, STS_THAT_BAI, SUA_SINK, SUA_BUCKET_AUDIT, DOI_IAM_PROJECT],
        [LOG_KHONG_PHAI_AUDIT],
    ),
}


@pytest.mark.parametrize("ten", sorted(TRUONG_HOP))
def test_filter_bat_dung_su_kien(bo_loc: dict[str, str], ten: str) -> None:
    phai_khop, phai_khong_khop = TRUONG_HOP[ten]
    bieu_thuc = bo_loc[ten]
    for ban_ghi in phai_khop:
        assert danh_gia(bieu_thuc, ban_ghi), (
            f"filter {ten!r} BO SOT su kien phai bat: {ban_ghi['protoPayload']['methodName']}"
        )
    for ban_ghi in phai_khong_khop:
        assert not danh_gia(bieu_thuc, ban_ghi), (
            f"filter {ten!r} bat NHAM su kien: {ban_ghi['protoPayload']['methodName']}"
        )


def test_moi_filter_deu_duoc_phu_boi_truong_hop(bo_loc: dict[str, str]) -> None:
    """Them filter moi ma quen viet truong hop kiem thi test nay do."""
    assert set(bo_loc) == set(TRUONG_HOP), (
        f"lech: chi co trong JSON {sorted(set(bo_loc) - set(TRUONG_HOP))}, "
        f"chi co trong test {sorted(set(TRUONG_HOP) - set(bo_loc))}"
    )


def test_khong_con_dung_bang_tuyet_doi_cho_ten_rpc(bo_loc: dict[str, str]) -> None:
    """Hoi quy cho dung loi da bat duoc: methodName="AsymmetricSign" khong bao gio khop.

    Audit log ghi ten RPC day du. Bang tuyet doi voi ten ngan = metric luon 0 = alert im lang.
    """
    for ten, bieu_thuc in bo_loc.items():
        assert not re.search(r'methodName\s*=\s*"', bieu_thuc), (
            f"filter {ten!r} dung `methodName=` (bang tuyet doi) — phai dung `methodName:` (chua), "
            "vi audit log ghi ten RPC day du"
        )
