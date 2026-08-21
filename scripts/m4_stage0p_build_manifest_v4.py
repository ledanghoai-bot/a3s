#!/usr/bin/env python
"""I-B M4 Stage 0P — sinh `m4_stage0p_rehearsal_manifest_v4.jsonl`.

Đáp `PHASE1B-M4-MANIFEST-V4-PREPARATION-DIRECTIVE-VI.md` (PO chọn đường một-batch tương thích
privacy control **Cap A = 260**, sau khi Amendment 13 abort vì manifest v3 có 315 conversation).

VÌ SAO CHỌN LỌC TỪ v3 THAY VÌ VIẾT MỚI
--------------------------------------
Ground truth của v3 đã qua ba vòng CA review và mang quyết định có thẩm quyền của staff 5 cho
`RG004` (F-V3-01). Viết mới 260 câu = tạo 260 nhãn mới chưa ai kiểm — đúng lớp rủi ro đã cắn dự án
này nhiều lần (Dev từng tự gán nhãn sai cho số điện thoại quốc tế và địa chỉ ở chính bản nháp v3).
Chọn lọc giữ nguyên từng ký tự `canonical_text` và từng offset đã được xác minh.

`v2` và `v3` TUYỆT ĐỐI KHÔNG bị sửa — script này chỉ ĐỌC v3 và GHI ra file v4 mới.

QUY TẮC CHỌN — XÁC ĐỊNH HOÀN TOÀN, KHÔNG NGẪU NHIÊN
---------------------------------------------------
Phân loại từng conversation theo TẬP slot_type mà nó mang (v3 có đúng 7 nhóm), rồi:

| nhóm                    | v3  | v4  | lý do |
|-------------------------|-----|-----|-------|
| `national_id`           |  35 |  35 | đúng 35, không thể bớt mà vẫn ≥ 30 |
| `bank_account`          |  35 |  35 | như trên |
| `address+name+phone`    |  20 |  20 | ca đa-slot, giá trị chẩn đoán cao nhất |
| negative "khó" (v3 mới) |  22 |  22 | đúng loại "dễ bị detector nhận nhầm" directive đòi |
| negative (từ v2)        |  43 |  18 | nâng tổng negative lên 40 (> mức tối thiểu 30) |
| `phone` đơn             |  65 |  53 | giữ tỉ lệ gốc |
| `name` đơn              |  51 |  41 | giữ tỉ lệ gốc |
| `address` đơn           |  44 |  36 | giữ tỉ lệ gốc |
| **tổng**                |**315**|**260**| = Cap A |

Khi phải bớt, KHÔNG cắt đuôi (`[:K]`) mà lấy **giãn đều** theo `floor(i*M/K)`: nếu v3 xếp các mẫu
cùng khuôn cạnh nhau, cắt đuôi sẽ vứt nguyên một khuôn; giãn đều lấy rải khắp danh sách nên giữ
được độ đa dạng — đúng yêu cầu "không dùng bản sao câu chỉ thay đổi nhỏ để tăng đếm".

Chạy (sandbox, KHÔNG chạy trên production):
    python scripts/m4_stage0p_build_manifest_v4.py            # sinh v4 + in bảng kiểm
    python scripts/m4_stage0p_build_manifest_v4.py --inventory  # thêm: xuất inventory cho staff 5
"""
import argparse
import collections
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
V3 = ROOT / "datasets" / "pii" / "m4_stage0p_rehearsal_manifest_v3.jsonl"
V4 = ROOT / "datasets" / "pii" / "m4_stage0p_rehearsal_manifest_v4.jsonl"
INVENTORY = ROOT / "datasets" / "pii" / "m4_stage0p_rehearsal_manifest_v4_inventory.md"

MANIFEST_VERSION_V4 = "m4-stage0p-rehearsal-v4"
CAP_A = 260  # doi chieu lai voi MAX_CONVERSATIONS o buoc kiem tra cuoi

# nhom -> so luong giu lai o v4. Khoa la tuple da sap xep cua cac slot_type trong conversation;
# "<negative>" tach lam 2 nhom con theo nguon (v2 goc vs bo sung moi cua v3).
KEEP = {
    ("national_id",): 35,
    ("bank_account",): 35,
    ("address", "name", "phone"): 20,
    ("phone",): 53,
    ("name",): 41,
    ("address",): 36,
}
KEEP_NEG_HARD = 22   # negative bo sung o v3 (index >= 225) — giu HET
KEEP_NEG_V2 = 18     # negative co san tu v2
V2_LINE_COUNT = 225  # 225 dong dau cua v3 chinh la v2

# --- F-V4-01: sua trung `conversation_key` do generator v3 gay ra --------------------------------
# v3 tai dung prefix `RB` cho 30 ban ghi bank_account (dung 50 ban ghi `name` cua v2) va `RC` cho
# 8 ca cross-slot (dung 40 ban ghi `RC` cua v2) => 38 key bi trung trong v3.
#
# Hau qua THAT trong runner (khong phai gia dinh):
#   - `_seed_synthetic` dong 401 ghi `state.conversation_key_to_conversation_id[key] = conv_id` —
#     day la DICT, nen key trung thi ban SAU ghi de ban TRUOC, lam MAT conversation_id khoi map.
#   - `_label_samples` dong 451 lay map nguoc roi `conv_key_by_id.get(conv_id)`; voi cac
#     conversation bi mat, ket qua la None => `raise SystemExit("FENCE FAIL: sample thuoc
#     conversation_id=... khong nam trong danh sach synthetic tracked")`.
#   => rehearsal ABORT o buoc labeling, va thong bao DO LOI CHO FENCE trong khi nguyen nhan that
#      la trung key manifest. Fail-closed (khong gan nhan sai), nhung chan doan sai huong hoan toan.
#
# Amendment 12 dung v2 (khong trung key) nen khong dinh; Amendment 13 abort o lock_batch, TRUOC
# buoc labeling, nen loi nay chua kip lo ra. v4 sua bang cach doi prefix cho DUNG 38 ban ghi do —
# `canonical_text`, `labeled_slots`, `psid` GIU NGUYEN TUNG KY TU.
KEY_PREFIX_REMAP = {"RB": "BA", "RC": "CX"}  # chi ap dung cho record co index v3 >= V2_LINE_COUNT

MIN_POSITIVE_PER_TYPE = 30
MIN_NEGATIVE = 30
PII_TYPES = ("phone", "name", "address", "national_id", "bank_account")


def load(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def slot_types(rec: dict) -> tuple[str, ...]:
    slots = [s["slot_type"] for m in rec["messages"] for s in m.get("labeled_slots", [])]
    return tuple(sorted(set(slots)))


def spread(items: list, keep: int) -> list:
    """Lay `keep` phan tu GIAN DEU tren `items` (giu nguyen thu tu goc).

    `floor(i*M/K)` cho i=0..K-1 — xac dinh, khong ngau nhien, va phu kin ca dau lan cuoi danh sach.
    Neu keep >= len(items) thi giu nguyen tat ca.
    """
    m = len(items)
    if keep >= m:
        return list(items)
    if keep <= 0:
        return []
    return [items[(i * m) // keep] for i in range(keep)]


def build() -> tuple[list[dict], dict]:
    v3 = load(V3)
    if len(v3) != 315:
        raise SystemExit(f"v3 phai co 315 dong, doc duoc {len(v3)} - DUNG, khong sinh v4")

    groups: dict[tuple, list[tuple[int, dict]]] = collections.defaultdict(list)
    for idx, rec in enumerate(v3):
        key = slot_types(rec)
        if not key:  # negative — tach theo nguon de giu HET nhung ca "kho"
            key = ("<negative_v2>",) if idx < V2_LINE_COUNT else ("<negative_hard>",)
        groups[key].append((idx, rec))

    plan = dict(KEEP)
    plan[("<negative_hard>",)] = KEEP_NEG_HARD
    plan[("<negative_v2>",)] = KEEP_NEG_V2

    unknown = set(groups) - set(plan)
    if unknown:
        raise SystemExit(f"v3 co nhom ngoai du kien {unknown} - DUNG, khong tu doan cach chon")

    selected: list[tuple[int, dict]] = []
    audit = {}
    for key, keep in plan.items():
        available = groups.get(key, [])
        if keep > len(available):
            raise SystemExit(f"nhom {key}: can {keep} nhung v3 chi co {len(available)} - DUNG")
        chosen = spread(available, keep)
        audit["+".join(key)] = {"v3": len(available), "v4": len(chosen)}
        selected.extend(chosen)

    selected.sort(key=lambda t: t[0])  # giu DUNG thu tu goc cua v3 — de doi chieu de dang

    v2_keys = {r["conversation_key"] for r in v3[:V2_LINE_COUNT]}
    out, remapped = [], []
    for idx, rec in selected:
        rec = json.loads(json.dumps(rec))  # ban sao sau, khong dung chung tham chieu voi v3
        rec["manifest_version"] = MANIFEST_VERSION_V4
        # F-V4-01: chi doi key cho record MOI (index >= 225) dang DUNG key cua v2.
        old = rec["conversation_key"]
        if idx >= V2_LINE_COUNT and old in v2_keys:
            new_prefix = KEY_PREFIX_REMAP.get(old[:2])
            if new_prefix is None:
                raise SystemExit(f"key trung {old!r} nhung khong co quy tac remap - DUNG")
            rec["conversation_key"] = new_prefix + old[2:]
            remapped.append((old, rec["conversation_key"]))
        out.append(rec)
    audit["_remapped_keys"] = remapped
    return out, audit


def validate(v4: list[dict]) -> list[str]:
    """Fail-closed: tra ve danh sach van de. Rong = dat."""
    problems = []

    if len(v4) > CAP_A:
        problems.append(f"co {len(v4)} conversation, VUOT Cap A {CAP_A}")

    per = collections.Counter()
    neg = 0
    psids = set()
    conv_keys = set()
    for rec in v4:
        if rec["psid"] in psids:
            problems.append(f"psid trung lap: {rec['psid']}")
        psids.add(rec["psid"])
        # F-V4-01: bat buoc — key trung se lam _seed_synthetic ghi de map va _label_samples
        # abort voi thong bao FENCE FAIL sai huong.
        if rec["conversation_key"] in conv_keys:
            problems.append(f"conversation_key trung lap: {rec['conversation_key']}")
        conv_keys.add(rec["conversation_key"])
        found = False
        for msg in rec["messages"]:
            text = msg["canonical_text"]
            if text != msg["content"]:
                problems.append(f"{rec['psid']}: content != canonical_text")
            for s in msg.get("labeled_slots", []):
                found = True
                per[s["slot_type"]] += 1
                if not (0 <= s["start"] < s["end"] <= len(text)):
                    problems.append(f"{rec['psid']}: offset ngoai bien {s['start']}-{s['end']}")
        if not found:
            neg += 1

    for t in PII_TYPES:
        if per[t] < MIN_POSITIVE_PER_TYPE:
            problems.append(f"{t}: chi {per[t]} positive (<{MIN_POSITIVE_PER_TYPE})")
    if neg < MIN_NEGATIVE:
        problems.append(f"chi {neg} negative (<{MIN_NEGATIVE})")

    gate_eligible = sum(1 for r in v4 if r.get("expect_gate"))
    if gate_eligible < 200:
        problems.append(f"chi {gate_eligible} gate-eligible (<200) - dry-run cua runner se tu choi")

    return problems


def unchanged_check() -> list[str]:
    """v2/v3 phai bat bien — doi chieu hash sau khi ghi v4."""
    expect = {
        "m4_stage0p_rehearsal_manifest_v2.jsonl":
            "5f0f92dbd311d0a4c7d309c01c86b958c81f32126ee531694f4b43a23c54bce5",
        "m4_stage0p_rehearsal_manifest_v3.jsonl":
            "2bebfd62bd21e7cea8a55bccabd3089c357e7649aa10744b06b8c4fef8d802c4",
    }
    problems = []
    for name, want in expect.items():
        got = hashlib.sha256((ROOT / "datasets" / "pii" / name).read_bytes()).hexdigest()
        if got != want:
            problems.append(f"{name} DA BI SUA: {got} != {want}")
    return problems


def write_inventory(v4: list[dict]) -> None:
    """Inventory cho staff 5 review — ID, loai mau, positive/negative, nhan + span THAT SU, va
    doan text da duoc gan nhan (de reviewer doi chieu bang mat, khong phai tu dem offset)."""
    lines = [
        "# Manifest v4 — Inventory cho staff 5 (reviewer/evaluator) review",
        "",
        "Sinh boi `scripts/m4_stage0p_build_manifest_v4.py` tu v3 (v3 KHONG bi sua).",
        f"Tong: **{len(v4)} conversation** (Cap A = {CAP_A}).",
        "",
        "Cot `span_text` la ket qua cat `canonical_text[start:end]` THAT SU — neu offset sai,",
        "doan nay se lech, nen reviewer doi chieu bang mat duoc ma khong can tu dem ky tu.",
        "",
        "| # | conversation_key | psid | loai | slot | span | span_text | canonical_text |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for i, rec in enumerate(v4, 1):
        msg = rec["messages"][0]
        text = msg["canonical_text"]
        slots = msg.get("labeled_slots", [])
        safe = text.replace("|", "\\|")
        if not slots:
            lines.append(f"| {i} | {rec['conversation_key']} | {rec['psid']} | negative | — | — | — | {safe} |")
        for s in slots:
            span_text = text[s["start"]:s["end"]].replace("|", "\\|")
            lines.append(
                f"| {i} | {rec['conversation_key']} | {rec['psid']} | positive | "
                f"{s['slot_type']} | ({s['start']}, {s['end']}) | `{span_text}` | {safe} |")
    INVENTORY.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--inventory", action="store_true", help="xuat them inventory cho staff 5")
    args = ap.parse_args()

    v4, audit = build()

    problems = validate(v4)
    if problems:
        for p in problems:
            print(f"  FAIL  {p}")
        print("\nKHONG ghi v4 vi validation that bai.")
        return 1

    with V4.open("w", encoding="utf-8", newline="\n") as fh:
        for rec in v4:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    unchanged = unchanged_check()
    if unchanged:
        for p in unchanged:
            print(f"  FAIL  {p}")
        return 1

    raw = V4.read_bytes()
    per = collections.Counter()
    neg = 0
    for rec in v4:
        sl = [s["slot_type"] for m in rec["messages"] for s in m.get("labeled_slots", [])]
        if not sl:
            neg += 1
        for s in sl:
            per[s] += 1

    remapped = audit.pop("_remapped_keys", [])
    print("== Chon tu v3 ==")
    print(f"  {'nhom':<26}{'v3':>6}{'v4':>6}")
    for k, v in audit.items():
        print(f"  {k:<26}{v['v3']:>6}{v['v4']:>6}")
    print("\n== F-V4-01: doi conversation_key trung (text/nhan/psid GIU NGUYEN) ==")
    print(f"  so record duoc doi key: {len(remapped)}")
    for old, new in remapped[:5]:
        print(f"    {old} -> {new}")
    if len(remapped) > 5:
        print(f"    ... con {len(remapped) - 5} record nua")
    print("\n== v4 ==")
    print(f"  conversation_count : {len(v4)}  (Cap A = {CAP_A})")
    lf, cr = raw.count(b"\n"), raw.count(b"\r")
    print(f"  bytes / LF / CR    : {len(raw)} / {lf} / {cr}")
    print(f"  gate_eligible      : {sum(1 for r in v4 if r.get('expect_gate'))}  (san >= 200)")
    print(f"  negative           : {neg}  (san >= {MIN_NEGATIVE})")
    for t in PII_TYPES:
        print(f"  {t:<19}: {per[t]}  (san >= {MIN_POSITIVE_PER_TYPE})")
    print(f"\n  sha256             : {hashlib.sha256(raw).hexdigest()}")
    print("  v2/v3 bat bien     : OK (hash khop)")

    if args.inventory:
        write_inventory(v4)
        inv = INVENTORY.read_bytes()
        print(f"\n  inventory          : {INVENTORY.name}")
        print(f"  inventory sha256   : {hashlib.sha256(inv).hexdigest()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
