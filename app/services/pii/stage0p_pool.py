"""I-B M4 Stage 0P — real connection-pool integration cho pinned-actor lifecycle (F-M4-0P-T8-01).

CA Technical Re-review #8 (F-M4-0P-T8-01): Correction #8 (T7-01) chi dong truong hop actor A
HOAN TAT 1 hanh dong nghiep vu THANH CONG roi actor B muon lai CUNG connection (consume-on-use xoa
row pin ngay sau thanh cong). Nhung Correction #8 tu ghi nhan 1 khoang cach con lai: neu actor A
pin THANH CONG roi request bi huy/loi TRUOC khi lam hanh dong nghiep vu nao, row pin + session_nonce
VAN CON. Toan bo evidence script trong repo (`m4_stage0p_*_test.py`) dung `asyncpg.connect()` MOI
cho MOI thao tac — moi "connection" la 1 backend_pid MOI, nen kich ban "pool tra CUNG 1 connection
vat ly cho actor B" chua bao gio duoc tai hien THAT SU. CA yeu cau tich hop 1 pool THAT
(`asyncpg.create_pool`) va chung minh bang integration test THAT rang:
  - pool checkout LUON bat dau tu trang thai unpinned (bat ke checkout truoc do ket thuc the nao);
  - pool checkin/release UNPIN ke ca khi hanh dong nghiep vu raise exception hoac task bi cancel;
  - actor B fail-closed (RAISE "chua pin actor") khi checkout lai CUNG connection vat ly ma actor A
    da bo do (khong hoan tat hanh dong nao) truoc do.

Thiet ke: `pinned_actor_session()` la async context manager DUY NHAT dung de lam viec voi pool nay —
KHONG expose pool.acquire()/release() truc tiep cho code nghiep vu, de connection KHONG THE "thoat"
khoi wrapper trong luc con pin hieu luc (yeu cau CA §T8-01, gach dau dong 3). Ben trong:
  1. acquire tu pool.
  2. SET ROLE actor_binder, goi `m4_stage0p_unpin_actor()` NGAY LAP TUC (an toan, bo qua loi "chua
     pin") TRUOC khi pin — luoi an toan chu dong: neu connection vat ly nay dang mang 1 pin BI BO
     LAI tu lan checkout truoc (vi checkin/cleanup lan do that bai vi ly do nao khac), no bi xoa
     O DAY, KHONG doi checkout tra ve boi cleanup cua nguoi dung truoc — dam bao invariant "checkout
     luon bat dau unpinned" LA THAT (khong chi la loi hua tu phia release).
  3. pin_actor that su, SET ROLE sang business_role, yield connection cho caller.
  4. finally (boc `asyncio.shield` cho phan cleanup — dam bao chay het du outer task bi cancel giua
     chung): RESET ROLE, SET ROLE actor_binder, unpin_actor (best-effort, nuot loi + log), RESET
     ROLE, roi `pool.release()`.

Con lai CHUA dong (ngoai pham vi T8-01, CA da ghi nhan la khoang cach kien truc rieng): `pin_secret`
van la 1 credential tu tao (bespoke), KHONG phai identity authority production that su — Stage 0P
hien khong co lop HTTP/JWT auth THAT de derive staff identity tu 1 authenticated application
principal (CA da neu lai yeu cau nay o Correction #6/#7 va nhac lai o Review #8). Khi Stage 0P noi
vao 1 service HTTP that, buoc pin phai lay staff_id tu principal DA XAC THUC boi lop do (vd JWT
claim), khong phai tu tham so caller tu khai nhu hien tai — day la 1 architecture gap RIENG, T8-01
khong giai quyet."""

import asyncio
import json

import asyncpg

from app.services.pii.stage0p_control import ActorNotPinnedError, pin_actor, unpin_actor


def _log(event: str, **fields) -> None:
    print("[m4-stage0p-pool] " + json.dumps({"event": event, **fields}, ensure_ascii=False, sort_keys=True))


async def create_stage0p_pool(dsn: str, *, min_size: int = 1, max_size: int = 4,
                              command_timeout: float | None = 10.0) -> asyncpg.Pool:
    """Tao 1 pool RIENG cho Stage 0P (tach biet pool chung cua app `app/db_pool.py` — Stage 0P van
    chua noi vao production, xem CLAUDE.md muc 6 'Kien truc — ranh gioi trach nhiem quan trong').
    Goi `await pool.close()` khi xong (vd cuoi integration test / shutdown)."""
    return await asyncpg.create_pool(dsn, min_size=min_size, max_size=max_size,
                                     command_timeout=command_timeout)


class _PinnedSession:
    """Trien khai async context manager cho `pinned_actor_session()` — xem module docstring cho
    thiet ke day du. Khong dung truc tiep tu ben ngoai module nay."""

    def __init__(self, pool: asyncpg.Pool, *, staff_id: int, pin_secret: str, business_role: str):
        self._pool = pool
        self._staff_id = staff_id
        self._pin_secret = pin_secret
        self._business_role = business_role
        self._conn = None

    async def __aenter__(self):
        self._conn = await self._pool.acquire()
        conn = self._conn
        await conn.execute("SET ROLE alpha3s_m4_actor_binder")
        try:
            # T8-01: luoi an toan chu dong - xoa BAT KY pin nao con sot lai tren CHINH connection
            # vat ly nay tu lan checkout truoc (vd cleanup lan do that bai/bi cancel giua chung).
            # Loi o day (vd chua tung co pin) la binh thuong, khong phai dieu kien that bai.
            await conn.execute("SELECT m4_stage0p_unpin_actor()")
        except Exception as e:  # noqa: BLE001
            _log("m4_pool_checkout_safety_unpin_noop", error_type=type(e).__name__)
        try:
            await pin_actor(conn, staff_id=self._staff_id, pin_secret=self._pin_secret)
        except Exception:
            await conn.execute("RESET ROLE")
            await self._pool.release(conn)
            self._conn = None
            raise
        await conn.execute("RESET ROLE")
        await conn.execute(f"SET ROLE {self._business_role}")
        return conn

    async def __aexit__(self, exc_type, exc, tb):
        conn = self._conn
        if conn is None:
            return False
        # T8-01: cleanup PHAI hoan tat du __aexit__ dang chay vi outer task bi cancel — shield
        # khoi 1 lan cancel THEM trong luc chinh cleanup nay dang cho await (khong shield duoc
        # cancel da nem VAO __aexit__, chi shield cac await BEN TRONG khoi bi cancel THEM lan nua).
        async def _cleanup():
            try:
                await conn.execute("RESET ROLE")
            except Exception as e:  # noqa: BLE001
                _log("m4_pool_release_reset_role_failed", error_type=type(e).__name__)
            try:
                await conn.execute("SET ROLE alpha3s_m4_actor_binder")
                await unpin_actor(conn)
            except Exception as e:  # noqa: BLE001
                _log("m4_pool_release_unpin_failed", error_type=type(e).__name__)
            finally:
                try:
                    await conn.execute("RESET ROLE")
                except Exception as e:  # noqa: BLE001
                    _log("m4_pool_release_final_reset_role_failed", error_type=type(e).__name__)
        try:
            await asyncio.shield(_cleanup())
        except asyncio.CancelledError:
            # shield bi huy tu NGOAI (task cha bi huy them lan nua) - van cho _cleanup() tu hoan
            # tat trong nen (best-effort), KHONG de connection roi ve pool ma chua kip thu unpin.
            pass
        finally:
            await self._pool.release(conn)
            self._conn = None
        return False


def pinned_actor_session(pool: asyncpg.Pool, *, staff_id: int, pin_secret: str,
                         business_role: str) -> _PinnedSession:
    """Context manager DUY NHAT de lay 1 connection tu pool VA lam viec nhu 1 actor da pin, vd:

        async with pinned_actor_session(pool, staff_id=1, pin_secret="...",
                                        business_role="alpha3s_m4_control_plane") as conn:
            await conn.fetchrow("SELECT * FROM m4_stage0p_set_capture($1,$2)", True, ref)

    Connection KHONG BAO GIO thoat khoi khoi `async with` trong luc pin con hieu luc — day la
    invariant CA yeu cau (T8-01, gach dau dong 3). Neu `pin_actor` that bai (staff sai/pin_secret
    sai/rate-limit), connection duoc tra ve pool NGAY (khong pin) va `ActorNotPinnedError` duoc
    nem cho caller — xem `_PinnedSession.__aenter__`."""
    return _PinnedSession(pool, staff_id=staff_id, pin_secret=pin_secret, business_role=business_role)


__all__ = ["create_stage0p_pool", "pinned_actor_session", "ActorNotPinnedError"]
