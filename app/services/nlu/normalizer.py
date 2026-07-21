"""Normalization engine cho NLU dataset (Alpha3S NLU layer - Bat A, nang
cap v1.1 theo NLU-INTEGRATION-GUIDE.md 18/7):
1. Unicode normalization
2. Trim + gop khoang trang
3. Nhan dien + tam bao ve Brand/Product names (protected_phrases) - MOI v1.1
4. Chuan hoa hoa/thuong cho matching
5. Ap dung phrase mappings truoc token mappings
6. Khoi phuc canonical protected phrases - MOI v1.1
7. Tao phien ban khong dau nhu tin hieu phu; KHONG thay the cau goc

BUG THUC TE PHAT HIEN KHI TEST (18/7, Bat A): ap dung rule TUAN TU tung cai
mot (vong lap for) khien 1 rule co the vo tinh khop VAO KET QUA cua rule
truoc do - vi du rule "con ko"->"con khong" va rule rieng "con k"->"con
khong" (2 rule KHAC nhau, cung dich nghia) - sau khi rule dau chay xong,
chuoi ket qua "con khong" da TU CHUA san "con k" o dau (vi "khong" bat dau
bang "k"), khien rule thu 2 khop DE LEN lan nua, ra ket qua sai "con
khonghong". FIX: ap dung TAT CA rule PHRASE trong 1 LAN QUET DUY NHAT.

BUG THUC TE KHAC (Bat A): "3S Coffee" (ten thuong hieu) bi rule
"coffee"->"cà phê" doi nham thanh "3S cà phê". FIX v1.1: them
protected_phrases - tam thay the bang placeholder TRUOC khi chay rule,
khoi phuc lai canonical form SAU khi rule chay xong.

protected_phrases GIO DA CO FILE CHINH THUC tu team Knowledge
(datasets/nlu/protected-phrases.yaml, 18/7) - gom 3 phrase: "3S Coffee",
"Robanme", "Công ty Cổ phần Robanme". QUAN TRONG: sap xep theo DO DAI GIAM
DAN (longest_phrase_first, dung field `validation.longest_phrase_first` cua
file) truoc khi xu ly - "Công ty Cổ phần Robanme" CHUA "Robanme" ben trong,
neu xu ly "Robanme" truoc se pha vo kha nang khop cum dai hon. Da test dung
voi du lieu that qua sandbox truoc khi dua vao code chinh thuc.

Ham `normalize()` van nhan `protected_phrases` qua tham so (khong tu doc
file) - script goi (nlu_build.py, scripts/nlu_*_test.py) chiu trach nhiem
load tu `datasets/nlu/protected-phrases.yaml` roi truyen vao. Neu khong
truyen gi, dung DEFAULT_PROTECTED_PHRASES (chi co "3S Coffee", du lieu tam
tu truoc khi co file chinh thuc) de code cu (chua cap nhat) khong bi vo.
"""

import re
import unicodedata

# DU LIEU DU PHONG - dung khi khong truyen protected_phrases vao normalize().
# Uu tien dung du lieu THAT tu datasets/nlu/protected-phrases.yaml qua
# loader.load_protected_phrases().
DEFAULT_PROTECTED_PHRASES: list[dict] = [
    {"canonical": "3S Coffee", "variants": ["3S Coffee", "3s coffee", "3S coffee"], "match": "phrase"},
]


def strip_diacritics(text: str) -> str:
    """Bo dau tieng Viet + chuyen thuong - dung lam tin hieu PHU (buoc 7),
    KHONG thay the cau da normalize."""
    text = text.lower().replace("đ", "d")
    normalized = unicodedata.normalize("NFD", text)
    return "".join(c for c in normalized if unicodedata.category(c) != "Mn")


def normalize(
    text: str, rules: list[dict], protected_phrases: list[dict] | None = None
) -> str:
    """Tra ve cau da normalize. Khong thay doi y nghia, chi hinh thuc dien
    dat (dung theo README.md: "Normalization chi thay doi hinh thuc, khong
    thay doi y nghia").

    protected_phrases: mac dinh dung DEFAULT_PROTECTED_PHRASES (du lieu du
    phong) neu khong truyen vao - xem docstring module.
    """
    result = " ".join(text.strip().split())  # buoc 2: trim + gop khoang trang

    if protected_phrases is None:
        protected_phrases = DEFAULT_PROTECTED_PHRASES

    # Buoc 3: nhan dien + tam bao ve Brand/Product names (v1.1). Sap xep
    # phrase DAI truoc (longest_phrase_first) - tranh phrase ngan (vd
    # "Robanme") bi thay the TRUOC, pha vo kha nang khop phrase dai hon
    # chua no ben trong (vd "Công ty Cổ phần Robanme").
    sorted_phrases = sorted(
        protected_phrases,
        key=lambda p: max(len(v) for v in (p.get("variants", []) + [p["canonical"]])),
        reverse=True,
    )

    # Thay moi variant bang 1 placeholder DUY NHAT KHONG THE bi rule nao
    # khac khop nham (dung ky tu dieu khien \x00, khong xuat hien trong
    # text thuong).
    placeholders: dict[str, str] = {}
    for idx, p in enumerate(sorted_phrases):
        canonical = p["canonical"]
        match_type = p.get("match", "phrase")
        variants = sorted(set(p.get("variants", [canonical]) + [canonical]), key=lambda v: -len(v))
        placeholder = f"\x00PROTECTED{idx}\x00"
        for variant in variants:
            if match_type == "token":
                pattern = re.compile(r"\b" + re.escape(variant) + r"\b", re.IGNORECASE)
            else:
                pattern = re.compile(re.escape(variant), re.IGNORECASE)
            if pattern.search(result):
                result = pattern.sub(placeholder, result)
        if placeholder in result:
            placeholders[placeholder] = canonical

    # Buoc 4-5: chuan hoa hoa/thuong + ap dung phrase mappings TRUOC token
    # mappings, trong 1 LAN QUET DUY NHAT cho moi loai (xem bug cascading o
    # docstring module).
    phrase_rules = sorted(
        [r for r in rules if r.get("match") == "phrase"], key=lambda r: -len(r["source"])
    )
    if phrase_rules:
        combined = "|".join(re.escape(r["source"]) for r in phrase_rules)
        lookup = {r["source"].lower(): r["target"] for r in phrase_rules}
        result = re.compile(combined, re.IGNORECASE).sub(
            lambda m: lookup[m.group(0).lower()], result
        )

    token_rules = sorted(
        [r for r in rules if r.get("match") == "token"], key=lambda r: -len(r["source"])
    )
    if token_rules:
        combined_tok = "|".join(r"\b" + re.escape(r["source"]) + r"\b" for r in token_rules)
        lookup_tok = {r["source"].lower(): r["target"] for r in token_rules}
        result = re.compile(combined_tok, re.IGNORECASE).sub(
            lambda m: lookup_tok[m.group(0).lower()], result
        )

    # Buoc 6: khoi phuc canonical protected phrases (v1.1)
    for placeholder, canonical in placeholders.items():
        result = result.replace(placeholder, canonical)

    return result


def normalize_with_accentless(
    text: str, rules: list[dict], protected_phrases: list[dict] | None = None
) -> tuple[str, str]:
    """Tra ve (normalized_text, accentless_signal) - accentless CHI la tin
    hieu phu bo sung (buoc 7 trong NLU-INTEGRATION-GUIDE.md), dung lam du
    lieu them cho pattern/semantic router, KHONG thay the cau da normalize."""
    normalized = normalize(text, rules, protected_phrases)
    accentless = strip_diacritics(normalized)
    return normalized, accentless
