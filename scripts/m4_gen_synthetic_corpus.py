#!/usr/bin/env python
"""I-B M4-S0 — sinh synthetic PII corpus v1 (deterministic, KHONG du lieu that).

Chay:  docker exec alpha3s-m4-test python scripts/m4_gen_synthetic_corpus.py
Output: datasets/pii/synthetic_corpus_v1.jsonl (ghi de — corpus la ham thuan cua
        script nay; provenance = chinh file nay + git history).

Provenance (Directive §9 "corpus datasheet va generation provenance"):
- 100% tong hop tay boi Dev trong M4-S0 tu template + gia tri BIA (so dien thoai,
  ten, dia chi, CCCD, STK deu la chuoi tu che — khong lay tu conversation that,
  khong production data, khong PII cua nguoi that).
- Khong dung random: corpus co dinh, tai sinh identical moi lan chay.
- Truong `gate`: true = tinh vao recall/precision gate; false = known-limitation
  case (ky vong detector MISS — bao cao rieng trong failure taxonomy, KHONG tinh
  vao gate de khong lam dep so lieu bang cach loai case kho mot cach ngam dinh).
- expect: so INSTANCE ky vong theo slot (dem, khong cham offset — eval instance-level).
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "datasets" / "pii" / "synthetic_corpus_v1.jsonl"

E0 = {"phone": 0, "name": 0, "address": 0, "national_id": 0, "bank_account": 0}


def case(cid, text, risk="D0", gate=True, variant="dau", note="", **expect):
    e = dict(E0)
    e.update(expect)
    return {"id": cid, "text": text, "expect": e, "risk": risk,
            "gate": gate, "variant": variant, "note": note}


CASES: list[dict] = []

# ---------------------------------------------------------------------------
# A. PHONE — so bia 09x/03x/07x + landline 028; moi format nhung vao cau thuc te
# ---------------------------------------------------------------------------
_PHONE_FORMATS = [
    ("A01", "0912345678", "lien"),
    ("A02", "0912 345 678", "space"),
    ("A03", "0912.345.678", "dot"),
    ("A04", "0912-345-678", "dash"),
    ("A05", "+84912345678", "+84"),
    ("A06", "+84 912 345 678", "+84 space"),
    ("A07", "84912345678", "84"),
    ("A08", "(+84)912345678", "ngoac"),
    ("A09", "09 1234 5678", "nhom la"),
    ("A10", "0356789012", "dau 03"),
    ("A11", "0789012345", "dau 07"),
    ("A12", "0898765432", "dau 08"),
]
for cid, num, note in _PHONE_FORMATS:
    CASES.append(case(cid, f"sđt của mình là {num} nhé shop", risk="D1",
                      note=f"phone format {note}", phone=1))
_PHONE_SENTENCES = [
    ("A13", "alo gọi giúp em số 0912345678 trước khi giao", "dau"),
    ("A14", "lien he 0987654321 gap nha", "khong_dau"),
    ("A15", "0912345678", "digits"),  # tin nhan CHI co so
    ("A16", "so dien thoai cua minh: 0345678901", "khong_dau"),
    ("A17", "shop ơi gọi số 0778 123 456 giúp mình", "dau"),
    ("A18", "zalo mình 0912345678 add giúp", "dau"),
    ("A19", "số cố định 02838123456 gọi giờ hành chính", "dau"),
    ("A20", "đổi số mới +84 356 789 012 nhé, số cũ mất sim", "dau"),
]
for cid, text, variant in _PHONE_SENTENCES:
    CASES.append(case(cid, text, risk="D1", variant=variant, phone=1))
CASES.append(case("A21", "hai số nhé: 0912345678 với 0356789012, số nào cũng được",
                  risk="D1", note="2 phone trong 1 tin", phone=2))

# ---------------------------------------------------------------------------
# B. NAME — ten bia; cue + khong cue, co dau + khong dau, nhieu nguoi
# ---------------------------------------------------------------------------
_NAMES = [
    ("B01", "tên mình là Nguyễn Văn An", 1, "dau", "cue+ho, viet hoa"),
    ("B02", "ten minh la nguyen thi thu ha", 1, "khong_dau", "cue+ho, thuong khong dau"),
    ("B03", "em là Trần Bình", 1, "dau", "cue em la"),
    ("B04", "toi la pham hong phuc", 1, "khong_dau", "cue toi la + ho"),
    ("B05", "người nhận là Lê Thị Mai", 1, "dau", "cue nguoi nhan la"),
    ("B06", "giao cho chị Lan nhé shop", 1, "dau", "cue giao cho + viet hoa"),
    ("B07", "tên người nhận Hoàng Minh Tuấn", 1, "dau", "cue ten nguoi nhan"),
    ("B08", "Nguyễn Văn An", 1, "dau", "chi ten, khong cue (ho + viet hoa)"),
    ("B09", "đặt giúp đơn cho Võ Thị Sáu Mươi", 1, "dau", "chuoi ho viet hoa khong cue"),
    ("B10", "giao cho chị Lan, người đặt là Nguyễn Văn An", 2, "dau", "2 nguoi 1 tin"),
    ("B11", "gửi cho anh Phạm Đức", 1, "dau", "cue gui cho"),
    ("B12", "nguoi nhan ten la bui thanh tam", 1, "khong_dau", "cue day du khong dau"),
    ("B13", "mình là Đặng Quỳnh Anh, khách mới ạ", 1, "dau", "cue minh la"),
    ("B14", "tên là Đỗ Hùng", 1, "dau", "cue ten la"),
    ("B15", "ship cho Ngô Gia Bảo giúp em", 1, "dau", "cue ship cho"),
]
for cid, text, n, variant, note in _NAMES:
    CASES.append(case(cid, text, risk="D1", variant=variant, note=note, name=n))

# ---------------------------------------------------------------------------
# C. ADDRESS — dia chi bia (so nha tu che); >=2 thanh phan hoac so nha + duong
# ---------------------------------------------------------------------------
_ADDRESSES = [
    ("C01", "giao về số 12 đường Lê Lợi, phường 5, quận 3, TPHCM nhé", 1, "dau",
     "day du 4 cap"),
    ("C02", "giao ve so 12 duong le loi phuong 5 quan 3 tphcm", 1, "khong_dau",
     "day du khong dau"),
    ("C03", "địa chỉ: 45/6/7 tổ 5 ấp Bình Đông, xã Tân Hòa, huyện Cái Bè, Tiền Giang",
     1, "dau", "nong thon: so xuyet + to/ap/xa/huyen/tinh"),
    ("C04", "123 duong Nguyen Trai", 1, "khong_dau", "so nha + duong don le (MEDIUM)"),
    ("C05", "nhà mình ở ngõ 34 phố Huế, quận Hai Bà Trưng, Hà Nội", 1, "dau",
     "ngo + pho + quan + tinh"),
    ("C06", "ship về chung cư Sky Lake block B, phường Yên Hòa, Cầu Giấy", 1, "dau",
     "chung cu + block + phuong"),
    ("C07", "gui hang ve 78 hem 51 duong 3 thang 2, phuong 12, quan 10", 1,
     "khong_dau", "hem + duong so"),
    ("C08", "số nhà 9, thôn Đoài, xã Phú Minh, huyện Sóc Sơn", 1, "dau",
     "so nha + thon/xa/huyen"),
    ("C09", "văn phòng ở tòa nhà Bitexco, quận 1 nha shop", 1, "dau",
     "toa nha + quan"),
    ("C10", "đổi địa chỉ giao thành 56B đường Trần Phú, Nha Trang", 1, "dau",
     "so + duong + tinh"),
    ("C11", "khu đô thị Ecopark, tòa Rừng Cọ, căn 1203 giao giờ nào cũng được", 1,
     "dau", "khu do thi + toa"),
    ("C12", "lay hang o kdc phu my hung, phuong tan phong, quan 7", 1, "khong_dau",
     "kdc + phuong + quan"),
]
for cid, text, n, variant, note in _ADDRESSES:
    CASES.append(case(cid, text, risk="D1", variant=variant, note=note, address=n))
CASES.append(case("C13",
                  "giao sáng ở số 12 đường Lê Lợi quận 3, chiều chuyển về 45 ngõ 78 phố Huế Hà Nội giúp mình",
                  risk="D1", note="2 dia chi 1 tin (multi-address)", address=2))

# ---------------------------------------------------------------------------
# D. COMBO don hang day du (name + phone + address trong 1 tin)
# ---------------------------------------------------------------------------
_COMBOS = [
    ("D01", "Đặt 2 gói 500g. Người nhận Nguyễn Văn An, 0912345678, số 12 đường Lê Lợi, phường 5, quận 3",
     "dau"),
    ("D02", "dat 1 hop ca phe sua. nguoi nhan la tran thi bich, sdt 0356789012, 78/9 duong quang trung, go vap",
     "khong_dau"),
    ("D03", "Giao cho chị Lê Thu Thảo - 0789 012 345 - ngõ 34 phố Huế, Hai Bà Trưng, Hà Nội", "dau"),
    ("D04", "Nguyễn Văn An, 0912.345.678, 123 đường Nguyễn Trãi, Thanh Xuân", "dau"),
    ("D05", "nguoi dat la vo minh chau, lien he +84 912 345 678, giao ve so nha 9 thon doai xa phu minh",
     "khong_dau"),
]
for cid, text, variant in _COMBOS:
    CASES.append(case(cid, text, risk="D1", variant=variant,
                      note="combo don hang", phone=1, name=1, address=1))

# ---------------------------------------------------------------------------
# E. SENSITIVE / HIGH-RISK (D2) — disclosure suc khoe (domain ca phe gap that),
# giay to, tai chinh. Slot chi khi co day so.
# ---------------------------------------------------------------------------
_SENSITIVE = [
    ("E01", "mình bị tiểu đường uống cà phê này được không shop", {}, "dau",
     "health: tieu duong"),
    ("E02", "em dang mang thai co uong duoc khong", {}, "khong_dau",
     "health: mang thai"),
    ("E03", "mẹ mình huyết áp cao, cà phê decaf có không?", {}, "dau",
     "health: huyet ap"),
    ("E04", "tôi bị mất ngủ nặng, đang uống thuốc bác sĩ dặn", {}, "dau",
     "health: mat ngu + thuoc"),
    ("E05", "bé nhà em còn cho con bú thì mẹ uống được không", {}, "khong_dau",
     "health: cho con bu"),
    ("E06", "mình dị ứng caffeine nhẹ có sao không", {}, "dau", "health: di ung"),
    ("E07", "nhận hàng cần CMND không shop?", {}, "dau",
     "identity: nhac giay to, KHONG so"),
    ("E08", "CCCD của tôi là 079123456789 đây nhé", {"national_id": 1}, "dau",
     "identity: CCCD 12 so"),
    ("E09", "so cmnd 123456789 dung khong", {"national_id": 1}, "khong_dau",
     "identity: CMND 9 so + cue"),
    ("E10", "chuyển khoản tới STK 0071000123456 đúng không shop", {"bank_account": 1},
     "dau", "finance: STK"),
    ("E11", "so tai khoan 19036789012345 vietcombank phai khong", {"bank_account": 1},
     "khong_dau", "finance: tai khoan + 14 so"),
    ("E12", "ông ngoại bị bệnh tim, uống loại nhẹ nhất được không", {}, "dau",
     "health: benh tim"),
]
for cid, text, expect, variant, note in _SENSITIVE:
    CASES.append(case(cid, text, risk="D2", variant=variant, note=note, **expect))

# ---------------------------------------------------------------------------
# F. NEGATIVE (D0) — khong PII; gom cac bay dong am/so lieu domain (CLAUDE.md §6)
# ---------------------------------------------------------------------------
_NEGATIVES = [
    ("F01", "cho mình 2 gói 500g nhé"),
    ("F02", "đơn A123 tới đâu rồi shop"),
    ("F03", "ship Cà Mau được không?"),  # ten tinh don le = cau hoi vung giao
    ("F04", "ship ca mau duoc khong"),
    ("F05", "cà phê này chua quá, đổi vị khác được không"),  # bay "chua"/"chưa"
    ("F06", "chưa nhận được hàng nha shop"),
    ("F07", "máy pha bị hỏng rồi, không lên nước"),  # bay "hong"/"khong"
    ("F08", "giá 120000 đồng một gói phải không"),
    ("F09", "tổng đơn 1.250.000đ đúng chưa"),
    ("F10", "giao 10 giờ 30 sáng mai nhé"),
    ("F11", "tp hồ chí minh còn ship trong ngày không"),  # admin+tinh = dia danh
    ("F12", "đà nẵng đường xa vậy phí ship nhiêu"),  # bay street+province khong so
    ("F13", "quán gần phố đi bộ không shop"),
    ("F14", "cho 1 ly cà phê sữa với 2 ly đen đá"),  # bay "ly"
    ("F15", "hạn dùng tới năm 2027 hả"),
    ("F16", "mã giảm giá SALE50 còn không"),
    ("F17", "gói 250g với gói 1kg lệch nhau nhiêu tiền"),
    ("F18", "order hom qua chua thay xac nhan"),
    ("F19", "cà phê phin với cà phê pha máy khác gì nhau"),
    ("F20", "shop mở cửa tới mấy giờ"),
]
for cid, text in _NEGATIVES:
    CASES.append(case(cid, text, risk="D0", note="negative"))

# ---------------------------------------------------------------------------
# G. KNOWN LIMITATIONS (gate=false) — ky vong detector MISS o v0.1; ghi nhan
# trong failure taxonomy, KHONG tinh gate. Khong duoc xoa de lam dep so lieu.
# ---------------------------------------------------------------------------
_LIMITS = [
    ("G01", "số mình là không chín một hai ba bốn năm sáu bảy tám nhé",
     {"phone": 1}, "phone doc bang chu (spelled-out)"),
    ("G02", "goi cho hoa nhe", {"name": 1},
     "ten thuong khong dau, khong cue manh ('hoa' = ten/loai hoa)"),
    ("G03", "số đuôi 678 đó, đầu 0912 với 345 ở giữa", {"phone": 1},
     "phone tach roi nhieu cum cach xa"),
    ("G04", "0912🌟345🌟678 nha shop", {"phone": 1},
     "phone chen emoji giua cac cum so"),
    ("G05", "nha o cho lon do, hem thu hai ben trai qua cay xang", {"address": 1},
     "dia chi mo ta loi noi, khong thanh phan chuan"),
    ("G06", "tui ten Ut Nho o duoi que", {"name": 1},
     "ten goi mien Tay khong ho, cue 'ten' yeu + khong viet hoa chuan"),
]
for cid, text, expect, note in _LIMITS:
    CASES.append(case(cid, text, risk="D1", gate=False, note=note, **expect))


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    ids = [c["id"] for c in CASES]
    assert len(ids) == len(set(ids)), "trung id trong corpus"
    with OUT.open("w", encoding="utf-8", newline="\n") as f:
        for c in CASES:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    gate_n = sum(1 for c in CASES if c["gate"])
    print(f"wrote {len(CASES)} cases ({gate_n} gate, {len(CASES) - gate_n} known-limit) -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
