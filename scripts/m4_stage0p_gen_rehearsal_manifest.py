#!/usr/bin/env python
"""I-B M4 Stage 0P — sinh MANIFEST rehearsal synthetic dataset v2 (deterministic, KHONG dung
database, KHONG ghi ban ghi nao).

Chay:  docker exec alpha3s-api-1 python scripts/m4_stage0p_gen_rehearsal_manifest.py
Output: datasets/pii/m4_stage0p_rehearsal_manifest_v2.jsonl

REV2 (dap lai `PHASE1B-M4-INTERNAL-SYNTHETIC-REHEARSAL-READINESS-REVIEW-1-VI.md`
F-M4-RH-R1-05): CA khuyen nghi mo rong len >=200 gate-eligible conversation (khuyen nghi 220) de
chay FULL Stage 0P lifecycle (qua write_predictions/complete_evaluation), khong chi
capture/seal — tranh dung ca ngay logic "tier bypass" cho ngu`ong exclusion gate 10%/200 dang
ap dung CUNG cho moi batch. Manifest nay nhan du 220 conversation gate-eligible + 5
known-limitation (gate=false, khong tinh gate).

REV2 cung sua giong voi F-M4-RH-R1-03 (Thieu labeling workflow): v1 chi co truong dem `expect`
(so luong theo slot). Stage 0P dung EXACT-SPAN matching (khac S0 count-only) — moi message gio
co them `labeled_slots`: list span {slot_type, start, end, confidence, reason} voi OFFSET THAT
tren canonical_text (tinh qua `app.services.pii.canonicalize.canonicalize` — HAM SAN CO cua
production, dam bao offset khop chinh xac cach server tinh canonical_text_len). offset duoc TU
DONG suy ra qua `str.find()` tren canonical_text (khong go tay, tranh sai so dem tay) — script
raise ngay neu 1 substring khong tim thay hoac xuat hien >1 lan (mo ho).

Provenance (giu nguyen tu v1, xem git history):
- 100% tong hop tay tu template + gia tri BIA (so dien thoai, ten, dia chi, CCCD, STK deu la
  chuoi tu che) - khong lay tu conversation/customer that, khong production data.
- Khong dung random/timestamp dong - manifest co dinh, tai sinh identical moi lan chay.
- Namespace psid `m4synthrehearsalv1_NNNNNN` GIU NGUYEN (khong doi sang v2 - namespace la ve
  NHAN DIEN DU LIEU purge, khong phai ve manifest schema version).
- reason/confidence gan cho moi span duoc chon can cu TRUC TIEP vao logic that trong
  `app/services/pii/detector.py` (da doc nguyen file luc viet script nay) - vd cue "tên mình là"
  khop 1 phan tu trong `_NAME_CUES` KHONG nam trong `_WEAK_CUES` => `has_surname and strong_cue`
  => HIGH/NAME_CUE_SURNAME khi ten bat dau bang ho VN pho bien trong `_SURNAMES`. Day la ground
  truth TAC GIA (Dev) DOC LAP voi bat ky lan chay detect() nao — khong goi detect() de sinh
  labeled_slots (se lam ket qua evaluation tro thanh "detector tu cham diem chinh no").
"""

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.pii.canonicalize import canonicalize  # noqa: E402

OUT = ROOT / "datasets" / "pii" / "m4_stage0p_rehearsal_manifest_v2.jsonl"

MANIFEST_VERSION = "m4-stage0p-rehearsal-manifest-v2"
PSID_PREFIX = "m4synthrehearsalv1_"


def _span(canonical_text: str, substr: str, slot_type: str, confidence: str, reason: str) -> dict:
    start = canonical_text.find(substr)
    if start == -1:
        raise ValueError(f"substring khong tim thay: {substr!r} trong {canonical_text!r}")
    if canonical_text.find(substr, start + 1) != -1:
        raise ValueError(f"substring MO HO (xuat hien >1 lan): {substr!r} trong {canonical_text!r}")
    return {"slot_type": slot_type, "start": start, "end": start + len(substr),
            "confidence": confidence, "reason": reason}


def _msg(raw_text: str, spans_fn=None) -> dict:
    """spans_fn: callable(canonical_text) -> list[span dict], hoac None (khong PII)."""
    canonical_text, truncated = canonicalize(raw_text)
    assert not truncated, f"message qua dai, khong ky vong truncate trong rehearsal: {raw_text!r}"
    spans = spans_fn(canonical_text) if spans_fn else []
    return {"role": "customer", "content": raw_text, "canonical_text": canonical_text,
            "labeled_slots": spans}


def conv(key, messages, *, gate=True, note=""):
    return {"conversation_key": key, "messages": messages, "expect_gate": gate, "note": note}


CONVERSATIONS: list[dict] = []

# ---------------------------------------------------------------------------
# A. PHONE (60) — so dien thoai bia, nhieu template cau + nhieu format.
# ---------------------------------------------------------------------------
_MOBILE_PREFIXES = ["03", "05", "07", "08", "09"]
_MOBILE_NUMS = [f"{p}{i:08d}" for p in _MOBILE_PREFIXES for i in range(1234567, 1234567 + 6)]
# 5 prefixes x 6 = 30 so mobile plain.
_PHONE_TEMPLATES_PLAIN = [
    "sđt của mình là {n} nhé shop",
    "lien he {n} gap nha",
    "alo gọi giúp em số {n} trước khi giao",
    "shop ơi gọi số {n} giúp mình",
    "zalo mình {n} add giúp",
]
for i, num in enumerate(_MOBILE_NUMS):
    tmpl = _PHONE_TEMPLATES_PLAIN[i % len(_PHONE_TEMPLATES_PLAIN)]
    text = tmpl.format(n=num)
    CONVERSATIONS.append(conv(
        f"RA{i + 1:03d}",
        [_msg(text, lambda ct, n=num: [_span(ct, n, "phone", "high", "phone_valid_vn_mobile")])],
        note="phone mobile plain"))

_LANDLINE_NUMS = [f"028{i:07d}" for i in range(3812345, 3812345 + 10)]
for i, num in enumerate(_LANDLINE_NUMS):
    text = f"số cố định {num} gọi giờ hành chính giúp em"
    CONVERSATIONS.append(conv(
        f"RA{31 + i:03d}",
        [_msg(text, lambda ct, n=num: [_span(ct, n, "phone", "medium", "phone_valid_vn_landline")])],
        note="phone landline"))

_FORMAT_VARIANTS = [
    ("0912 345 {s}", "spaced"), ("0912.345.{s}", "dot"), ("0912-345-{s}", "dash"),
    ("+84912345{s}", "+84"), ("+84 912 345 {s}", "+84 space"),
    ("84912345{s}", "84"), ("(+84)912345{s}", "ngoac"), ("09 1234 5{s}", "nhom la"),
    ("0912345{s}", "lien2"), ("0912 345{s}", "spaced2"),
]
for i, (fmt, label) in enumerate(_FORMAT_VARIANTS):
    suffix = f"{670 + i:03d}"
    formatted = fmt.format(s=suffix)
    text = f"đổi số mới {formatted} nhé shop, số cũ mất sim"
    CONVERSATIONS.append(conv(
        f"RA{41 + i:03d}",
        [_msg(text, lambda ct, n=formatted: [_span(ct, n, "phone", "high", "phone_valid_vn_mobile")])],
        note=f"phone format {label}"))

_MORE_TEMPLATES = [
    "so dien thoai cua minh: {n}",
    "shop gọi lại giúp em số {n} nhé",
    "để lại số {n} liên hệ khi giao hàng",
    "cần đặt hàng, số của em là {n}",
    "gọi trước khi ship về số {n} giúp shop",
    "em đổi sim rồi, số mới {n}",
    "liên hệ giúp em qua số {n} buổi tối",
    "shop lưu giúp số {n} để giao lần sau",
    "gọi giúp em trước 10 phút, số {n}",
    "số nhà mạng viettel của mình {n}",
]
for i, tmpl in enumerate(_MORE_TEMPLATES):
    num = f"09{87654321 + i:08d}"
    text = tmpl.format(n=num)
    CONVERSATIONS.append(conv(
        f"RA{51 + i:03d}",
        [_msg(text, lambda ct, n=num: [_span(ct, n, "phone", "high", "phone_valid_vn_mobile")])],
        note="phone extra template"))

assert len(CONVERSATIONS) == 60, len(CONVERSATIONS)

# ---------------------------------------------------------------------------
# B. NAME (50) — ten bia, 5 template cue-manh x 10 ten (ho VN pho bien).
# ---------------------------------------------------------------------------
_NAMES = [
    "Nguyễn Văn An", "Trần Thị Bích", "Lê Hoàng Nam", "Phạm Thu Hà",
    "Hoàng Minh Tuấn", "Huỳnh Gia Bảo", "Phan Thị Mai", "Vũ Đức Anh",
    "Võ Thành Long", "Đặng Quỳnh Anh",
]
_NAME_TEMPLATES = [
    "tên mình là {n}",
    "em là {n} ạ",
    "người nhận là {n}",
    "tên người nhận là {n}",
    "người đặt là {n}",
]
idx = 0
for t_i, tmpl in enumerate(_NAME_TEMPLATES):
    for n_i, name in enumerate(_NAMES):
        idx += 1
        text = tmpl.format(n=name)
        CONVERSATIONS.append(conv(
            f"RB{idx:03d}",
            [_msg(text, lambda ct, nm=name: [_span(ct, nm, "name", "high", "name_cue_surname")])],
            note=f"name template {t_i}"))
assert idx == 50, idx

# ---------------------------------------------------------------------------
# C. ADDRESS (40) — dia chi bia day du (house+street+admin), 2 template x 20 dia chi.
# ---------------------------------------------------------------------------
_ADDRESSES = [
    "số 12 đường Lê Lợi, phường 5, quận 3, TPHCM",
    "78/9 đường Quang Trung, phường 10, quận Gò Vấp",
    "45 đường Nguyễn Trãi, phường 7, quận Thanh Xuân, Hà Nội",
    "số 9, thôn Đoài, xã Phú Minh, huyện Sóc Sơn",
    "56B đường Trần Phú, phường Lộc Thọ, Nha Trang",
    "123 đường Điện Biên Phủ, phường 15, quận Bình Thạnh",
    "34 ngõ 78 phố Huế, phường Ngô Thì Nhậm, Hai Bà Trưng",
    "số 5 đường Hoàng Diệu, phường Quán Thánh, Ba Đình",
    "67 đường Cách Mạng Tháng 8, phường 6, quận 3",
    "88 đường Lý Thường Kiệt, phường 7, quận 11",
    "21 đường Phan Đăng Lưu, phường 3, quận Phú Nhuận",
    "9 đường Nguyễn Huệ, phường Bến Nghé, quận 1",
    "156 đường Hai Bà Trưng, phường Đa Kao, quận 1",
    "43 đường Trường Chinh, phường Khương Mai, Thanh Xuân",
    "12 đường Bạch Đằng, phường 2, quận Tân Bình",
    "76 đường Lạc Long Quân, phường 5, quận 11",
    "29 đường Kim Mã, phường Kim Mã, Ba Đình",
    "58 đường Nguyễn Thị Minh Khai, phường 6, quận 3",
    "14 đường Hùng Vương, phường 9, quận 5",
    "37 đường Trần Hưng Đạo, phường Cầu Kho, quận 1",
]
_ADDR_TEMPLATES = [
    "giao về {a} nhé shop",
    "địa chỉ giao hàng: {a}",
]
idx = 0
for t_i, tmpl in enumerate(_ADDR_TEMPLATES):
    for a_i, addr in enumerate(_ADDRESSES):
        idx += 1
        text = tmpl.format(a=addr)
        CONVERSATIONS.append(conv(
            f"RC{idx:03d}",
            [_msg(text, lambda ct, ad=addr: [_span(ct, ad, "address", "high", "addr_multi_component")])],
            note=f"address template {t_i}"))
assert idx == 40, idx

# ---------------------------------------------------------------------------
# D. COMBO (20) — 1 message/conversation (name+phone+address CUNG 1 tin) — CO Y GIU 1
#    message/conversation xuyen suot toan bo manifest (xem ghi chu quan trong duoi day).
# ---------------------------------------------------------------------------
# QUAN TRONG: m4_stage0p_seed_capture_progress() seed TOI DA 20 message role='customer' MOI
# conversation (khong chi 1) — neu 1 conversation co >1 message 'customer', se co >1 sample
# duoc capture cho CUNG batch_id/conversation_ref, nhung m4_shadow_review_samples KHONG co cot
# message_id de phan biet sample nao khop message nao (chi co customer_ref/conversation_ref).
# De labeling workflow (F-M4-RH-R1-03) anh xa DUNG 1-1 sample<->ground-truth ma khong can doan
# qua thu tu captured_at/canonical_text_len, MOI conversation trong manifest nay CHI co DUNG 1
# message — dam bao 1 conversation = 1 sample, anh xa tuong minh.
_COMBO_NAMES = _NAMES
_COMBO_PHONES = [f"09{11223344 + i:08d}" for i in range(20)]
_COMBO_ADDRS = _ADDRESSES[:10] + _ADDRESSES[10:20]
for i in range(20):
    name = _COMBO_NAMES[i % len(_COMBO_NAMES)]
    phone = _COMBO_PHONES[i]
    addr = _COMBO_ADDRS[i]
    text = f"Đặt giúp em 2 gói 500g. Người nhận {name}, {phone}, {addr}"

    def _combo_spans(ct, nm=name, ph=phone, ad=addr):
        return [
            _span(ct, nm, "name", "high", "name_cue_surname"),
            _span(ct, ph, "phone", "high", "phone_valid_vn_mobile"),
            _span(ct, ad, "address", "high", "addr_multi_component"),
        ]
    CONVERSATIONS.append(conv(f"RD{i + 1:03d}", [_msg(text, _combo_spans)], note="combo 1-message"))

assert sum(1 for c in CONVERSATIONS if c["conversation_key"].startswith("RD")) == 20

# ---------------------------------------------------------------------------
# E. SENSITIVE (20) — 10 health (khong PII slot), 5 national_id, 5 bank_account.
# ---------------------------------------------------------------------------
_HEALTH_TEXTS = [
    "mình bị tiểu đường uống cà phê này được không shop",
    "em đang mang thai có uống được không",
    "mẹ mình huyết áp cao, cà phê decaf có không?",
    "tôi bị mất ngủ nặng, đang uống thuốc bác sĩ dặn",
    "bé nhà em còn cho con bú thì mẹ uống được không",
    "mình dị ứng caffeine nhẹ có sao không",
    "ông ngoại bị bệnh tim, uống loại nhẹ nhất được không",
    "mình hay bị trào ngược dạ dày có uống được không",
    "em đang điều trị trầm cảm có nên uống cà phê không",
    "mình bị rối loạn lo âu, cà phê có ảnh hưởng không",
]
for i, text in enumerate(_HEALTH_TEXTS):
    CONVERSATIONS.append(conv(f"RE{i + 1:03d}", [_msg(text)], note="sensitive health, no PII slot"))

_NID_NUMS = [f"{79000012345 + i:012d}" for i in range(5)]
for i, num in enumerate(_NID_NUMS):
    text = f"CCCD của tôi là {num} đây nhé"
    CONVERSATIONS.append(conv(
        f"RE{11 + i:03d}",
        [_msg(text, lambda ct, n=num: [_span(ct, n, "national_id", "high", "nid_cue_digits")])],
        note="sensitive identity CCCD"))

_BANK_NUMS = [f"{71000123456 + i:011d}" for i in range(5)]
for i, num in enumerate(_BANK_NUMS):
    text = f"chuyển khoản tới STK {num} đúng không shop"
    CONVERSATIONS.append(conv(
        f"RE{16 + i:03d}",
        [_msg(text, lambda ct, n=num: [_span(ct, n, "bank_account", "high", "bank_cue_digits")])],
        note="sensitive finance STK"))

assert sum(1 for c in CONVERSATIONS if c["conversation_key"].startswith("RE")) == 20

# ---------------------------------------------------------------------------
# F. NEGATIVE (25) — D0, khong PII, bay dong am tieng Viet (CLAUDE.md §6).
# ---------------------------------------------------------------------------
_NEGATIVE_TEXTS = [
    "cho mình 2 gói 500g nhé",
    "đơn A123 tới đâu rồi shop",
    "ship Cà Mau được không?",
    "ship ca mau duoc khong",
    "cà phê này chua quá, đổi vị khác được không",
    "chưa nhận được hàng nha shop",
    "máy pha bị hỏng rồi, không lên nước",
    "giá 120000 đồng một gói phải không",
    "tổng đơn 1.250.000đ đúng chưa",
    "giao 10 giờ 30 sáng mai nhé",
    "tp hồ chí minh còn ship trong ngày không",
    "đà nẵng đường xa vậy phí ship nhiêu",
    "quán gần phố đi bộ không shop",
    "cho 1 ly cà phê sữa với 2 ly đen đá",
    "hạn dùng tới năm 2027 hả",
    "mã giảm giá SALE50 còn không",
    "gói 250g với gói 1kg lệch nhau nhiêu tiền",
    "order hom qua chua thay xac nhan",
    "cà phê phin với cà phê pha máy khác gì nhau",
    "shop mở cửa tới mấy giờ",
    "cho em hỏi cách pha cold brew tại nhà",
    "đóng gói có chống ẩm không shop",
    "còn khuyến mãi mua 2 tặng 1 không",
    "vận chuyển mất mấy ngày vậy shop",
    "đổi trả trong bao lâu nếu lỗi",
    "cà phê rang mộc với rang xay khác nhau sao shop",
    "mình ở xa có ship được không",
    "cho hỏi cách bảo quản sau khi mở gói",
    "đơn hàng có xuất hoá đơn không shop",
    "mua sỉ có giảm giá thêm không",
]
assert len(_NEGATIVE_TEXTS) == 30
for i, text in enumerate(_NEGATIVE_TEXTS):
    CONVERSATIONS.append(conv(f"RF{i + 1:03d}", [_msg(text)], note="negative, no PII"))

assert sum(1 for c in CONVERSATIONS if c["expect_gate"]) == 220, \
    sum(1 for c in CONVERSATIONS if c["expect_gate"])

# ---------------------------------------------------------------------------
# G. KNOWN LIMITATION (5, gate=false) — ky vong detector MISS, KHONG tinh gate.
#    labeled_slots VAN dung (ground truth that), chi khong tinh vao bao cao gate.
# ---------------------------------------------------------------------------
_num_spelled = "0912345678"
CONVERSATIONS.append(conv(
    "RG001",
    [_msg("số mình là không chín một hai ba bốn năm sáu bảy tám nhé",
          lambda ct: [])],  # so doc bang chu -> khong co digit-run nao de tro offset toi
    gate=False, note="phone doc bang chu — khong co digit substring de gan span, ground truth rong co y"))

_addr_loi_noi = "nha o cho lon do, hem thu hai ben trai qua cay xang"
CONVERSATIONS.append(conv(
    "RG002", [_msg(_addr_loi_noi, lambda ct: [])],
    gate=False, note="dia chi mo ta loi noi, khong thanh phan chuan — ground truth rong co y"))

_g3_num = "0912🌟345🌟678"
CONVERSATIONS.append(conv(
    "RG003",
    [_msg(f"{_g3_num} nha shop", lambda ct: [_span(ct, _g3_num, "phone", "low", "phone_digitrun_with_cue")])],
    gate=False, note="phone chen emoji — ground truth van danh dau du dia chi that"))

CONVERSATIONS.append(conv(
    "RG004", [_msg("tui ten Ut Nho o duoi que", lambda ct: [])],
    gate=False, note="ten goi mien Tay khong ho, cue yeu — ground truth rong co y"))

_g5_num = "678, đầu 0912 với 345"
CONVERSATIONS.append(conv(
    "RG005", [_msg("số đuôi 678 đó, đầu 0912 với 345 ở giữa", lambda ct: [])],
    gate=False, note="phone tach roi nhieu cum cach xa — ground truth rong co y"))

assert sum(1 for c in CONVERSATIONS if not c["expect_gate"]) == 5

# ---------------------------------------------------------------------------
TOTAL = len(CONVERSATIONS)
assert TOTAL == 225, TOTAL


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    keys = [c["conversation_key"] for c in CONVERSATIONS]
    assert len(keys) == len(set(keys)), "trung conversation_key trong manifest"

    records = []
    seq = 0
    for c in CONVERSATIONS:
        seq += 1
        psid = f"{PSID_PREFIX}{seq:06d}"
        records.append({
            "manifest_version": MANIFEST_VERSION,
            "psid": psid,
            "conversation_key": c["conversation_key"],
            "messages": c["messages"],
            "expect_gate": c["expect_gate"],
            "note": c["note"],
        })

    with OUT.open("w", encoding="utf-8", newline="\n") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    gate_n = sum(1 for r in records if r["expect_gate"])
    msg_n = sum(len(r["messages"]) for r in records)
    span_n = sum(len(m["labeled_slots"]) for r in records for m in r["messages"])
    digest = hashlib.sha256(OUT.read_bytes()).hexdigest()
    print(f"wrote {len(records)} conversations / {msg_n} messages / {span_n} labeled spans "
          f"({gate_n} gate, {len(records) - gate_n} known-limit) -> {OUT}")
    print(f"sha256 {digest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
