"""F-PR27-E01 — guard hoi quy cho image provenance.

Bang chung HANH VI (build that fail-closed, verify chan duoc image lech commit) nam o
`scripts/m4_image_provenance_evidence.sh` vi no can docker that. Cac test o day la lop guard RE:
chung chan dung mot dieu -- ai do vo tinh dat lai mot mac dinh am tham -- va chay duoc trong CI
khong co docker.

Vi sao van dang gia du da co kich ban evidence: lop loi bi bat lan nay la mot MAC DINH
(`ARG GIT_COMMIT=unknown`) sinh ra image khong truy nguon duoc ma khong ai thay. Mac dinh rat de
bi them lai trong mot PR khong lien quan; kich ban evidence thi khong chay trong CI.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILES = [ROOT / "Dockerfile", ROOT / "dashboard" / "Dockerfile"]
COMPOSE = ROOT / "docker-compose.prod.yml"
DEPLOY = ROOT / "scripts" / "deploy.sh"
VERIFY = ROOT / "scripts" / "verify_image_provenance.sh"


@pytest.mark.parametrize("df", DOCKERFILES, ids=lambda p: str(p.relative_to(ROOT)))
def test_dockerfile_khong_co_mac_dinh_am_tham(df: Path) -> None:
    """`ARG GIT_COMMIT=<gi do>` = image khong truy nguon duoc van build ra binh thuong."""
    src = df.read_text(encoding="utf-8")
    assert re.search(r"^ARG\s+GIT_COMMIT\s*$", src, re.M), f"{df}: phai co ARG GIT_COMMIT khong mac dinh"
    assert not re.search(r"^ARG\s+GIT_COMMIT\s*=", src, re.M), f"{df}: KHONG duoc dat mac dinh cho GIT_COMMIT"


@pytest.mark.parametrize("df", DOCKERFILES, ids=lambda p: str(p.relative_to(ROOT)))
def test_dockerfile_kiem_dinh_dang_commit(df: Path) -> None:
    src = df.read_text(encoding="utf-8")
    assert "[0-9a-f]{40}" in src, f"{df}: phai kiem GIT_COMMIT la SHA 40 hex"
    assert "org.opencontainers.image.revision" in src, f"{df}: thieu nhan chuan OCI"


def test_compose_truyen_commit_cho_moi_service_build_tu_repo() -> None:
    """Truoc correction: api/worker/2 bot dung `build: .` tran -> khong nhan arg -> luon 'unknown'."""
    src = COMPOSE.read_text(encoding="utf-8")
    assert not re.search(r"^\s*build:\s*\.\s*$", src, re.M), \
        "khong duoc dung `build: .` tran -- service do se khong nhan GIT_COMMIT"
    assert "unknown" not in src, "khong duoc co mac dinh 'unknown' trong compose"


def test_compose_dung_dau_hai_cham_gach_ngang_khong_phai_hoi_cham() -> None:
    """Bai hoc F-H2A2-01: `${VAR:?}` noi suy o parse-time -> lam hong `config` cua deploy dormant."""
    src = COMPOSE.read_text(encoding="utf-8")
    assert "${GIT_COMMIT:-}" in src
    assert "${GIT_COMMIT:?" not in src, \
        "`:?` se lam `docker compose config` hong khi GIT_COMMIT chua dat (deploy dormant)"


def test_deploy_dat_VA_kiem_commit() -> None:
    """CA doi ca hai: dat nhan, va kiem lai tren container dang chay."""
    src = DEPLOY.read_text(encoding="utf-8")
    assert "git rev-parse HEAD" in src, "deploy.sh phai lay commit dang deploy"
    assert "export GIT_COMMIT" in src, "phai export de docker compose build nhan duoc"
    assert "verify_image_provenance.sh" in src, "deploy.sh phai KIEM lai sau khi up"
    dat = src.index("git rev-parse HEAD")
    up = src.index("up -d --build")
    kiem = src.index("verify_image_provenance.sh")
    assert dat < up < kiem, "thu tu phai la: lay commit -> build/up -> kiem"


def test_deploy_khong_kiem_image_nguon_ngoai() -> None:
    """db/redis la image thuong nguon ngoai, khong co nhan cua ta -> dua vao se bao dong gia."""
    src = DEPLOY.read_text(encoding="utf-8")
    m = re.search(r'^SERVICES_CO_NHAN="([^"]+)"', src, re.M)
    assert m, "phai co danh sach rieng cho service build tu repo"
    ds = m.group(1).split()
    assert "db" not in ds and "redis" not in ds
    assert {"api", "worker", "migrate", "dashboard"} <= set(ds)


def test_verifier_fail_closed_khi_thieu_container() -> None:
    """Khong tim thay container PHAI la loi, khong duoc coi nhu 'khong co gi de kiem -> qua'."""
    src = VERIFY.read_text(encoding="utf-8")
    assert "THIEU" in src and "exit 1" in src
    assert "lech=$((lech + 1))" in src
