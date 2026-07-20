"""Xay Knowledge Unit tu ParsedAsset - chunk theo heading, dung thuat toan
TONG QUAT da test voi toan bo file that trong depository truoc khi dua vao
day (xem docs/KNOWLEDGE_BASE_V2_DESIGN-VI.md).

Van de thuc te phai giai quyet: file KHONG YAML dung `#` lam tieu de tai lieu
(1 lan) + `##`/`###` cho section; file CO YAML dung `#` lam section CHINH,
nhung rieng FAQ lai co `##`/`###` long ben trong ma KHONG duoc tach roi (dung
INGESTION_GUIDE.md: "FAQ Object nen la mot Knowledge Unit doc lap").

Thuat toan (da verify dung voi FAQ-BREW-005 vi du chinh xac trong
INGESTION_GUIDE.md):
1. Xac dinh `primary_level` = level cua heading DAU TIEN xuat hien trong file.
2. Nhom cac heading o dung primary_level thanh cac "container".
3. Voi moi container: neu no co heading con TRUC TIEP o primary_level+1 ->
   TACH thanh cac con do (moi con la 1 KU rieng, giu nguyen MOI THU sau hon
   nua ben trong no - KHONG de quy tach them). Neu KHONG co con truc tiep ->
   ca container la 1 KU.

Cach nay tu dong dung cho ca 2 kieu file (YAML dung `#`, khong-YAML dung `##`)
ma khong can biet truoc file thuoc kieu nao - chi can nhin thuc te heading
level nao xuat hien dau tien.
"""

import hashlib
import re

from app.services.kb_ingest.loader import ParsedAsset

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)


def _parse_headings(body: str) -> list[tuple[int, str, int, int]]:
    """Tra ve list (level, text, header_line_start, header_line_end)."""
    result = []
    for m in _HEADING_RE.finditer(body):
        level = len(m.group(1))
        text = m.group(2).strip()
        result.append((level, text, m.start(), m.end()))
    return result


def _ku_suffix(asset_id: str) -> str:
    """'SKL-FAQ-003' -> 'FAQ-003', 'PBK-BRAND-VOICE' -> 'BRAND-VOICE'."""
    for prefix in ("SKL-", "PBK-"):
        if asset_id.startswith(prefix):
            return asset_id[len(prefix):]
    return asset_id


def content_hash(content: str) -> str:
    return hashlib.sha256(content.strip().encode("utf-8")).hexdigest()


def _embedding_text(asset_title: str, heading: str, content: str) -> str:
    """Text RIENG dung de tinh embedding (KHAC voi `content` dung de luu/hien
    thi) - lap lai heading NHIEU LAN, so lan TU DONG CAN CHINH theo do dai
    content, de heading luon chiem it nhat ~50% "trong luong tu" trong ban
    trung binh embedding, bat ke content dai bao nhieu.

    LY DO (bug thuc te 18/7): embedding tinh tren nguyen `content` (dai, gom
    ca doan huong dan/quy tac chi tiet cho bot) bi PHA LOANG tin hieu ngu
    nghia manh cua rieng dong heading - vd cau hoi 'Pha ca phe 3S the nao?'
    khop GAN NGUYEN VAN voi heading 'FAQ-BREW-001 - Pha ca phe 3S the nao?'
    nhung KU van khong duoc vector search xep hang cao vi trung binh embedding
    voi ca doan Answer Guidance/Unit Rule dai hon nhieu.

    LAN SUA DAU (lap co dinh 2 lan) KHONG DU: content dai ~50-80 tu trong khi
    heading chi ~8-10 tu, lap 2 lan van chi chiem ~20% trong so, khong du de
    thay doi thu hang trong vector search. Sua lai: TINH SO LAN LAP DONG theo
    ti le do dai, dam bao heading >= ~50% trong so tu.
    """
    heading_words = max(len(heading.split()), 1)
    content_words = max(len(content.split()), 1)
    repeat = max(3, (content_words // heading_words) + 1)
    repeat = min(repeat, 15)  # tran an toan, tranh lap qua nhieu voi asset cuc dai
    heading_block = "\n".join([heading] * repeat)
    return f"{heading_block}\n\n{content}"


def build_units(asset: ParsedAsset) -> list[dict]:
    """Tra ve list dict {id, heading, content, content_hash, embedding_text} -
    san sang tinh embedding va ghi vao kb_units (xem scripts/kb_ingest.py).
    `embedding_text` la text DUNG DE TINH EMBEDDING (heading duoc nhan trong
    so) - KHAC voi `content` (luu nguyen, dung de hien thi/tra ve provenance).

    GIOI HAN DA BIET: KU ID sinh theo THU TU XUAT HIEN trong file (positional),
    khong phai theo noi dung - neu team Knowledge chen 1 heading moi vao GIUA
    file cu, cac KU o SAU heading do se doi ID. Nang cap thanh content-based ID
    la cai tien ngoai pham vi M1 dau tien (xem thiet ke).
    """
    headings = _parse_headings(asset.body)
    suffix = _ku_suffix(asset.id)

    if not headings:
        content = f"# {asset.title}\n\n{asset.body.strip()}"
        return [{
            "id": f"KU-{suffix}-001",
            "heading": asset.title,
            "content": content,
            "content_hash": content_hash(content),
            "embedding_text": _embedding_text(asset.title, asset.title, content),
        }]

    primary_level = headings[0][0]
    containers = [h for h in headings if h[0] == primary_level]

    raw_units: list[dict] = []
    for i, (level, text, _start, end_line) in enumerate(containers):
        container_end = containers[i + 1][2] if i + 1 < len(containers) else len(asset.body)
        inner = [h for h in headings if end_line <= h[2] < container_end]
        children = [h for h in inner if h[0] == primary_level + 1]

        if children:
            for j, (clevel, ctext, _cstart, cend_line) in enumerate(children):
                child_end = children[j + 1][2] if j + 1 < len(children) else container_end
                body_text = asset.body[cend_line:child_end].strip()
                marks = "#" * clevel
                content = f"# {asset.title}\n\n{marks} {ctext}\n\n{body_text}"
                raw_units.append({"heading": ctext, "content": content})
        else:
            body_text = asset.body[end_line:container_end].strip()
            marks = "#" * level
            content = f"# {asset.title}\n\n{marks} {text}\n\n{body_text}"
            raw_units.append({"heading": text, "content": content})

    units = []
    for idx, u in enumerate(raw_units, start=1):
        units.append({
            "id": f"KU-{suffix}-{idx:03d}",
            "heading": u["heading"],
            "content": u["content"],
            "content_hash": content_hash(u["content"]),
            "embedding_text": _embedding_text(asset.title, u["heading"], u["content"]),
        })
    return units
