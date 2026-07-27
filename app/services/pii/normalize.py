"""I-B M4-S0 — chuan hoa van ban cho PII detector, GIU ANH XA OFFSET 1:1.

Bai hoc CLAUDE.md §6: bo dau de so khop chi khi bo dau o CA HAI PHIA (input lan
tu dien) mot cach nhat quan. Module nay fold dau THEO TUNG KY TU tren van ban da
NFC-normalize, nen ket qua co CUNG DO DAI voi input — moi offset tren ban fold
tro dung ve ky tu goc (span PII tham chieu offset, khong luu plaintext).

Khac voi nlu/normalizer.strip_diacritics (fold ca chuoi, khong dam bao do dai),
day la ban rieng cho PII vi yeu cau offset — KHONG import cheo sang NLU de giu
ranh gioi kien truc (NLU va PII la 2 duong doc lap).
"""

import unicodedata


def nfc(text: str) -> str:
    """Chuan hoa NFC — moi offset trong module nay tinh tren ban NFC."""
    return unicodedata.normalize("NFC", text)


def fold(text_nfc: str) -> str:
    """Fold dau + lowercase, giu do dai: 'Cà Mau' -> 'ca mau', 'Đường' -> 'duong'.

    Input PHAI la ban NFC (tu ham nfc() o tren). Voi ky tu to hop don le (van ban
    da NFD tu truoc) fold co the giu nguyen ky tu — chap nhan duoc vi nfc() da
    gop truoc do.
    """
    out: list[str] = []
    for ch in text_nfc.lower():
        if ch == "đ":
            out.append("d")
            continue
        decomp = unicodedata.normalize("NFD", ch)
        base = "".join(c for c in decomp if unicodedata.category(c) != "Mn")
        # base rong (ky tu to hop tran vao) -> giu ky tu goc de bao toan do dai
        out.append(base if len(base) == 1 else ch)
    return "".join(out)
