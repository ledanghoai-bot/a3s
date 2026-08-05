"""I-B M4 (CA F-M4-S2-04 final) — trusted SKU catalog resolver.

Nguyen tac: MODEL KHONG BAO GIO la authority tao SKU string. Moi SKU model de
xuat chi la ung vien; trusted code doi chieu voi catalog that (bang `products`)
va command args CHI nhan canonical SKU do resolver tra ve — khong copy raw
model string.

- So khop normalize: upper + bo moi ky tu ngoai A-Z0-9 ("3s100g", "3S-100G" ->
  cung khoa "3S100G") => alias ve canonical.
- Khong tim thay / AMBIGUOUS (>=2 canonical trung khoa normalize) -> None
  (fail closed — caller di deterministic fallback, executor khong chay).
- Loi DB/catalog: RAISE — caller escalate fail-closed, khong doan.
- Khong log gia tri SKU raw cua model (co the la PII transliterate) — chi count.
"""

import re

_NORM_RE = re.compile(r"[^A-Z0-9]")


def _norm(value: str) -> str:
    return _NORM_RE.sub("", value.upper())


def build_catalog_map(skus: list[str]) -> tuple[dict[str, str], set[str]]:
    """Tu danh sach canonical SKU cua catalog -> (map normalize->canonical,
    tap khoa ambiguous). Tach rieng de test thuan logic."""
    canon: dict[str, str] = {}
    dup: set[str] = set()
    for sku in skus:
        key = _norm(sku)
        if key in canon and canon[key] != sku:
            dup.add(key)
        canon[key] = sku
    return canon, dup


async def resolve_skus(conn, proposed: list[str]) -> dict[str, str | None]:
    """Resolve tung SKU model de xuat ve canonical SKU trong catalog.

    Tra dict proposed -> canonical | None (None = unknown/ambiguous, fail
    closed). Catalog nho (vai chuc SKU) nen doc toan bo — tranh dua raw model
    string vao mau SQL LIKE/param phuc tap."""
    rows = await conn.fetch("SELECT sku FROM products")
    canon, dup = build_catalog_map([r["sku"] for r in rows])
    out: dict[str, str | None] = {}
    for p in proposed:
        key = _norm(p)
        out[p] = None if (not key or key in dup) else canon.get(key)
    return out
