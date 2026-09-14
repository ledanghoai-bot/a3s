"""VietQR TU SINH (CA Directive 272 §3.3) — payload EMVCo MPM / NAPAS QRIBFTTA, thuan Python, KHONG goi API ngan hang,
KHONG tao giao dich. Ung dung sinh payload + anh QR TU SNAPSHOT payment instruction (bank BIN, so tai khoản dang text,
so tien VND, noi dung `3SCF <order-id>`), doc lap SePay.

Cau truc (NAPAS "QR thanh toan/chuyen tien nhanh toi tai khoan"):
  00 02 01                      Payload Format Indicator
  01 02 12                      Point of Initiation (12 = dynamic, dung 1 lan / co so tien)
  38 xx                         Merchant Account Information (NAPAS)
     00 06 A000000727           GUID NAPAS
     01 xx  [00 06 <BIN>][01 xx <account>]   Beneficiary
     02 08 QRIBFTTA             Service: chuyen nhanh toi TAI KHOAN
  53 03 704                     Currency VND
  54 xx <amount>                So tien (nguyen, khong thap phan)
  58 02 VN                      Country
  62 xx [08 xx <addInfo>]       Additional Data: Purpose of Transaction (noi dung CK)
  63 04 <CRC16-CCITT-FALSE>     CRC tren toan bo chuoi ke ca "6304", hex hoa

decode() parse TLV nguoc + verify CRC -> chung minh BIN/account/amount/content khop (DoD "decode-test").
"""
from __future__ import annotations

import re
from dataclasses import dataclass

NAPAS_GUID = "A000000727"
SERVICE_TO_ACCOUNT = "QRIBFTTA"
CURRENCY_VND = "704"
COUNTRY_VN = "VN"
MAX_ADD_INFO = 25          # gioi han noi dung chuyen khoan (NAPAS purpose of transaction)
MAX_ACCOUNT_LEN = 19
MAX_AMOUNT_DIGITS = 13

_BIN_RE = re.compile(r"^[0-9]{6}$")
_ACCT_RE = re.compile(r"^[0-9A-Za-z]{1,19}$")
_ADDINFO_RE = re.compile(r"^[0-9A-Za-z ._-]{1,25}$")


class VietQRError(ValueError):
    """Input khong hop le — fail-closed (khong sinh QR sai)."""


def crc16_ccitt_false(data: bytes) -> int:
    """CRC-16/CCITT-FALSE: poly 0x1021, init 0xFFFF, khong reflect, xorout 0 (EMVCo QR)."""
    crc = 0xFFFF
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if (crc & 0x8000) else (crc << 1)
            crc &= 0xFFFF
    return crc


def _tlv(tag: str, value: str) -> str:
    if len(value) > 99:
        raise VietQRError(f"tag {tag} qua dai ({len(value)} > 99)")
    return f"{tag}{len(value):02d}{value}"


def validate_inputs(*, bin_code: str, account_number: str, amount_vnd: int, add_info: str) -> None:
    if not isinstance(bin_code, str) or not _BIN_RE.match(bin_code):
        raise VietQRError("bank BIN phai 6 chu so (NAPAS)")
    if not isinstance(account_number, str) or not _ACCT_RE.match(account_number):
        raise VietQRError("so tai khoan phai dang text 1-19 ky tu chu/so (giu so 0 dau)")
    if isinstance(amount_vnd, bool) or not isinstance(amount_vnd, int) or amount_vnd <= 0:
        raise VietQRError("amount_vnd phai so nguyen VND > 0")
    if len(str(amount_vnd)) > MAX_AMOUNT_DIGITS:
        raise VietQRError("amount_vnd qua lon")
    if not isinstance(add_info, str) or not _ADDINFO_RE.match(add_info):
        raise VietQRError(f"noi dung chuyen khoan chi chu/so/khoang trang, toi da {MAX_ADD_INFO} ky tu, khong dau")


def build_payload(*, bin_code: str, account_number: str, amount_vnd: int, add_info: str) -> str:
    """Sinh payload VietQR tat dinh tu snapshot. Cung input -> cung chuoi (khong timestamp/random)."""
    validate_inputs(bin_code=bin_code, account_number=account_number, amount_vnd=amount_vnd, add_info=add_info)
    beneficiary = _tlv("00", bin_code) + _tlv("01", account_number)
    mai = _tlv("00", NAPAS_GUID) + _tlv("01", beneficiary) + _tlv("02", SERVICE_TO_ACCOUNT)
    body = (
        _tlv("00", "01")
        + _tlv("01", "12")
        + _tlv("38", mai)
        + _tlv("53", CURRENCY_VND)
        + _tlv("54", str(amount_vnd))
        + _tlv("58", COUNTRY_VN)
        + _tlv("62", _tlv("08", add_info))
        + "6304"
    )
    return body + f"{crc16_ccitt_false(body.encode('ascii')):04X}"


@dataclass(frozen=True)
class Decoded:
    bin_code: str
    account_number: str
    amount_vnd: int | None
    add_info: str | None
    service: str | None
    currency: str | None
    country: str | None
    initiation: str | None
    crc_ok: bool


def _parse_tlv(s: str) -> dict[str, str]:
    out: dict[str, str] = {}
    i = 0
    while i < len(s):
        if i + 4 > len(s):
            raise VietQRError("TLV cut ngan")
        tag, ln = s[i:i + 2], s[i + 2:i + 4]
        if not (tag.isdigit() and ln.isdigit()):
            raise VietQRError(f"TLV header khong hop le tai {i}")
        n = int(ln)
        val = s[i + 4:i + 4 + n]
        if len(val) != n:
            raise VietQRError(f"TLV tag {tag} thieu du lieu")
        out[tag] = val
        i += 4 + n
    return out


def decode(payload: str) -> Decoded:
    """Parse nguoc payload + verify CRC. Khong hop le -> raise. Dung cho decode-test bang chung."""
    if not isinstance(payload, str) or len(payload) < 8 or not payload.isascii():
        raise VietQRError("payload rong/khong ASCII")
    if payload[-8:-4] != "6304":
        raise VietQRError("thieu CRC tag 63")
    body, crc_hex = payload[:-4], payload[-4:]
    crc_ok = f"{crc16_ccitt_false(body.encode('ascii')):04X}" == crc_hex.upper()
    top = _parse_tlv(payload)
    mai = _parse_tlv(top.get("38", ""))
    if mai.get("00") != NAPAS_GUID:
        raise VietQRError("khong phai VietQR NAPAS (GUID)")
    ben = _parse_tlv(mai.get("01", ""))
    add = _parse_tlv(top["62"]) if "62" in top else {}
    amt = top.get("54")
    return Decoded(
        bin_code=ben.get("00", ""), account_number=ben.get("01", ""),
        amount_vnd=int(amt) if amt and amt.isdigit() else None,
        add_info=add.get("08"), service=mai.get("02"), currency=top.get("53"), country=top.get("58"),
        initiation=top.get("01"), crc_ok=crc_ok,
    )


def png_bytes(payload: str, *, scale: int = 6) -> bytes | None:
    """Anh PNG tu payload (segno, thuan Python). None neu thieu lib -> caller gui text (khong chan luong)."""
    try:
        import io

        import segno
    except Exception:  # noqa: BLE001
        return None
    buf = io.BytesIO()
    segno.make(payload, error="M").save(buf, kind="png", scale=scale, border=2)
    return buf.getvalue()


def svg_data_uri(payload: str, *, scale: int = 4) -> str | None:
    """Data URI SVG cho dashboard preview (tai tao tu snapshot, khong luu anh)."""
    try:
        import segno
    except Exception:  # noqa: BLE001
        return None
    return segno.make(payload, error="M").svg_data_uri(scale=scale, border=2)
