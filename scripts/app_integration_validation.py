#!/usr/bin/env python3
"""App-integration validation (I-B M0, CA-REVIEW-M0-DEV-001 §8 lop 2).

Goi TOOL that (app.services.tools.search_products) va khang dinh: sau corrective 014
(serving_size_g=NULL), tool KHONG tra 'serving_info' cho 3S-100G -> bot khong suy
~50 ly/hu hay gia/ly (Product Fact chua duyet).

Exit != 0 neu fail. Chay trong container `api` voi DATABASE_URL tro toi DB can kiem:
  docker exec -e DATABASE_URL=... api python /srv/scripts/app_integration_validation.py
"""
import asyncio
import sys

from app.services import tools


async def main() -> int:
    res = await tools.search_products()
    prods = {p["sku"]: p for p in res.get("products", [])}
    p = prods.get("3S-100G")
    if p is None:
        print("APP FAIL: search_products khong tra 3S-100G")
        return 1
    if "serving_info" in p:
        print(f"APP FAIL: search_products TRA serving_info cho 3S-100G: {p['serving_info']}")
        return 1
    # serving_info la noi chua servings_per_unit_approx / price_per_serving_vnd_approx -> vang mat theo
    blob = str(p)
    for forbidden in ("servings_per_unit_approx", "price_per_serving_vnd_approx"):
        if forbidden in blob:
            print(f"APP FAIL: 3S-100G van lo '{forbidden}'")
            return 1
    print("APP PASS: search_products KHONG tra serving_info / servings_per_unit / price_per_serving cho 3S-100G")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
