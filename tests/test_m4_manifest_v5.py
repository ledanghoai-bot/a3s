"""I-B M4 — CI invariant tests cho manifest v5 (đáp F-V5-01).

CA từ chối PR #23 vòng 1 vì generator validation chỉ chạy **thủ công**: full suite vẫn `384 passed`
y hệt PR #22, tức không có gì trong CI khoá dataset. Nếu v5 hoặc generator bị sửa về sau, CI sẽ
không phát hiện — trong khi chính v5 là cơ sở để đóng F-NUM-03.

Toàn bộ test dưới đây chạy **không cần DB/Redis/production**.
"""
import collections
import hashlib
import importlib.util
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

DATA = os.path.join(ROOT, "datasets", "pii")
V2 = os.path.join(DATA, "m4_stage0p_rehearsal_manifest_v2.jsonl")
V3 = os.path.join(DATA, "m4_stage0p_rehearsal_manifest_v3.jsonl")
V4 = os.path.join(DATA, "m4_stage0p_rehearsal_manifest_v4.jsonl")
V5 = os.path.join(DATA, "m4_stage0p_rehearsal_manifest_v5.jsonl")
INVENTORY = os.path.join(DATA, "m4_stage0p_rehearsal_manifest_v5_inventory.md")
COVERAGE = os.path.join(DATA, "m4_stage0p_rehearsal_manifest_v5_coverage.md")

V2_SHA = "5f0f92dbd311d0a4c7d309c01c86b958c81f32126ee531694f4b43a23c54bce5"
V3_SHA = "2bebfd62bd21e7cea8a55bccabd3089c357e7649aa10744b06b8c4fef8d802c4"
V4_SHA = "ef6f76c6c8eed4bc8b9abb921d420cdc1bcb3b22801473dd39dfcb65de3c7f17"
V5_SHA = "125a5183825feb42f61bcfdd1b39ff1b89a8e4afe47a1222d9f6e654d02cf52f"
INVENTORY_SHA = "0a9f706527428a2fd975f76896b8763c24dd0c148341b19db0c9ea55d2fbc997"
COVERAGE_SHA = "5df7d91a2230fe495d109d81a86a960dd744095c71784416dba5249ac53e8c9d"

CAP_A = 260
MIN_POSITIVE_PER_TYPE = 30
MIN_NEGATIVE = 30
MIN_GATE_ELIGIBLE = 200
PII_TYPES = ("phone", "name", "address", "national_id", "bank_account")

# `scripts/` không phải package — nạp theo đường dẫn, không thêm __init__.py.
_spec = importlib.util.spec_from_file_location(
    "m4_build_v5_for_test", os.path.join(ROOT, "scripts", "m4_stage0p_build_manifest_v5.py"))
gen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gen)


def _sha(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


@pytest.fixture(scope="module")
def v5():
    with open(V5, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


@pytest.fixture(scope="module")
def new40(v5):
    return [r for r in v5 if r.get("source") == "fnum03_new"]


# --------------------------------------------------------------------------------------------
# (1) Hash / định dạng / bất biến lịch sử
# --------------------------------------------------------------------------------------------

@pytest.mark.parametrize("path,expected,label", [
    (V2, V2_SHA, "v2"), (V3, V3_SHA, "v3"), (V4, V4_SHA, "v4"),
    (V5, V5_SHA, "v5"), (INVENTORY, INVENTORY_SHA, "inventory"), (COVERAGE, COVERAGE_SHA, "coverage"),
])
def test_hash_artifact(path, expected, label):
    """v2/v3/v4 bất biến; v5 + inventory + coverage khoá đúng hash đã nộp cho CA."""
    assert _sha(path) == expected, f"{label} đổi hash"


def test_v5_dung_260_dong_va_LF_only():
    raw = open(V5, "rb").read()
    assert raw.count(b"\r") == 0, "có CR — phải LF-only"
    assert raw.count(b"\n") == CAP_A


# --------------------------------------------------------------------------------------------
# (2) Schema / offset / định danh duy nhất
# --------------------------------------------------------------------------------------------

def test_psid_va_conversation_key_duy_nhat(v5):
    psids = [r["psid"] for r in v5]
    keys = [r["conversation_key"] for r in v5]
    assert len(psids) == len(set(psids)), "psid trùng lặp"
    assert len(keys) == len(set(keys)), "conversation_key trùng lặp"


def test_moi_conversation_dung_mot_message(v5):
    for rec in v5:
        assert len(rec["messages"]) == 1, rec["conversation_key"]


def test_offset_va_canonical_text(v5):
    for rec in v5:
        msg = rec["messages"][0]
        text = msg["canonical_text"]
        assert text == msg["content"], rec["conversation_key"]
        for s in msg.get("labeled_slots", []):
            assert 0 <= s["start"] < s["end"] <= len(text), \
                f"{rec['conversation_key']}: offset {s['start']}-{s['end']} ngoài biên"
            assert set(s) == {"slot_type", "start", "end", "confidence", "reason"}, \
                f"{rec['conversation_key']}: schema slot sai"


def test_span_khong_chong_lan_trong_cung_message(v5):
    for rec in v5:
        slots = sorted(rec["messages"][0].get("labeled_slots", []), key=lambda s: s["start"])
        for a, b in zip(slots, slots[1:]):
            assert a["end"] <= b["start"], f"{rec['conversation_key']}: span chồng lấn"


# --------------------------------------------------------------------------------------------
# (3) Cap A / gate-eligible / sàn acceptance
# --------------------------------------------------------------------------------------------

def test_cap_a(v5):
    assert len(v5) <= CAP_A
    assert len(v5) == CAP_A


def test_gate_eligible(v5):
    assert sum(1 for r in v5 if r.get("expect_gate")) >= MIN_GATE_ELIGIBLE


def _counts(recs):
    per, neg = collections.Counter(), 0
    for rec in recs:
        sl = [s["slot_type"] for m in rec["messages"] for s in m.get("labeled_slots", [])]
        if not sl:
            neg += 1
        for s in sl:
            per[s] += 1
    return per, neg


@pytest.mark.parametrize("slot_type", PII_TYPES)
def test_san_positive_moi_loai(v5, slot_type):
    per, _ = _counts(v5)
    assert per[slot_type] >= MIN_POSITIVE_PER_TYPE, f"{slot_type} chỉ có {per[slot_type]}"


def test_san_negative(v5):
    _, neg = _counts(v5)
    assert neg >= MIN_NEGATIVE


# --------------------------------------------------------------------------------------------
# (4) Đúng 40 ca F-NUM-03, đúng 8 ca mỗi nhóm A–E
# --------------------------------------------------------------------------------------------

def test_dung_40_ca_fnum03(new40):
    assert len(new40) == 40


def test_moi_record_co_source_hop_le(v5):
    assert {r.get("source") for r in v5} == {"v4_retained", "fnum03_new"}


@pytest.mark.parametrize("group_prefix", ["A ", "B ", "C ", "D ", "E "])
def test_dung_8_ca_moi_nhom(new40, group_prefix):
    n = sum(1 for r in new40 if r["fnum03_group"].startswith(group_prefix))
    assert n == 8, f"nhóm {group_prefix.strip()} có {n} ca"


def test_ca_moi_khong_lay_tu_v4(new40):
    """psid của ca mới phải nằm ngoài dải v4 — chống trùng khi rehearsal seed."""
    with open(V4, encoding="utf-8") as fh:
        v4_psids = {json.loads(l)["psid"] for l in fh if l.strip()}
    for rec in new40:
        assert rec["psid"] not in v4_psids, rec["psid"]


# --------------------------------------------------------------------------------------------
# (5) Expected outcomes — khoá đúng ngữ nghĩa policy, không chỉ đếm số lượng
# --------------------------------------------------------------------------------------------

def _slots_of(rec):
    return [(s["slot_type"], rec["messages"][0]["canonical_text"][s["start"]:s["end"]])
            for s in rec["messages"][0].get("labeled_slots", [])]


def _by_key(recs):
    return {r["conversation_key"]: r for r in recs}


def test_collision_ca_HAI_huong(new40):
    """Nhóm A phải có cả hướng bank thắng LẪN hướng national_id thắng.

    Nếu chỉ có một hướng thì tập dữ liệu không phân biệt được 'cue gần nhất thắng' với
    'một loại luôn thắng loại kia'.
    """
    a = [r for r in new40 if r["fnum03_group"].startswith("A ")]
    kinds = collections.Counter(s["slot_type"] for r in a
                                for s in r["messages"][0]["labeled_slots"])
    assert kinds["bank_account"] >= 1 and kinds["national_id"] >= 1
    assert kinds["bank_account"] + kinds["national_id"] == 8


def test_boundary_co_ca_TRONG_lan_NGOAI_cua_so(new40):
    b = [r for r in new40 if r["fnum03_group"].startswith("B ")]
    labelled = [r for r in b if r["messages"][0]["labeled_slots"]]
    no_slot = [r for r in b if not r["messages"][0]["labeled_slots"]]
    assert len(labelled) >= 1, "thiếu ca cue TRONG cửa sổ"
    assert len(no_slot) >= 1, "thiếu ca cue NGOÀI cửa sổ (no-slot)"


def test_boundary_no_slot_KHONG_dung_so_12_chu_so(new40):
    """Số 12 chữ số không cue sẽ rơi vào fallback national_id — dùng nó cho ca 'ngoài cửa sổ'
    sẽ khiến kỳ vọng no-slot sai về bản chất, không phải vì cửa sổ."""
    import re
    for rec in new40:
        if rec["fnum03_group"].startswith("B ") and not rec["messages"][0]["labeled_slots"]:
            digits = re.findall(r"\d+", rec["messages"][0]["canonical_text"])
            assert digits, rec["conversation_key"]
            assert all(len(d) != 12 for d in digits), \
                f"{rec['conversation_key']}: dùng số 12 chữ số cho ca ngoài cửa sổ"


def test_clause_co_ca_khong_ro_ri_cheo_menh_de(new40):
    """Nhóm C phải có ít nhất một ca 2 PII ở 2 mệnh đề, mỗi số lấy cue riêng."""
    c = [r for r in new40 if r["fnum03_group"].startswith("C ")]
    multi = [r for r in c if len(r["messages"][0]["labeled_slots"]) == 2]
    assert multi, "thiếu ca hai PII hai mệnh đề"
    kinds = {s["slot_type"] for s in multi[0]["messages"][0]["labeled_slots"]}
    assert kinds == {"national_id", "bank_account"}


def test_clause_co_ca_cue_canh_tranh_chan_va_ca_khong_chan(new40):
    c = [r for r in new40 if r["fnum03_group"].startswith("C ")]
    assert any(not r["messages"][0]["labeled_slots"] for r in c), \
        "thiếu ca cue cạnh tranh cùng mệnh đề chặn -> no-slot"
    assert any(r["messages"][0]["labeled_slots"] for r in c), \
        "thiếu ca cue cạnh tranh ở mệnh đề khác KHÔNG chặn"


def test_reference_exclusion_TAT_CA_deu_no_slot(new40):
    d = [r for r in new40 if r["fnum03_group"].startswith("D ")]
    assert len(d) == 8
    for rec in d:
        assert rec["messages"][0]["labeled_slots"] == [], \
            f"{rec['conversation_key']}: reference exclusion phải là no-slot"


def test_reference_exclusion_dung_so_12_chu_so(new40):
    """Phải dùng 12 chữ số mới chứng minh được là KHÔNG rơi vào fallback national_id."""
    import re
    for rec in new40:
        if rec["fnum03_group"].startswith("D "):
            digits = re.findall(r"\d+", rec["messages"][0]["canonical_text"])
            assert any(len(x) == 12 for x in digits), rec["conversation_key"]


def test_reference_exclusion_phu_du_4_cum_moi(new40):
    text = " ".join(r["messages"][0]["canonical_text"].lower()
                    for r in new40 if r["fnum03_group"].startswith("D "))
    from app.services.pii.normalize import fold, nfc
    folded = fold(nfc(text))
    for cue in ("ma tham chieu", "ma van don", "ma tra cuu", "ma hoa don"):
        assert cue in folded, f"nhóm D thiếu cụm {cue!r}"


def test_bank_override_tat_ca_deu_bank(new40):
    e = [r for r in new40 if r["fnum03_group"].startswith("E ")]
    assert len(e) == 8
    for rec in e:
        kinds = {s["slot_type"] for s in rec["messages"][0]["labeled_slots"]}
        assert kinds == {"bank_account"}, f"{rec['conversation_key']}: {kinds}"


def test_bank_override_co_bien_the_thuc_te(new40):
    """Directive đòi 'realistic variants': emoji, không dấu câu, có/không dấu."""
    e = {r["conversation_key"]: r["messages"][0]["canonical_text"]
         for r in new40 if r["fnum03_group"].startswith("E ")}
    joined = " ".join(e.values())
    assert any(ord(ch) > 0xFFFF for ch in joined), "thiếu ca có emoji ngoài BMP"
    assert any("ố" in t or "à" in t or "é" in t for t in e.values()), "thiếu biến thể CÓ DẤU"
    assert any(t == t.encode("ascii", "ignore").decode() for t in e.values()), \
        "thiếu biến thể KHÔNG DẤU"


# --------------------------------------------------------------------------------------------
# (6) Inventory / coverage khớp v5
# --------------------------------------------------------------------------------------------

def test_inventory_liet_ke_moi_conversation(v5):
    inv = open(INVENTORY, encoding="utf-8").read()
    for rec in v5:
        assert rec["conversation_key"] in inv, rec["conversation_key"]


def test_coverage_liet_ke_dung_40_ca(new40):
    cov = open(COVERAGE, encoding="utf-8").read()
    for rec in new40:
        assert rec["conversation_key"] in cov, rec["conversation_key"]
    for rec in [r for r in v5_all() if r.get("source") == "v4_retained"][:5]:
        assert rec["conversation_key"] not in cov.split("## Tổng hợp")[0], \
            "coverage matrix chỉ được liệt kê ca F-NUM-03"


def v5_all():
    with open(V5, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def test_inventory_co_no_slot_kem_ly_do(v5):
    inv = open(INVENTORY, encoding="utf-8").read()
    assert "**no-slot**" in inv, "inventory phải đánh dấu no-slot cho staff 5 soi"
    for rec in v5:
        if not rec["messages"][0].get("labeled_slots"):
            assert rec.get("note"), f"{rec['conversation_key']}: no-slot phải có lý do"


# --------------------------------------------------------------------------------------------
# (7) Generator deterministic — không ghi đè file thật
# --------------------------------------------------------------------------------------------

def test_generator_deterministic_va_khop_file_da_commit():
    """Gọi `build()` hai lần, so sánh serialize; rồi so với chính file v5 đã commit.

    Không ghi file nào — tránh mọi rủi ro test làm hỏng dataset.
    """
    a, _ = gen.build()
    b, _ = gen.build()
    ser = lambda recs: "\n".join(json.dumps(r, ensure_ascii=False) for r in recs)
    assert ser(a) == ser(b), "generator KHÔNG deterministic"

    on_disk = open(V5, encoding="utf-8").read()
    assert ser(a) + "\n" == on_disk, "output generator khác file v5 đã commit"


def test_generator_tu_dung_neu_lich_su_bi_sua():
    """`historical_unchanged()` là chốt fail-closed của generator."""
    assert gen.historical_unchanged() == []


def test_generator_validate_khong_bao_loi_tren_v5_hien_tai(v5):
    assert gen.validate(v5) == []
