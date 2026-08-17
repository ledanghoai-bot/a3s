"""Truy van mot gia tri, va DUNG HAN neu ket qua rong.
Ly do: harness truoc do dung char(10) (cu phap SQL Server, khong phai Postgres) nen truy van loi
va tra ve rong; hai chuoi rong so sanh voi nhau ra "bang" => PASS GIA. Bat gia tri rong thanh loi
la cach duy nhat de phep do khong the xanh vi khong co gi de do."""
import asyncio, asyncpg, os, sys
async def m():
    c = await asyncpg.connect(os.environ["DATABASE_URL"])
    try:
        v = await c.fetchval(sys.argv[1])
    except Exception as e:
        print(f"QUERY_ERROR: {type(e).__name__}: {e}", file=sys.stderr); sys.exit(2)
    if v is None or v == "":
        print("EMPTY_RESULT", file=sys.stderr); sys.exit(3)
    print(v)
asyncio.run(m())
