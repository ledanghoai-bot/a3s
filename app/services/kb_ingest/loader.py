"""Parse front matter tu file Skill/Playbook - chiu duoc 4 dinh dang khac
nhau da phat hien trong depository that cua team Knowledge (xem
docs/KNOWLEDGE_BASE_V2_DESIGN-VI.md muc "3 phat hien quan trong"):

1. YAML chuan (---\\nkey: value\\n---) - vd SAL, CON, FAQ, PBK
2. Text 1 dong: "Status: Approved Version: 1.0.0" - vd BRAND-001, CS-001
3. Bold 1 dong: "**Status:** Approved & Locked **Version:** 1.0.0" - vd PRD-003
4. Bold nhieu dong, co "\\" cuoi dong: "**Status:** Draft for Review\\" - vd PRD-004

Da test qua toan bo 22 file that trong depository truoc khi dua vao code
chinh thuc (khong doan mo hinh - xem lich su phien lam viec).
"""

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

# Regex lay ID + title tu dong "# SKL-XXX --- Ten" (dung khi khong co YAML
# hoac YAML thieu id/title).
_TITLE_LINE_RE = re.compile(r"^#\s+([A-Z]+-[A-Z]+-\d+)\s*-+\s*(.+?)\s*$", re.MULTILINE)

# Regex linh hoat bat "Status" + "Version", chiu duoc **, dau \ cuoi dong,
# va cac cach dien dat nhu "Approved & Locked"/"Draft for Review"/"Draft v0.3".
_STATUS_VERSION_RE = re.compile(
    r"\*{0,2}Status:?\*{0,2}\s*(.+?)\s*\\?\s*\n?\s*"
    r"\*{0,2}Version:?\*{0,2}\s*([\d.]+)",
    re.IGNORECASE,
)

_KNOWN_STATUSES = ("draft", "review", "approved", "locked", "superseded", "archived")


def _normalize_status(raw: str) -> str:
    """Chuan hoa moi bien the status ve dung 1 trong 6 gia tri chuan cua
    taxonomy.yaml. UU TIEN TU DAU TIEN cua chuoi (vd "Draft for Review" phai
    la 'draft', khong duoc bi nham thanh 'review' chi vi chua substring do -
    bug thuc te da gap va sua khi test voi du lieu that)."""
    low = raw.strip().lower()
    words = low.split()
    first_word = words[0].strip("*:&") if words else ""
    if first_word in _KNOWN_STATUSES:
        return first_word
    # Fallback: scan substring neu tu dau khong khop truc tiep
    for candidate in ("approved", "locked", "superseded", "archived", "draft", "review"):
        if candidate in low:
            return candidate
    return "draft"  # mac dinh AN TOAN nhat neu khong doc duoc - coi nhu chua duyet


@dataclass
class ParsedAsset:
    id: str
    title: str
    status: str  # da chuan hoa: draft/review/approved/locked/superseded/archived
    version: str
    domain: str | None
    priority: str | None
    language: str
    dependencies: list[str]
    raw_frontmatter: dict
    body: str  # noi dung SAU phan front matter/status line, dung de chunk (M1 unit_builder)
    content_hash: str
    source_path: str
    parse_errors: list[str] = field(default_factory=list)


def parse_asset_file(path: Path) -> ParsedAsset:
    """Parse 1 file .md thanh ParsedAsset. Khong bao gio raise loi - moi truong
    hop khong doc duoc deu duoc ghi vao parse_errors de AssetValidator (buoc
    sau) quyet dinh co reject hay khong, thay vi crash toan bo pipeline ingest
    chi vi 1 file loi."""
    errors: list[str] = []
    raw_bytes = path.read_bytes()
    try:
        text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        errors.append("invalid_encoding")
        text = raw_bytes.decode("utf-8", errors="replace")

    content_hash = hashlib.sha256(raw_bytes).hexdigest()
    frontmatter: dict = {}
    body = text

    if text.lstrip().startswith("---"):
        parts = text.lstrip().split("---", 2)
        if len(parts) >= 3:
            try:
                frontmatter = yaml.safe_load(parts[1]) or {}
            except yaml.YAMLError:
                errors.append("invalid_yaml")
            body = parts[2]

    asset_id = frontmatter.get("id")
    title = frontmatter.get("title")
    status_raw = frontmatter.get("status")
    version = str(frontmatter.get("version")) if frontmatter.get("version") is not None else None
    domain = frontmatter.get("domain")
    priority = frontmatter.get("priority")
    language = frontmatter.get("language", "vi")
    dependencies = frontmatter.get("dependencies") or []

    if not asset_id or not title:
        m = _TITLE_LINE_RE.search(text)
        if m:
            asset_id = asset_id or m.group(1)
            title = title or m.group(2).strip()

    if status_raw is None or version is None:
        m = _STATUS_VERSION_RE.search(text)
        if m:
            if status_raw is None:
                status_raw = m.group(1)
            if version is None:
                version = m.group(2)

    status = _normalize_status(status_raw) if status_raw else "draft"

    if not asset_id:
        errors.append("missing_id")
    if not version:
        errors.append("missing_version")
        version = "0.0.0"
    if status_raw is None:
        errors.append("missing_status")

    return ParsedAsset(
        id=asset_id or f"UNKNOWN-{path.stem}",
        title=title or path.stem,
        status=status,
        version=version,
        domain=domain,
        priority=priority,
        language=language,
        dependencies=dependencies if isinstance(dependencies, list) else [],
        raw_frontmatter=frontmatter,
        body=body,
        content_hash=content_hash,
        source_path=str(path),
        parse_errors=errors,
    )


def discover_files(root: Path) -> list[Path]:
    """Tim toan bo file .md trong skills/ + playbooks/ (KHONG dong docs/,
    implementation/ - dung theo INGESTION_GUIDE.md muc 'Khong embed mac dinh':
    README/CHANGELOG/ADR/roadmap/governance/developer docs khong duoc ingest)."""
    files: list[Path] = []
    for sub in ("skills", "playbooks"):
        d = root / sub
        if d.is_dir():
            files.extend(sorted(d.rglob("*.md")))
    return files
