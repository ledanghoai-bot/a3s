"""I-B M4 — kiểm manifest v4 (đáp `PHASE1B-M4-MANIFEST-V4-PREPARATION-DIRECTIVE-VI.md`).

v4 là đường một-batch tương thích **Cap A = 260**, sinh bằng cách CHỌN LỌC xác định từ v3 chứ không
viết nhãn mới — nên nhóm test quan trọng nhất ở đây là §"không bịa ground truth": mọi record của v4
phải trùng khít record tương ứng trong v3, chỉ khác `manifest_version`.

Không cần DB/Redis.
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

CAP_A = 260
MIN_POSITIVE_PER_TYPE = 30
MIN_NEGATIVE = 30
PII_TYPES = ("phone", "name", "address", "national_id", "bank_account")

V2_SHA = "5f0f92dbd311d0a4c7d309c01c86b958c81f32126ee531694f4b43a23c54bce5"
V3_SHA = "2bebfd62bd21e7cea8a55bccabd3089c357e7649aa10744b06b8c4fef8d802c4"
V4_SHA = "ef6f76c6c8eed4bc8b9abb921d420cdc1bcb3b22801473dd39dfcb65de3c7f17"

_spec = importlib.util.spec_from_file_location(
    "m4_runner_for_v4_test", os.path.join(ROOT, "scripts", "m4_stage0p_rehearsal_runner.py"))
runner = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(runner)


def _load(path):
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


@pytest.fixture(scope="module")
def v4():
    return _load(V4)


@pytest.fixture(scope="module")
def v3():
    return _load(V3)


# --------------------------------------------------------------------------------------------
# Cap A
# --------------------------------------------------------------------------------------------

def test_khong_vuot_cap_a(v4):
    assert len(v4) <= CAP_A
    assert len(v4) == CAP_A, "v4 duoc thiet ke dung 260 - lech nghia la generator da doi"


def test_guard_cua_runner_chap_nhan_v4(v4):
    """Chính hàm mà dry-run và execute dùng — không phải một bản kiểm viết lại."""
    assert runner._cap_a_problem(v4) is None


def test_guard_cua_runner_VAN_tu_choi_v3(v3):
    """Đối chứng âm: cùng hàm đó phải vẫn chặn v3 (315)."""
    problem = runner._cap_a_problem(v3)
    assert problem is not None and "315" in problem


# --------------------------------------------------------------------------------------------
# Không bịa ground truth — v4 phải là tập con NGUYÊN VẸN của v3
# --------------------------------------------------------------------------------------------

def test_moi_record_v4_trung_khit_record_v3(v4, v3):
    """Điểm mấu chốt. Nếu test này đỏ nghĩa là có nhãn/span/text bị đổi trong lúc sinh v4 —
    tức Dev đã tạo ground truth mới mà chưa ai review.

    Đối chiếu theo `psid` chứ **không** theo `conversation_key`: `psid` là định danh duy nhất
    thật sự (v3 có 315 psid phân biệt nhưng chỉ 277 conversation_key phân biệt — chính là
    F-V4-01). `conversation_key` được phép khác vì v4 đổi key cho các record trùng.
    """
    by_psid = {r["psid"]: r for r in v3}
    for rec in v4:
        psid = rec["psid"]
        assert psid in by_psid, f"{psid} khong co trong v3 - v4 KHONG duoc them mau moi"
        a, b = dict(rec), dict(by_psid[psid])
        for field in ("manifest_version", "conversation_key"):
            a.pop(field)
            b.pop(field)
        assert a == b, f"{psid}: noi dung/nhan khac v3"


def test_key_chi_duoc_doi_PREFIX_va_khong_doi_gi_khac(v4, v3):
    """F-V4-01: việc đổi key phải là đổi tên thuần tuý — cùng phần số, chỉ khác 2 ký tự đầu."""
    by_psid = {r["psid"]: r for r in v3}
    remapped = 0
    for rec in v4:
        old = by_psid[rec["psid"]]["conversation_key"]
        new = rec["conversation_key"]
        if new == old:
            continue
        remapped += 1
        assert new[2:] == old[2:], f"{rec['psid']}: doi ca phan so {old} -> {new}"
        assert (old[:2], new[:2]) in (("RB", "BA"), ("RC", "CX")), f"remap la {old} -> {new}"
    assert remapped == 36, f"ky vong doi dung 36 key, thuc te {remapped}"


def test_conversation_key_duy_nhat_trong_v4(v4):
    """Nếu đỏ, `_seed_synthetic` sẽ ghi đè map và rehearsal abort nhầm ở bước labeling."""
    keys = [r["conversation_key"] for r in v4]
    assert len(keys) == len(set(keys))


def test_v3_VAN_con_trung_key_dung_38(v3):
    """Chốt lại hiện trạng v3 để CA đối chiếu — v3 là bằng chứng lịch sử, KHÔNG được sửa."""
    keys = [r["conversation_key"] for r in v3]
    assert len(keys) - len(set(keys)) == 38


def test_manifest_version_da_doi(v4):
    assert {r["manifest_version"] for r in v4} == {"m4-stage0p-rehearsal-v4"}


def test_psid_khong_trung_lap(v4):
    psids = [r["psid"] for r in v4]
    assert len(psids) == len(set(psids))


# --------------------------------------------------------------------------------------------
# Acceptance criteria theo directive
# --------------------------------------------------------------------------------------------

def _counts(recs):
    per, neg = collections.Counter(), 0
    for rec in recs:
        found = False
        for msg in rec["messages"]:
            for s in msg.get("labeled_slots", []):
                per[s["slot_type"]] += 1
                found = True
        if not found:
            neg += 1
    return per, neg


@pytest.mark.parametrize("slot_type", PII_TYPES)
def test_du_30_positive_moi_loai(v4, slot_type):
    per, _ = _counts(v4)
    assert per[slot_type] >= MIN_POSITIVE_PER_TYPE, f"{slot_type} chi co {per[slot_type]}"


def test_du_30_negative(v4):
    _, neg = _counts(v4)
    assert neg >= MIN_NEGATIVE


def test_du_gate_eligible_cho_dry_run(v4):
    """Runner từ chối dry-run nếu gate-eligible < 200 — sàn này độc lập với Cap A."""
    assert sum(1 for r in v4 if r.get("expect_gate")) >= 200


# --------------------------------------------------------------------------------------------
# Schema / offset
# --------------------------------------------------------------------------------------------

def test_offset_tro_dung_vao_canonical_text(v4):
    for rec in v4:
        for msg in rec["messages"]:
            text = msg["canonical_text"]
            assert text == msg["content"]
            for s in msg.get("labeled_slots", []):
                assert 0 <= s["start"] < s["end"] <= len(text), \
                    f"{rec['conversation_key']}: offset {s['start']}-{s['end']} ngoai bien"


def test_moi_conversation_dung_1_message(v4):
    """Bất biến runner tự assert khi load — kiểm trước ở đây để không vỡ giữa lifecycle."""
    for rec in v4:
        assert len(rec["messages"]) == 1, rec["conversation_key"]


def test_file_chi_dung_LF():
    raw = open(V4, "rb").read()
    assert raw.count(b"\r") == 0
    assert raw.count(b"\n") == CAP_A


# --------------------------------------------------------------------------------------------
# Bất biến lịch sử
# --------------------------------------------------------------------------------------------

@pytest.mark.parametrize("path,expected", [(V2, V2_SHA), (V3, V3_SHA), (V4, V4_SHA)])
def test_hash_manifest(path, expected):
    got = hashlib.sha256(open(path, "rb").read()).hexdigest()
    assert got == expected, f"{os.path.basename(path)} doi hash: {got}"


# --------------------------------------------------------------------------------------------
# F-V4-01 — guard mới trong `_load_manifest`
# --------------------------------------------------------------------------------------------

def _write(tmp_path, records):
    p = tmp_path / "m.jsonl"
    with open(p, "w", encoding="utf-8", newline="\n") as fh:
        for r in records:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    return p


def test_load_manifest_tu_choi_conversation_key_trung(tmp_path, v4):
    """Chốt mới: trước đây `_load_manifest` chỉ chặn trùng `psid`, không chặn trùng key — nên
    manifest hỏng đi lọt tới tận bước labeling rồi mới abort với thông báo sai hướng."""
    a, b = json.loads(json.dumps(v4[0])), json.loads(json.dumps(v4[1]))
    b["conversation_key"] = a["conversation_key"]          # trùng key, psid vẫn khác nhau
    with pytest.raises(SystemExit) as exc:
        runner._load_manifest(_write(tmp_path, [a, b]))
    msg = str(exc.value)
    assert "conversation_key trung lap" in msg
    assert "F-V4-01" in msg


def test_load_manifest_chap_nhan_v4_that(v4):
    """Đối chứng dương: chính file v4 đã sinh phải qua được guard."""
    loaded = runner._load_manifest(__import__("pathlib").Path(V4))
    assert len(loaded) == CAP_A


def test_load_manifest_VAN_tu_choi_psid_trung(tmp_path, v4):
    """Guard cũ không được hỏng khi thêm guard mới."""
    a, b = json.loads(json.dumps(v4[0])), json.loads(json.dumps(v4[1]))
    b["psid"] = a["psid"]
    with pytest.raises(SystemExit) as exc:
        runner._load_manifest(_write(tmp_path, [a, b]))
    assert "psid trung lap" in str(exc.value)
