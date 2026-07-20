"""Validate ParsedAsset truoc khi cho vao Knowledge Unit builder - dung theo
dung quy tac "Block ingestion khi" trong INGESTION_GUIDE.md:
- Thieu id/version/status
- ID trung
- Status khong phai approved/locked cho production (tru khi bat include_draft)
- Dependency bat buoc khong ton tai
- File encoding khong phai UTF-8

Khong tu ra quyet dinh "sua ho" - chi tra ve danh sach ly do reject, de
scripts/kb_ingest.py ghi vao rejected-report roi bo qua file do, KHONG lam
crash ca lan chay ingest chi vi 1 file loi.
"""

from app.services.kb_ingest.loader import ParsedAsset

_PRODUCTION_OK_STATUSES = ("approved", "locked")


def validate_asset(
    asset: ParsedAsset,
    seen_ids: set[str],
    known_ids: set[str],
    include_draft: bool,
) -> list[str]:
    """Tra ve danh sach ly do reject (rong = asset hop le, cho ingest tiep).

    seen_ids: cac ID da chap nhan TRONG LAN CHAY NAY (de bat trung ID).
    known_ids: TOAN BO ID se duoc ingest trong lan chay nay (dung de check
    dependency co ton tai khong - phai truyen vao SAU khi da parse het moi
    file, xem scripts/kb_ingest.py cho 2-pass logic).
    """
    reasons: list[str] = list(asset.parse_errors)  # missing_id/missing_version/missing_status/invalid_encoding/invalid_yaml da co san tu loader

    if "missing_id" not in reasons and asset.id in seen_ids:
        reasons.append("duplicate_id")

    is_production_ok = asset.status in _PRODUCTION_OK_STATUSES
    if not is_production_ok and not (include_draft and asset.status == "draft"):
        reasons.append(f"not_approved (status={asset.status})")

    for dep in asset.dependencies:
        if dep not in known_ids:
            reasons.append(f"missing_dependency ({dep})")

    return reasons
