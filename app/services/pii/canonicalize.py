"""I-B M4 Stage 0P — canonicalization DUY NHAT dung chung giua collector (khong con truc tiep
dung de ky) va trusted capture signing service (REV11 F-M4-0P-T10-01/T10-02).

CA Technical Re-review #10 (F-M4-0P-T10-01): tach rieng module nay de ca DB
(`m4_stage0p_fetch_message_content`, PL/pgSQL) LAN signing service (Python, tien trinh RIENG —
xem `stage0p_signing_service.py`) dung CHINH XAC 1 thuat toan — truoc REV11, collector tu goi
`_truncate(nfc(...))` ROI truyen canonical_len/truncated/digest da tinh SAN cho signer nhu tham so
DUOC TIN CAY — CA chi ro day la lo hong ("signer ky metadata do caller tu khai ma khong kiem tra
khop plaintext vua encrypt"). REV11: CHI signing service duoc goi ham nay — no tu canonicalize tu
RAW content (chua qua xu ly gi), tu doo suy ra digest/length/truncated, khong con nhan bat ky gia
tri nao trong so do tu caller nhu authority."""

from app.services.pii.normalize import nfc

MAX_CHARS = 2000
MAX_BYTES = 8000


def truncate_canonical(text: str) -> tuple[str, bool]:
    """MAX_CHARS truoc, MAX_BYTES sau — UTF-8-safe CA HAI buoc (F-M4-0P-03B). GIONG HET thu tu
    PL/pgSQL `m4_stage0p_fetch_message_content` ap dung (migration 039) — 2 noi PHAI khop tuyet
    doi de digest tinh doc lap o ca hai phia ra CUNG gia tri.

    Buoc 1: cat theo code point (string slicing luon an toan UTF-8).
    Buoc 2: encode UTF-8, neu qua MAX_BYTES thi cat tren BYTES da encode roi decode voi
    errors='ignore' — CHI loai bo dung phan byte KHONG HOAN CHINH bi chen dot o cuoi, khong
    lam hong bat ky ky tu nao dung truoc do."""
    truncated = False
    s = text
    if len(s) > MAX_CHARS:
        s = s[:MAX_CHARS]
        truncated = True
    encoded = s.encode("utf-8")
    if len(encoded) > MAX_BYTES:
        s = encoded[:MAX_BYTES].decode("utf-8", errors="ignore")
        truncated = True
    return s, truncated


def canonicalize(raw_content: str) -> tuple[str, bool]:
    """`nfc()` + `truncate_canonical()` tren `raw_content` — raw_content PHAI la gia tri DB da
    tra ve (vd `left(content, 2000)` cua `fetch_message_content`), KHONG phai noi dung goc chua
    qua xu ly, de khop dung 2 buoc DB da lam TRUOC khi ap dung nfc/truncate ben phia PL/pgSQL."""
    return truncate_canonical(nfc(raw_content))
