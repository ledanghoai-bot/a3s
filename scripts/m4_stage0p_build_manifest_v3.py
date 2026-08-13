"""I-B M4 Stage 0P — sinh manifest v3 tu v2 (dap PHASE1B-M4-MANIFEST-V3-PREPARATION-DIRECTIVE-VI.md).

v3 = TOAN BO v2 (giu nguyen byte-for-byte tung dong) + 90 entry moi:
    +30 national_id positive, +30 bank_account positive, +30 negative.
=> conversation_count 225 -> 315 (dung target PO chot).

VI SAO CAN: v2 chi co 5 mau national_id va 5 mau bank_account, va ca 5 GIONG HET NHAU (cung mot cau,
chi khac chu so cuoi). PO Decision doi toi thieu 30 positive samples MOI LOAI, va CA yeu cau da dang
that su theo cue / dau / hoa-thuong / separator / do dai / vi tri trong cau — nhan ban 30 lan cung
mot mau se dat dieu kien ve chu nhung khong do them duoc gi.

OFFSET: sinh BANG CHUONG TRINH (tinh tu vi tri chen), KHONG go tay — tranh lech bien, vi metric gate
la `exact_span_match` (start/end khop tuyet doi).

DU LIEU: 100% tong hop. Khong lay tu log/DB production, khong sao chep chuoi nao tu du lieu khach
hang. So gia sinh trong dai danh rieng cho test.

Chay:  python scripts/m4_stage0p_build_manifest_v3.py
Ghi:   datasets/pii/m4_stage0p_rehearsal_manifest_v3.jsonl (LF, khong CRLF — xem .gitattributes)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
V2 = REPO / "datasets" / "pii" / "m4_stage0p_rehearsal_manifest_v2.jsonl"
V3 = REPO / "datasets" / "pii" / "m4_stage0p_rehearsal_manifest_v3.jsonl"

MANIFEST_VERSION = "m4-stage0p-rehearsal-manifest-v3"
PSID_PREFIX = "m4synthrehearsalv1_"


def _entry(seq: int, key: str, text: str, slots: list[dict], note: str,
           expect_gate: bool) -> dict:
    """1 conversation = 1 message. `slots` la list (slot_type, substring) — offset TU TINH."""
    labeled = []
    for slot_type, substring, reason in slots:
        idx = text.index(substring)
        labeled.append({
            "slot_type": slot_type,
            "start": idx,
            "end": idx + len(substring),
            "confidence": "high",
            "reason": reason,
        })
    return {
        "manifest_version": MANIFEST_VERSION,
        "psid": f"{PSID_PREFIX}{seq:06d}",
        "conversation_key": key,
        "messages": [{
            "role": "customer",
            "content": text,
            "canonical_text": text,
            "labeled_slots": labeled,
        }],
        "expect_gate": expect_gate,
        "note": note,
    }


# ---------------------------------------------------------------------------
# 30 national_id positive — da dang theo 6 chieu
# ---------------------------------------------------------------------------
# So gia: CCCD 12 so prefix 079 (ma tinh hop le VE HINH THUC), CMND 9 so — deu la dai danh cho test.
def national_id_cases() -> list[tuple[str, str, str, str]]:
    """(text, substring, reason, note)"""
    c = []
    # (a) cue day du, co dau, hoa/thuong khac nhau  [6]
    c += [
        ("CCCD của tôi là 079300010001 nhé shop", "079300010001", "nid_cue_digits", "nid cue CCCD hoa, co dau"),
        ("cccd của tôi là 079300010002 nhé shop", "079300010002", "nid_cue_digits", "nid cue cccd thuong, co dau"),
        ("Cccd của mình là 079300010003 ạ", "079300010003", "nid_cue_digits", "nid cue Cccd hoa dau"),
        ("căn cước của tôi là 079300010004 nhé", "079300010004", "nid_cue_digits", "nid cue 'can cuoc' co dau"),
        ("số căn cước 079300010005 của mình", "079300010005", "nid_cue_digits", "nid cue 'so can cuoc'"),
        ("chứng minh nhân dân 079300010006 nhé", "079300010006", "nid_cue_digits", "nid cue CMND day du chu"),
    ]
    # (b) khong dau (khach go khong dau — rat pho bien)  [6]
    c += [
        ("cccd cua toi la 079300010007 nhe shop", "079300010007", "nid_cue_digits", "nid khong dau"),
        ("CCCD cua minh 079300010008 nhe", "079300010008", "nid_cue_digits", "nid khong dau, cue hoa"),
        ("can cuoc cua toi la 079300010009 a", "079300010009", "nid_cue_digits", "nid khong dau 'can cuoc'"),
        ("so can cuoc 079300010010 nhe", "079300010010", "nid_cue_digits", "nid khong dau 'so can cuoc'"),
        ("chung minh nhan dan 079300010011 nhe", "079300010011", "nid_cue_digits", "nid khong dau CMND"),
        ("CMND 079300010012 cua minh day", "079300010012", "nid_cue_digits", "nid cue CMND ngan"),
    ]
    # (c) separator (khoang trang / cham / gach)  [6]
    c += [
        ("CCCD của tôi là 079 300 010013 nhé", "079 300 010013", "nid_cue_digits", "nid separator khoang trang"),
        ("CCCD của tôi là 079.300.010014 nhé", "079.300.010014", "nid_cue_digits", "nid separator dau cham"),
        ("CCCD của tôi là 079-300-010015 nhé", "079-300-010015", "nid_cue_digits", "nid separator gach ngang"),
        ("can cuoc 079 300 010016 nhe shop", "079 300 010016", "nid_cue_digits", "nid khong dau + khoang trang"),
        ("cccd 079.300.010017 nhe", "079.300.010017", "nid_cue_digits", "nid khong dau + cham"),
        ("CMND 079300018 nhé shop", "079300018", "nid_cue_digits", "CMND 9 so co cue"),
    ]
    # (d) do dai 9 so (CMND) — can cue moi nhan duoc  [4]
    c += [
        ("chứng minh nhân dân 079300019 của mình", "079300019", "nid_cue_digits", "CMND 9 so co dau"),
        ("cmnd 079300020 nhe", "079300020", "nid_cue_digits", "CMND 9 so khong dau"),
        ("số CMND 079300021 nhé shop", "079300021", "nid_cue_digits", "CMND 9 so + tu 'so'"),
        ("can cuoc cong dan 079300022 nhe", "079300022", "nid_cue_digits", "CMND 9 so cue dai"),
    ]
    # (e) vi tri trong cau: dau / cuoi  [4]
    c += [
        ("CCCD 079300010023", "079300010023", "nid_cue_digits", "nid o CUOI cau, khong tu thua"),
        ("cccd 079300010024 shop kiem tra giup", "079300010024", "nid_cue_digits", "nid gan DAU cau"),
        ("mình gửi CCCD 079300010025 để xác minh nhé", "079300010025", "nid_cue_digits", "nid GIUA cau"),
        ("xác minh giúp mình CCCD 079300010026", "079300010026", "nid_cue_digits", "nid cuoi cau, cue sat"),
    ]
    # (f) bare 12 so (khong cue) — fallback MEDIUM theo PO policy huong (ii)  [4]
    c += [
        ("079300010027 là số của mình nhé", "079300010027", "nid_12_digits", "bare 12 so, khong cue"),
        ("079300010028", "079300010028", "nid_12_digits", "bare 12 so, mot minh"),
        ("mình gửi 079300010029 nhé shop", "079300010029", "nid_12_digits", "bare 12 so giua cau"),
        ("so cua minh 079300010030 nhe", "079300010030", "nid_12_digits", "bare 12 so, cue mo ho 'so'"),
    ]
    return c


# ---------------------------------------------------------------------------
# 30 bank_account positive — da dang, GOM day du dai 8..19 (PO policy B)
# ---------------------------------------------------------------------------
def bank_account_cases() -> list[tuple[str, str, str, str]]:
    c = []
    # (a) phu HET do dai 8..19 (12 ca) — dieu kien cua PO policy B
    base = "7100"
    for n in range(8, 20):
        digits = (base + "0123456789012345678")[:n]
        c.append((f"chuyển khoản tới STK {digits} nhé", digits, "bank_cue_digits",
                  f"bank do dai {n} so"))
    # (b) cue khac nhau  [6]
    c += [
        ("số tài khoản 71001000001 của mình", "71001000001", "bank_cue_digits", "cue 'so tai khoan'"),
        ("tài khoản 710010000021 nhé shop", "710010000021", "bank_cue_digits", "cue 'tai khoan' (12 so)"),
        ("số thẻ 7100100000312 của mình", "7100100000312", "bank_cue_digits", "cue 'so the'"),
        ("stk 71001000004 nhe", "71001000004", "bank_cue_digits", "cue stk thuong khong dau"),
        ("STK 71001000005 Techcombank nhé", "71001000005", "bank_cue_digits", "cue STK + ten ngan hang"),
        ("so tai khoan cua minh 71001000006 nhe", "71001000006", "bank_cue_digits", "cue khong dau"),
    ]
    # (c) separator  [6]
    c += [
        ("STK 7100 1000 007 nhé", "7100 1000 007", "bank_cue_digits", "bank separator khoang trang"),
        ("số tài khoản 7100.1000.008 nhé", "7100.1000.008", "bank_cue_digits", "bank separator cham"),
        ("tài khoản 7100-1000-009 nhé", "7100-1000-009", "bank_cue_digits", "bank separator gach"),
        ("STK 7100 1000 0010 123 nhé", "7100 1000 0010 123", "bank_cue_digits", "bank 15 so + khoang trang"),
        ("so tai khoan 7100-1000-0011-2345 nhe", "7100-1000-0011-2345", "bank_cue_digits", "bank 18 so + gach"),
        ("tai khoan 7100.1000.0012.34567 nhe", "7100.1000.0012.34567", "bank_cue_digits", "bank 19 so + cham"),
    ]
    # (d) vi tri trong cau  [6]
    c += [
        ("STK 71001000013", "71001000013", "bank_cue_digits", "bank o CUOI cau"),
        ("tài khoản 71001000014 shop chuyển giúp", "71001000014", "bank_cue_digits", "bank gan DAU cau"),
        ("mình gửi STK 71001000015 để shop chuyển nhé", "71001000015", "bank_cue_digits", "bank GIUA cau"),
        ("chuyển vào số tài khoản 71001000016 giúp mình", "71001000016", "bank_cue_digits", "bank cuoi, cue dai"),
        ("STK của mình là 71001000017 nha", "71001000017", "bank_cue_digits", "bank cue + 'cua minh la'"),
        ("shop ơi tài khoản 71001000018 nhé", "71001000018", "bank_cue_digits", "bank sau tu goi"),
    ]
    return c


# ---------------------------------------------------------------------------
# 30 negative — KHONG duoc gan slot nao
# ---------------------------------------------------------------------------
def negative_cases() -> list[tuple[str, str]]:
    """(text, note) — labeled_slots RONG hoan toan (khong phai PII loai nao).

    LUU Y QUAN TRONG ve dinh nghia "negative": Directive doi negatives phu ca "international phone"
    va "address-number contexts". Nhung phone quoc te VAN LA `phone` PII, va dia chi VAN LA
    `address` PII — chung chi la negative DOI VOI `national_id`/`bank_account`, khong phai "khong
    co PII".
    Ban dau Dev de chung o day voi labeled_slots rong -> do ra 4 phone fp + 4 address fp, vi
    detector bat DUNG con ground truth thi SAI. Da chuyen sang `cross_slot_negative_cases()` ben
    duoi, gan nhan THAT cua chung.
    """
    return [
        # order / transaction codes (12 so — dung dai de nham national_id)  [8]
        ("đơn hàng 079400010001 tới chưa shop", "neg order code 12 so co dau"),
        ("don hang 079400010002 giao chua", "neg order code khong dau"),
        ("mã đơn 079400010003 kiểm tra giúp mình", "neg ma don co dau"),
        ("ma don 079400010004 sao roi shop", "neg ma don khong dau"),
        ("mã giao dịch 079400010005 đã chuyển", "neg ma giao dich co dau"),
        ("ma giao dich 079400010006 nhe", "neg ma giao dich khong dau"),
        ("order 079400010007 status thế nào", "neg order tieng Anh"),
        ("transaction 079400010008 pending nhé", "neg transaction tieng Anh"),
        # order / transaction dai 17-19 so (dai bank moi — do precision policy B)  [6]
        ("mã giao dịch 07940001000900011 đã chuyển tiền", "neg ma giao dich 17 so"),
        ("mã tham chiếu chuyển khoản 079400010010000112 nhé", "neg ma tham chieu 18 so"),
        ("nội dung chuyển khoản 0794000100110001123 đã gửi", "neg noi dung CK 19 so"),
        ("hóa đơn 07940001001200011 đã thanh toán", "neg hoa don 17 so"),
        ("mã vận đơn 079400010013000112 giao rồi", "neg ma van don 18 so"),
        ("ma don 0794000100140001123 da chuyen khoan", "neg ma don 19 so"),
        # so tien  [5]
        ("chuyển 71000123456 đồng nhé", "neg so tien 11 so"),
        ("tổng đơn 1.250.000đ nhé shop", "neg so tien co dau cham"),
        ("giá 120000 đồng thôi", "neg so tien ngan"),
        ("thanh toán 7100012345678 đồng", "neg so tien 13 so"),
        ("phí ship 35000 nhé", "neg phi ship"),
        # chuoi so khac khong phai PII loai nao  [3]
        ("năm 2026 hết hạn nhé", "neg nam"),
        ("đơn A123 tới đâu rồi", "neg ma don chu+so"),
        ("lô hàng LOT20260813 tới chưa", "neg ma lo chu+so"),
    ]


# ---------------------------------------------------------------------------
# Cross-slot negative: LA PII loai khac, nhung KHONG duoc la national_id/bank_account
# ---------------------------------------------------------------------------
def cross_slot_negative_cases() -> list[tuple[str, str, str, str]]:
    """(text, substring, reason, note) — Directive doi phu "international phone" va
    "address-number contexts" trong negative set.

    Nhung day la negative DOI VOI nid/bank, KHONG phai "khong co PII": so dien thoai quoc te van la
    `phone`, dia chi van la `address`. Neu de labeled_slots rong thi chinh GROUND TRUTH sai, va
    detector bat dung lai bi tinh false positive — Dev da mac loi nay o ban dau tien va sua o day.
    """
    return [
        # international phone -> PHAI la phone, KHONG duoc la nid/bank  [4]
        ("liên hệ +84 301234501 nhé", "+84 301234501", "phone_valid_vn_mobile",
         "intl phone: negative cho nid/bank, positive cho phone"),
        ("gọi +84912345602 giúp mình", "+84912345602", "phone_valid_vn_mobile",
         "intl phone lien: negative cho nid/bank"),
        ("số 84912345603 nhé shop", "84912345603", "phone_valid_vn_mobile",
         "prefix 84: negative cho nid/bank"),
        ("liên hệ (+84)912345604 ạ", "(+84)912345604", "phone_valid_vn_mobile",
         "intl phone co ngoac: negative cho nid/bank"),
        # address-number context -> PHAI la address, KHONG duoc la nid/bank  [4]
        ("giao về 45 đường Trần Hưng Đạo, phường 6, quận Long Biên nhé",
         "45 đường Trần Hưng Đạo, phường 6, quận Long Biên", "addr_multi_component",
         "so nha trong dia chi: negative cho nid/bank"),
        ("giao về số 12 đường Hai Bà Trưng, phường 8, quận Tân Bình nhé",
         "số 12 đường Hai Bà Trưng, phường 8, quận Tân Bình", "addr_multi_component",
         "so nha + quan: negative cho nid/bank"),
        ("địa chỉ 78/9 đường Phan Đình Phùng, phường 11, quận Ba Đình",
         "78/9 đường Phan Đình Phùng, phường 11, quận Ba Đình", "addr_multi_component",
         "dia chi co gach cheo: negative cho nid/bank"),
        ("giao về 123 đường Nguyễn Văn Cừ, phường 14, quận Hoàn Kiếm",
         "123 đường Nguyễn Văn Cừ, phường 14, quận Hoàn Kiếm", "addr_multi_component",
         "so nha 3 chu so: negative cho nid/bank"),
    ]


def main() -> int:
    if not V2.exists():
        print(f"LOI: khong thay v2 tai {V2}", file=sys.stderr)
        return 1

    # Doc v2 nguyen van (text mode, newline='' de KHONG bien doi line ending khi doc).
    v2_lines = V2.read_text(encoding="utf-8").splitlines()
    if len(v2_lines) != 225:
        print(f"LOI: v2 phai co dung 225 dong, thuc te {len(v2_lines)}", file=sys.stderr)
        return 1

    out: list[str] = []
    # Giu NGUYEN 225 dong v2, chi doi truong manifest_version de v3 tu mo ta dung phien ban.
    for line in v2_lines:
        rec = json.loads(line)
        rec["manifest_version"] = MANIFEST_VERSION
        out.append(json.dumps(rec, ensure_ascii=False))

    seq = 225
    counts = {"national_id": 0, "bank_account": 0, "negative": 0}

    for i, (text, sub, reason, note) in enumerate(national_id_cases(), start=1):
        seq += 1
        out.append(json.dumps(
            _entry(seq, f"RN{i:03d}", text, [("national_id", sub, reason)], note, True),
            ensure_ascii=False))
        counts["national_id"] += 1

    for i, (text, sub, reason, note) in enumerate(bank_account_cases(), start=1):
        seq += 1
        out.append(json.dumps(
            _entry(seq, f"RB{i:03d}", text, [("bank_account", sub, reason)], note, True),
            ensure_ascii=False))
        counts["bank_account"] += 1

    for i, (text, note) in enumerate(negative_cases(), start=1):
        seq += 1
        out.append(json.dumps(
            _entry(seq, f"RX{i:03d}", text, [], note, False),
            ensure_ascii=False))
        counts["negative"] += 1

    # Cross-slot negative: co nhan PII loai khac (phone/address) nhung phai KHONG phai nid/bank.
    for i, (text, sub, reason, note) in enumerate(cross_slot_negative_cases(), start=1):
        seq += 1
        slot = "phone" if reason.startswith("phone") else "address"
        out.append(json.dumps(
            _entry(seq, f"RC{i:03d}", text, [(slot, sub, reason)], note, True),
            ensure_ascii=False))
        counts["cross_slot_negative"] = counts.get("cross_slot_negative", 0) + 1

    # Ghi LF tuyet doi (newline="\n") — khong phu thuoc nen tang, de canonical SHA-256 duy nhat.
    with open(V3, "w", encoding="utf-8", newline="\n") as fh:
        for line in out:
            fh.write(line + "\n")

    print(f"v2 lines kept        : {len(v2_lines)}")
    print(f"national_id added    : {counts['national_id']}")
    print(f"bank_account added   : {counts['bank_account']}")
    print(f"negative added       : {counts['negative']}")
    print(f"cross-slot negative  : {counts.get('cross_slot_negative', 0)}")
    print(f"TOTAL v3 lines       : {len(out)}")
    print(f"written              : {V3}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
