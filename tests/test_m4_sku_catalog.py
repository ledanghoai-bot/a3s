"""I-B M4 (CA F-M4-S2-04 final): unit test trusted SKU catalog resolver."""

import asyncio

from app.services.pii.sku_catalog import build_catalog_map, resolve_skus


class FakeConn:
    def __init__(self, skus):
        self._skus = skus

    async def fetch(self, query):
        return [{"sku": s} for s in self._skus]


def _resolve(catalog, proposed):
    return asyncio.run(resolve_skus(FakeConn(catalog), proposed))


def test_exact_va_alias_ve_canonical():
    out = _resolve(["3S-100G", "3S-500G"], ["3S-100G", "3S100G", "3s-500g".upper()])
    assert out["3S-100G"] == "3S-100G"
    assert out["3S100G"] == "3S-100G"  # alias bo dash -> canonical
    assert out["3S-500G"] == "3S-500G"


def test_unknown_tra_none():
    out = _resolve(["3S-100G"], ["12-LE-LOI", "NGUYEN-VAN-AN", "0912345678"])
    assert all(v is None for v in out.values())


def test_ambiguous_fail_closed():
    # 2 canonical khac nhau nhung cung khoa normalize -> khong resolve
    canon, dup = build_catalog_map(["3S-100G", "3S10-0G"])
    assert "3S100G" in dup
    out = _resolve(["3S-100G", "3S10-0G"], ["3S100G", "3S-100G"])
    assert out["3S100G"] is None and out["3S-100G"] is None


def test_chuoi_rong_sau_normalize_tra_none():
    out = _resolve(["3S-100G"], ["---"])
    assert out["---"] is None
