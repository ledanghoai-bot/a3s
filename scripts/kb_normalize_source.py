"""Chuan hoa cau truc thu muc Knowledge Base tu team Knowledge sang dung
schema trong depository-structure.md (Knowledge Base V2, M1).

Chiu duoc CA 2 phien ban cau truc tu team Knowledge:
- Ban cu (17/7): `skill/` (so it) + FAQ o `docs/faq/`
- Ban da tu sua (18/7): `skills/` (so nhieu) + FAQ da o dung `skills/faq/`
Tu dong nhan dien dung phien ban dang co, khong bao gio bao 'khong thay' sai
chi vi ten thu muc da doi.

Cach dung (sau khi giai nen Knowledge_Base.zip ra 1 thu muc bat ky, vd
C:\\alpha3s\\_kb_source\\Knowledge_Base):
    python scripts/kb_normalize_source.py C:\\alpha3s\\_kb_source\\Knowledge_Base

Ket qua: tao/ghi de thu muc knowledge-base/ o goc repo, cau truc da chuan hoa,
san sang cho scripts/kb_ingest.py doc.

KHONG tu sua noi dung file - chi di chuyen/doi ten thu muc. Sua noi dung la
viec cua team Knowledge, khong phai script nay.
"""

import shutil
import sys
from pathlib import Path


def normalize(source_root: Path, target_root: Path) -> None:
    target_root.mkdir(parents=True, exist_ok=True)

    # skills/ (da dung ten) HOAC skill/ (ten cu, can doi) -> skills/
    skills_src_new = source_root / "skills"
    skill_src_old = source_root / "skill"
    skills_dst = target_root / "skills"

    if skills_src_new.is_dir():
        skill_src = skills_src_new
        print(f"Nhan dien dung cau truc moi: {skill_src} (da dung ten 'skills').")
    elif skill_src_old.is_dir():
        skill_src = skill_src_old
        print(f"Nhan dien cau truc cu: {skill_src} (ten so it 'skill', se doi ten).")
    else:
        skill_src = None

    if skill_src is not None:
        if skills_dst.exists():
            shutil.rmtree(skills_dst)
        shutil.copytree(skill_src, skills_dst)
        print(f"Da copy {skill_src} -> {skills_dst}")
    else:
        print(f"CANH BAO: khong thay {skills_src_new} lẫn {skill_src_old}, bo qua.")

    # FAQ: co the da o skills/faq/ (dung vi tri) HOAC con o docs/faq/ (can chuyen)
    faq_dst = skills_dst / "faq"
    faq_already_in_place = (skills_dst / "faq").is_dir() and any((skills_dst / "faq").glob("*.md"))
    if faq_already_in_place:
        print(f"FAQ da nam dung vi tri {faq_dst} tu buoc copy skills/ o tren, khong can lam gi them.")
    else:
        faq_src = source_root / "docs" / "faq"
        if faq_src.is_dir():
            faq_dst.mkdir(parents=True, exist_ok=True)
            count = 0
            for f in faq_src.glob("*.md"):
                shutil.copy2(f, faq_dst / f.name)
                count += 1
            print(f"Da copy {count} file FAQ: {faq_src} -> {faq_dst}")
        else:
            print(f"CANH BAO: khong thay FAQ o ca {faq_dst} lan {faq_src}, bo qua.")

    # playbooks/ (giu nguyen vi tri, dung spec san)
    pbk_src = source_root / "playbooks"
    pbk_dst = target_root / "playbooks"
    if pbk_src.is_dir():
        if pbk_dst.exists():
            shutil.rmtree(pbk_dst)
        shutil.copytree(pbk_src, pbk_dst)
        print(f"Da copy {pbk_src} -> {pbk_dst}")
    else:
        print(f"CANH BAO: khong thay {pbk_src}, bo qua.")

    # taxonomy.yaml
    tax_src = source_root / "taxonomy.yaml"
    if tax_src.is_file():
        shutil.copy2(tax_src, target_root / "taxonomy.yaml")
        print(f"Da copy {tax_src} -> {target_root / 'taxonomy.yaml'}")
    else:
        print(f"CANH BAO: khong thay {tax_src}, bo qua.")

    print("\nHoan tat chuan hoa. Cay thu muc knowledge-base/ moi:")
    for p in sorted(target_root.rglob("*")):
        if p.is_file():
            print(f"  {p.relative_to(target_root)}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Dung: python scripts/kb_normalize_source.py <duong_dan_thu_muc_Knowledge_Base_da_giai_nen>")
        sys.exit(1)

    source = Path(sys.argv[1]).resolve()
    if not source.is_dir():
        print(f"Loi: khong tim thay thu muc {source}")
        sys.exit(1)

    project_root = Path(__file__).resolve().parent.parent
    target = project_root / "knowledge-base"
    normalize(source, target)
