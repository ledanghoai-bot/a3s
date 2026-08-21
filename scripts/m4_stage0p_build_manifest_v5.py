#!/usr/bin/env python
"""I-B M4 Stage 0P — sinh `m4_stage0p_rehearsal_manifest_v5.jsonl`.

Đáp `PHASE1B-M4-MANIFEST-V5-F-NUM-03-COVERAGE-PREPARATION-DIRECTIVE-VI.md` + PO approval.

MỤC ĐÍCH: v4 **không có** ca conflict/vách đứng/mệnh đề — đã chứng minh: 6 phương án `_has_cue`
khác nhau cho metric y hệt nhau trên v4. Nên correction F-NUM-03 hiện chưa được đo trên đường
production. v5 = 220 record giữ từ v4 + **40 ca F-NUM-03 mới**, vẫn ≤ Cap A 260.

NGUYÊN TẮC QUAN TRỌNG NHẤT — GROUND TRUTH SUY TỪ *POLICY*, KHÔNG PHẢI TỪ DETECTOR
--------------------------------------------------------------------------------
Nhãn của 40 ca mới được Dev viết theo **đúng câu chữ policy PO đã duyệt** (nearest applicable cue
wins; window 80; quy tắc mệnh đề bất đối xứng; reference-exclusion chỉ chặn fallback national-ID;
decision B cho collision nid/bank). Generator **không bao giờ** gọi `detect()` để lấy nhãn.

Nếu lấy nhãn từ detector thì phép đo thành vòng tròn: detector luôn đúng 100% với chính nó. Sự
KHÁC BIỆT giữa nhãn (policy) và output (detector) mới là thứ cần đo — và nếu lệch thì đó là finding
phải báo, không phải chỗ để sửa nhãn cho khớp.

OFFSET: Dev **không đếm tay**. Mỗi ca khai báo đoạn văn bản của span; generator tự `index()` và
assert nó xuất hiện ĐÚNG MỘT LẦN, rồi tự tính start/end.

v2/v3/v4 chỉ được ĐỌC, không bao giờ bị ghi.

Chạy (sandbox):
    python scripts/m4_stage0p_build_manifest_v5.py [--inventory]
"""
import argparse
import collections
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "datasets" / "pii"
V4 = DATA / "m4_stage0p_rehearsal_manifest_v4.jsonl"
V5 = DATA / "m4_stage0p_rehearsal_manifest_v5.jsonl"
INVENTORY = DATA / "m4_stage0p_rehearsal_manifest_v5_inventory.md"
COVERAGE = DATA / "m4_stage0p_rehearsal_manifest_v5_coverage.md"

MANIFEST_VERSION = "m4-stage0p-rehearsal-v5"
CAP_A = 260
MIN_POSITIVE_PER_TYPE = 30
MIN_NEGATIVE = 30
MIN_GATE_ELIGIBLE = 200
MIN_FNUM03_CASES = 40
PII_TYPES = ("phone", "name", "address", "national_id", "bank_account")

V4_SHA256 = "ef6f76c6c8eed4bc8b9abb921d420cdc1bcb3b22801473dd39dfcb65de3c7f17"
V3_SHA256 = "2bebfd62bd21e7cea8a55bccabd3089c357e7649aa10744b06b8c4fef8d802c4"
V2_SHA256 = "5f0f92dbd311d0a4c7d309c01c86b958c81f32126ee531694f4b43a23c54bce5"

# Số record giữ lại từ mỗi nhóm của v4. Chỉ rút từ 3 nhóm đơn-slot dồi dào nhất; các nhóm sát sàn
# (national_id 35, bank_account 35) và nhóm đa-slot giữ NGUYÊN.
KEEP_FROM_V4 = {
    ("national_id",): 35,
    ("bank_account",): 35,
    ("address", "name", "phone"): 20,
    ("phone",): 33,          # v4 có 53
    ("name",): 31,           # v4 có 41
    ("address",): 26,        # v4 có 36
    ("<negative>",): 40,
}

# --------------------------------------------------------------------------------------------
# 40 ca F-NUM-03. Mỗi ca: (key, text, [(slot_type, span_text, confidence, reason), ...], note)
# Danh sách rỗng = no-slot, và note PHẢI giải thích vì sao — `no-slot` cũng là ground truth,
# staff 5 phải soi được lý do (Directive §3).
# --------------------------------------------------------------------------------------------
BANK = ("bank_account", "high", "bank_cue_digits")
NID = ("national_id", "high", "nid_cue_digits")


def _b(span):
    return (BANK[0], span, BANK[1], BANK[2])


def _n(span):
    return (NID[0], span, NID[1], NID[2])


# --- Nhóm A: collision national_id vs bank TRONG CÙNG MỆNH ĐỀ (PO decision B) ---
GROUP_A = [
    ("FNA001", "cccd va stk 079000012371 nhe shop", [_b("079000012371")],
     "A/collision: `stk` gan so hon `cccd` -> bank (decision B)"),
    ("FNA002", "STK và CCCD 079000012372 ạ", [_n("079000012372")],
     "A/collision: `CCCD` gan hon -> national_id; chieu nguoc cua FNA001"),
    ("FNA003", "so tai khoan cccd 079000012373", [_n("079000012373")],
     "A/collision: cue bank dai hon nhung `cccd` van gan so hon -> national_id"),
    ("FNA004", "cmnd va so tai khoan 079000012374 nhe", [_b("079000012374")],
     "A/collision: `so tai khoan` gan hon `cmnd` -> bank"),
    ("FNA005", "can cuoc stk 079000012375", [_b("079000012375")],
     "A/collision: `stk` gan hon `can cuoc` -> bank"),
    ("FNA006", "stk can cuoc 079000012376", [_n("079000012376")],
     "A/collision: `can cuoc` gan hon -> national_id; chieu nguoc cua FNA005"),
    ("FNA007", "tài khoản và căn cước 079000012377 nhé", [_n("079000012377")],
     "A/collision CO DAU: `căn cước` gan hon -> national_id"),
    ("FNA008", "chứng minh và STK 079000012378", [_b("079000012378")],
     "A/collision CO DAU: `STK` gan hon -> bank"),
]

# --- Nhóm B: cửa sổ / biên. Dùng số 11 chữ số cho ca NGOÀI cửa sổ, vì số 12 chữ số không cue sẽ
#     rơi vào fallback national_id (MEDIUM) chứ không phải no-slot. ---
_FILL = "cua em ben ngan hang do la"                       # 26 ký tự
GROUP_B = [
    ("FNB001", "stk cua em o ngan hang ben do la 71000123421", [_b("71000123421")],
     "B/window: cue cach ~29-35 ky tu, TRONG cua so 80 -> bank"),
    ("FNB002", "so tai khoan cua minh ben ngan hang ACB la 71000123422", [_b("71000123422")],
     "B/window: cue cach ~42 ky tu -> bank"),
    ("FNB003", "stk minh dang dung o ngan hang thuong mai co phan do la 71000123423",
     [_b("71000123423")], "B/window: cue cach ~55 ky tu -> bank"),
    ("FNB004", "stk cua em mo tai chi nhanh ngan hang gan nha ba ngoai o que la 71000123424",
     [_b("71000123424")], "B/window: cue cach ~63 ky tu, van trong 80 -> bank"),
    ("FNB005",
     "stk cua em mo tai chi nhanh ngan hang gan nha ba ngoai o duoi que mien tay xa lam la 71000123425",
     [], "B/window: cue cach >80 ky tu -> NGOAI cua so -> no-slot. So 11 chu so nen KHONG roi vao "
         "fallback national_id 12 so"),
    ("FNB006",
     "stk nha em mo tu hoi con o duoi que ngoai kia lau lam roi khong nho ro nam nao nua la 71000123426",
     [], "B/window: cue cach xa hon nua -> no-slot"),
    ("FNB007", "cccd cua minh dang cam theo trong vi la 079000012427", [_n("079000012427")],
     "B/window: cue giay to cach ~38 ky tu -> national_id"),
    ("FNB008", "can cuoc cua em vua lam lai o phuong hoi thang truoc la 079000012428",
     [_n("079000012428")], "B/window: cue giay to cach ~55 ky tu -> national_id"),
]

# --- Nhóm C: bất đối xứng mệnh đề. Cue CÙNG loại vượt dấu phẩy/xuống dòng; cue CẠNH TRANH không. ---
GROUP_C = [
    ("FNC001", "so tai khoan cua minh, 71000123431", [_b("71000123431")],
     "C/clause: cue CUNG loai vuot dau phay -> bank (kieu viet rat pho bien)"),
    ("FNC002", "stk cua em,\n71000123432", [_b("71000123432")],
     "C/clause: cue CUNG loai vuot XUONG DONG -> bank"),
    ("FNC003", "stk cua em, vietcombank, 71000123433", [_b("71000123433")],
     "C/clause: cue CUNG loai vuot HAI menh de -> bank"),
    ("FNC004", "ma giao dich da xong roi, stk 71000123434", [_b("71000123434")],
     "C/clause: cue CANH TRANH o menh de TRUOC -> khong chan duoc -> bank"),
    ("FNC005", "so tai khoan, ma giao dich 71000123435", [],
     "C/clause: cue canh tranh `ma giao dich` gan hon trong CUNG menh de; cue bank o menh de "
     "truoc -> no-slot"),
    ("FNC006", "cccd cua minh, 079000012436", [_n("079000012436")],
     "C/clause: cue giay to CUNG loai vuot dau phay -> national_id"),
    ("FNC007", "ma don da giao xong, cccd 079000012437", [_n("079000012437")],
     "C/clause: cue loai tru o menh de truoc -> khong chan -> national_id"),
    ("FNC008", "cccd 079000012438, stk 71000123439", [_n("079000012438"), _b("71000123439")],
     "C/clause: HAI PII, moi so lay cue cua menh de rieng -> khong ro ri cheo menh de"),
]

# --- Nhóm D: reference exclusion. Dùng số 12 chữ số để chứng minh KHÔNG rơi vào fallback nid. ---
GROUP_D = [
    ("FND001", "ma tham chieu 079000012441 nhe", [],
     "D/reference: `ma tham chieu` -> KHONG fallback national_id (so 12 chu so)"),
    ("FND002", "mã vận đơn 079000012442 đâu rồi shop", [],
     "D/reference CO DAU: `mã vận đơn` -> no-slot"),
    ("FND003", "ma tra cuu 079000012443 la gi vay", [],
     "D/reference: `ma tra cuu` -> no-slot"),
    ("FND004", "mã hóa đơn 079000012444 shop ơi", [],
     "D/reference CO DAU: `mã hóa đơn` -> no-slot"),
    ("FND005", "cho em xin lai ma van don 079000012445", [],
     "D/reference: cue nam giua cau -> no-slot"),
    ("FND006", "ma tham chieu giao dich 079000012446", [],
     "D/reference: cue tham chieu ghep voi tu tai chinh -> van no-slot"),
    ("FND007", "ma tra cuu don hang 079000012447 nhe", [],
     "D/reference: hai cue loai tru cung luc -> no-slot"),
    ("FND008", "mã hóa đơn của em là 079000012448", [],
     "D/reference CO DAU: cue cach so vai tu -> no-slot"),
]

# --- Nhóm E: bank cue thắng reference khi gần hơn + biến thể thực tế ---
GROUP_E = [
    ("FNE001", "ma tham chieu cho stk 71000123451", [_b("71000123451")],
     "E/override: `stk` gan hon `ma tham chieu` -> bank (rang buoc PO §1.4)"),
    ("FNE002", "ma van don xong roi stk 71000123452 nhe", [_b("71000123452")],
     "E/override KHONG DAU CAU: cue bank gan hon -> bank"),
    ("FNE003", "stk 🌟 71000123453", [_b("71000123453")],
     "E/emoji: emoji ngoai BMP chen giua cue va so -> bank"),
    ("FNE004", "số tài khoản 71000123454 nhé", [_b("71000123454")],
     "E/co dau: bien the co dau -> bank"),
    ("FNE005", "so tai khoan 71000123455 nhe", [_b("71000123455")],
     "E/khong dau: bien the khong dau cua FNE004 -> bank"),
    ("FNE006", "stk so tai khoan 71000123456", [_b("71000123456")],
     "E/tie cung nhom: hai cue CUNG nhom bank ke nhau -> bank, ket qua xac dinh"),
    ("FNE007", "ma hoa don va stk 71000123457", [_b("71000123457")],
     "E/override: `stk` gan hon `ma hoa don` -> bank"),
    ("FNE008", "chuyen khoan qua stk 71000123458 giup em", [_b("71000123458")],
     "E/thuc te: cau chuyen khoan thong thuong -> bank"),
]

GROUPS = [
    ("A same-clause nid/bank collision", GROUP_A),
    ("B window / boundary", GROUP_B),
    ("C clause asymmetry", GROUP_C),
    ("D reference exclusion", GROUP_D),
    ("E bank-cue override + realistic", GROUP_E),
]

NEW_PSID_BASE = 400          # v4 dùng tới 000314 -> 000401+ chắc chắn không đụng


def load(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def slot_key(rec: dict) -> tuple:
    ks = tuple(sorted({s["slot_type"] for m in rec["messages"]
                       for s in m.get("labeled_slots", [])}))
    return ks if ks else ("<negative>",)


def spread(items: list, keep: int) -> list:
    """Lấy `keep` phần tử giãn đều — không cắt đuôi, để không vứt nguyên một khuôn câu."""
    m = len(items)
    if keep >= m:
        return list(items)
    return [items[(i * m) // keep] for i in range(keep)]


def build_new_records() -> list[dict]:
    out = []
    idx = NEW_PSID_BASE
    for group_name, cases in GROUPS:
        for key, text, spans, note in cases:
            slots = []
            for slot_type, span_text, conf, reason in spans:
                if text.count(span_text) != 1:
                    raise SystemExit(
                        f"{key}: doan {span_text!r} xuat hien {text.count(span_text)} lan trong "
                        f"cau — offset se mo ho, DUNG")
                start = text.index(span_text)
                slots.append({"slot_type": slot_type, "start": start,
                              "end": start + len(span_text),
                              "confidence": conf, "reason": reason})
            slots.sort(key=lambda s: s["start"])
            idx += 1
            out.append({
                "manifest_version": MANIFEST_VERSION,
                "psid": f"m4synthrehearsalv1_{idx:06d}",
                "conversation_key": key,
                "messages": [{"role": "customer", "content": text,
                              "canonical_text": text, "labeled_slots": slots}],
                "expect_gate": True,
                "note": note,
                "fnum03_group": group_name,
            })
    return out


def build() -> tuple[list[dict], dict]:
    v4 = load(V4)
    if len(v4) != 260:
        raise SystemExit(f"v4 phai co 260 dong, doc duoc {len(v4)} - DUNG")

    groups = collections.defaultdict(list)
    for rec in v4:
        groups[slot_key(rec)].append(rec)

    unknown = set(groups) - set(KEEP_FROM_V4)
    if unknown:
        raise SystemExit(f"v4 co nhom ngoai du kien {unknown} - DUNG")

    retained, audit = [], {}
    for key, keep in KEEP_FROM_V4.items():
        avail = groups.get(key, [])
        if keep > len(avail):
            raise SystemExit(f"nhom {key}: can {keep} nhung v4 chi co {len(avail)} - DUNG")
        chosen = spread(avail, keep)
        audit["+".join(key)] = {"v4": len(avail), "v5": len(chosen)}
        retained.extend(chosen)

    out = []
    for rec in retained:
        rec = json.loads(json.dumps(rec))
        rec["manifest_version"] = MANIFEST_VERSION
        rec["source"] = "v4_retained"
        out.append(rec)

    new = build_new_records()
    for rec in new:
        rec["source"] = "fnum03_new"
    out.extend(new)

    audit["_new_fnum03"] = len(new)
    return out, audit


def validate(v5: list[dict]) -> list[str]:
    problems = []

    if len(v5) > CAP_A:
        problems.append(f"co {len(v5)} conversation, VUOT Cap A {CAP_A}")

    psids, keys = set(), set()
    per, neg = collections.Counter(), 0
    for rec in v5:
        if rec["psid"] in psids:
            problems.append(f"psid trung lap: {rec['psid']}")
        psids.add(rec["psid"])
        if rec["conversation_key"] in keys:
            problems.append(f"conversation_key trung lap: {rec['conversation_key']}")
        keys.add(rec["conversation_key"])
        if len(rec["messages"]) != 1:
            problems.append(f"{rec['conversation_key']}: phai dung 1 message")
        found = False
        for msg in rec["messages"]:
            text = msg["canonical_text"]
            if text != msg["content"]:
                problems.append(f"{rec['conversation_key']}: content != canonical_text")
            for s in msg.get("labeled_slots", []):
                found = True
                per[s["slot_type"]] += 1
                if not (0 <= s["start"] < s["end"] <= len(text)):
                    problems.append(f"{rec['conversation_key']}: offset ngoai bien")
        if not found:
            neg += 1

    for t in PII_TYPES:
        if per[t] < MIN_POSITIVE_PER_TYPE:
            problems.append(f"{t}: chi {per[t]} positive (<{MIN_POSITIVE_PER_TYPE})")
    if neg < MIN_NEGATIVE:
        problems.append(f"chi {neg} negative (<{MIN_NEGATIVE})")

    gate = sum(1 for r in v5 if r.get("expect_gate"))
    if gate < MIN_GATE_ELIGIBLE:
        problems.append(f"chi {gate} gate-eligible (<{MIN_GATE_ELIGIBLE})")

    n_new = sum(1 for r in v5 if r.get("source") == "fnum03_new")
    if n_new < MIN_FNUM03_CASES:
        problems.append(f"chi {n_new} ca F-NUM-03 (<{MIN_FNUM03_CASES})")
    by_group = collections.Counter(r.get("fnum03_group") for r in v5 if r.get("fnum03_group"))
    for gname, _ in GROUPS:
        if by_group[gname] < 8:
            problems.append(f"nhom {gname}: chi {by_group[gname]} ca (<8)")

    return problems


def historical_unchanged() -> list[str]:
    problems = []
    for name, want in (("m4_stage0p_rehearsal_manifest_v2.jsonl", V2_SHA256),
                       ("m4_stage0p_rehearsal_manifest_v3.jsonl", V3_SHA256),
                       ("m4_stage0p_rehearsal_manifest_v4.jsonl", V4_SHA256)):
        got = hashlib.sha256((DATA / name).read_bytes()).hexdigest()
        if got != want:
            problems.append(f"{name} DA BI SUA: {got} != {want}")
    return problems


def write_inventory(v5: list[dict]) -> None:
    lines = [
        "# Manifest v5 — Inventory cho staff 5 review",
        "",
        "Cột `span_text` là kết quả cắt `canonical_text[start:end]` **thật sự** — offset sai thì",
        "đoạn này lệch ngay, reviewer đối chiếu bằng mắt được mà không phải đếm ký tự.",
        "",
        "`no-slot` **cũng là ground truth** và phải được review: cột `note` giải thích vì sao",
        "không gán nhãn (Directive §3).",
        "",
        "| # | key | psid | nguồn | nhóm F-NUM-03 | slot | span | span_text | canonical_text | note |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for i, rec in enumerate(v5, 1):
        msg = rec["messages"][0]
        text = msg["canonical_text"]
        safe = text.replace("|", "\\|").replace("\n", "\\n")
        note = rec.get("note", "").replace("|", "\\|")
        grp = rec.get("fnum03_group", "—")
        src = rec.get("source", "v4_retained")
        slots = msg.get("labeled_slots", [])
        if not slots:
            lines.append(f"| {i} | {rec['conversation_key']} | {rec['psid']} | {src} | {grp} | "
                         f"**no-slot** | — | — | {safe} | {note} |")
        for s in slots:
            st = text[s["start"]:s["end"]].replace("|", "\\|").replace("\n", "\\n")
            lines.append(f"| {i} | {rec['conversation_key']} | {rec['psid']} | {src} | {grp} | "
                         f"{s['slot_type']} | ({s['start']}, {s['end']}) | `{st}` | {safe} | {note} |")
    INVENTORY.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def write_coverage(v5: list[dict]) -> None:
    lines = [
        "# Manifest v5 — Coverage matrix F-NUM-03",
        "",
        "Ánh xạ 40 ca chuyên biệt → nhóm / cue / mệnh đề / kết quả mong đợi.",
        "",
        "| key | nhóm | kết quả mong đợi | lý do (theo policy, KHÔNG theo detector) | câu |",
        "|---|---|---|---|---|",
    ]
    for rec in v5:
        if rec.get("source") != "fnum03_new":
            continue
        msg = rec["messages"][0]
        text = msg["canonical_text"].replace("|", "\\|").replace("\n", "\\n")
        slots = msg.get("labeled_slots", [])
        outcome = ", ".join(s["slot_type"] for s in slots) if slots else "**no-slot**"
        note = rec["note"].replace("|", "\\|")
        lines.append(f"| {rec['conversation_key']} | {rec['fnum03_group']} | {outcome} | {note} | {text} |")
    lines += ["", "## Tổng hợp theo nhóm", "",
              "| nhóm | số ca | bank | national_id | no-slot |", "|---|---|---|---|---|"]
    agg = collections.defaultdict(lambda: collections.Counter())
    for rec in v5:
        if rec.get("source") != "fnum03_new":
            continue
        g = rec["fnum03_group"]
        agg[g]["n"] += 1
        sl = rec["messages"][0].get("labeled_slots", [])
        if not sl:
            agg[g]["no_slot"] += 1
        for s in sl:
            agg[g][s["slot_type"]] += 1
    for gname, _ in GROUPS:
        c = agg[gname]
        lines.append(f"| {gname} | {c['n']} | {c['bank_account']} | {c['national_id']} | {c['no_slot']} |")
    COVERAGE.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--inventory", action="store_true")
    args = ap.parse_args()

    v5, audit = build()
    problems = validate(v5)
    if problems:
        for p in problems:
            print(f"  FAIL  {p}")
        print("\nKHONG ghi v5 vi validation that bai.")
        return 1

    with V5.open("w", encoding="utf-8", newline="\n") as fh:
        for rec in v5:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    unchanged = historical_unchanged()
    if unchanged:
        for p in unchanged:
            print(f"  FAIL  {p}")
        return 1

    raw = V5.read_bytes()
    per, neg = collections.Counter(), 0
    for rec in v5:
        sl = [s["slot_type"] for m in rec["messages"] for s in m.get("labeled_slots", [])]
        if not sl:
            neg += 1
        for s in sl:
            per[s] += 1

    new_n = audit.pop("_new_fnum03")
    print("== Giu tu v4 ==")
    print(f"  {'nhom':<26}{'v4':>6}{'v5':>6}")
    for k, v in audit.items():
        print(f"  {k:<26}{v['v4']:>6}{v['v5']:>6}")
    print(f"  {'(tong giu lai)':<26}{260:>6}{sum(v['v5'] for v in audit.values()):>6}")
    print(f"\n== Ca F-NUM-03 moi: {new_n} ==")
    by_group = collections.Counter(r.get("fnum03_group") for r in v5 if r.get("fnum03_group"))
    for gname, _ in GROUPS:
        print(f"  {gname:<40}{by_group[gname]:>4}  (toi thieu 8)")
    print("\n== v5 ==")
    print(f"  conversation_count : {len(v5)}  (Cap A = {CAP_A})")
    lf, cr = raw.count(b"\n"), raw.count(b"\r")
    print(f"  bytes / LF / CR    : {len(raw)} / {lf} / {cr}")
    print(f"  gate_eligible      : {sum(1 for r in v5 if r.get('expect_gate'))}  (san >= {MIN_GATE_ELIGIBLE})")
    print(f"  negative           : {neg}  (san >= {MIN_NEGATIVE})")
    for t in PII_TYPES:
        print(f"  {t:<19}: {per[t]}  (san >= {MIN_POSITIVE_PER_TYPE})")
    print(f"\n  sha256             : {hashlib.sha256(raw).hexdigest()}")
    print("  v2/v3/v4 bat bien  : OK")

    if args.inventory:
        write_inventory(v5)
        write_coverage(v5)
        print(f"\n  inventory sha256   : {hashlib.sha256(INVENTORY.read_bytes()).hexdigest()}")
        print(f"  coverage  sha256   : {hashlib.sha256(COVERAGE.read_bytes()).hexdigest()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
