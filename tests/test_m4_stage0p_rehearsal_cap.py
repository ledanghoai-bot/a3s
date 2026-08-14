"""I-B M4 — regression cho F-A13-01 / F-A13-02 (Amendment 13 abort).

Bối cảnh: manifest v3 có 315 conversation, vượt **Cap A = 260** — một biện pháp bảo vệ quyền riêng
tư đã được duyệt (F-M4-0P-03). Trước correction này:

  - runner cố ý không gọi `select_sample()` (fence F-01) nên Cap A không được enforce ở tầng Python;
  - dry-run chỉ kiểm sàn dưới (`>=200`), không kiểm trần trên → trả `dry_run_ready` (false green);
  - chốt duy nhất chặn được là DB `CHECK (selected_count <= 260)`, và nó chỉ nổ tại INSERT
    `m4_selection_batches` — tức GIỮA lifecycle, sau khi đã seed 315 hàng và đã bật capture.

Các test dưới đây chạy **không cần DB/Redis**: guard mới nằm TRƯỚC mọi `asyncpg.connect`, nên có thể
kiểm bằng cách chặn chính `connect` lại và khẳng định nó không bao giờ được gọi.
"""
import asyncio
import importlib.util
import os
import sys
from types import SimpleNamespace

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# `scripts/` KHONG phai package (khong co __init__.py) — nap module theo duong dan thay vi them
# __init__.py, de khong doi cach import cua bat ky cho nao khac dang dung thu muc nay.
# Runner import anh em cung thu muc (`from m4_dsn_utils import ...`), dieu nay dung khi chay
# `python scripts/m4_stage0p_rehearsal_runner.py` vi Python tu them thu muc script vao sys.path.
# Nap qua importlib thi khong co co che do, nen them tuong minh o day.
sys.path.insert(0, os.path.join(ROOT, "scripts"))
_spec = importlib.util.spec_from_file_location(
    "m4_stage0p_rehearsal_runner_for_test",
    os.path.join(ROOT, "scripts", "m4_stage0p_rehearsal_runner.py"))
runner = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(runner)


def _manifest(n: int) -> list[dict]:
    """Chỉ cần độ dài — guard Cap A đếm số conversation, không đọc nội dung."""
    return [{"conversation_key": f"K{i:04d}", "expect_gate": True} for i in range(n)]


# --------------------------------------------------------------------------------------------
# F-A13-02 — hàm kiểm cap, dùng chung cho cả dry-run lẫn execute
# --------------------------------------------------------------------------------------------

def test_cap_a_dung_hang_so_tu_stage0p_sampling():
    """Một nguồn sự thật duy nhất: runner phải đọc chính `MAX_CONVERSATIONS` của module định nghĩa
    Cap A, không hard-code lại số 260 (nếu hard-code, đổi cap ở một nơi sẽ lệch nơi kia)."""
    from app.services.pii.stage0p_sampling import MAX_CONVERSATIONS as canonical
    assert runner.MAX_CONVERSATIONS is canonical
    assert canonical == 260


@pytest.mark.parametrize("n", [0, 1, 200, 225, 259, 260])
def test_duoi_hoac_bang_cap_thi_khong_bao_van_de(n):
    """225 (manifest v2) và 260 (đúng biên) đều phải đạt — không được chặn nhầm."""
    assert runner._cap_a_problem(_manifest(n)) is None


@pytest.mark.parametrize("n", [261, 289, 315, 1000])
def test_vuot_cap_thi_bao_van_de(n):
    problem = runner._cap_a_problem(_manifest(n))
    assert problem is not None
    assert str(n) in problem
    assert "260" in problem


def test_bien_260_va_261_la_ranh_gioi_that():
    """Kiểm đúng cặp biên chứ không tin vào một phía."""
    assert runner._cap_a_problem(_manifest(260)) is None
    assert runner._cap_a_problem(_manifest(261)) is not None


def test_315_la_dung_con_so_da_gay_abort_amendment_13():
    """Regression trực tiếp cho sự cố thật: manifest v3 = 315."""
    problem = runner._cap_a_problem(_manifest(315))
    assert problem is not None
    assert "315" in problem


def test_thong_bao_neu_ro_day_la_bien_phap_bao_ve_khong_phai_gioi_han_ky_thuat():
    """Thông báo phải ngăn người vận hành hiểu nhầm rằng cứ nâng số là xong — Cap A là quyết định
    governance, đổi nó cần PO decision riêng."""
    problem = runner._cap_a_problem(_manifest(315))
    assert "bao ve quyen rieng tu" in problem
    assert "F-M4-0P-03" in problem


def test_cap_thay_doi_thi_guard_tu_dong_theo(monkeypatch):
    """Nếu Cap A được đổi (chỉ qua PO decision), guard phải theo ngay — chứng minh không có 260 nào
    bị chôn cứng trong logic."""
    monkeypatch.setattr(runner, "MAX_CONVERSATIONS", 50)
    assert runner._cap_a_problem(_manifest(50)) is None
    problem = runner._cap_a_problem(_manifest(51))
    assert problem is not None
    assert "50" in problem


# --------------------------------------------------------------------------------------------
# F-A13-01 — execute phải fail TRƯỚC MỌI write
# --------------------------------------------------------------------------------------------

def test_execute_vuot_cap_thi_abort_TRUOC_khi_mo_bat_ky_ket_noi_nao(monkeypatch):
    """Điểm mấu chốt của F-A13-01. Ở Amendment 13, runner đã ghi 315 hàng synthetic và bật capture
    RỒI mới bị DB chặn. Sau correction, `_run_execute` phải thoát trước cả `asyncpg.connect` — nên
    ở đây ta thay `connect` bằng một hàm nổ ngay nếu bị gọi."""
    called = []

    async def _must_not_connect(*a, **kw):
        called.append(a)
        raise AssertionError("asyncpg.connect() bi goi - guard Cap A da KHONG chan truoc write")

    monkeypatch.setattr(runner.asyncpg, "connect", _must_not_connect)

    args = SimpleNamespace(operator_staff_id=4, reviewer_staff_id=5,
                           approval_ref="test-ref", manifest="x", dry_run=False)

    with pytest.raises(SystemExit) as exc:
        asyncio.run(runner._run_execute(args, _manifest(315)))

    assert "F-A13-01" in str(exc.value)
    assert "315" in str(exc.value)
    assert called == [], "khong duoc mo ket noi DB nao truoc khi abort"


def test_execute_khong_can_PIN_de_abort_vi_cap(monkeypatch):
    """Guard đặt trước `_require_env` nên thiếu PIN cũng không che mất lỗi cap: người vận hành nhận
    đúng nguyên nhân thật (manifest sai) thay vì một lỗi thiếu biến môi trường gây hiểu lầm."""
    monkeypatch.delenv("STAGE0P_REHEARSAL_OPERATOR_PIN", raising=False)
    monkeypatch.delenv("STAGE0P_REHEARSAL_REVIEWER_PIN", raising=False)

    async def _must_not_connect(*a, **kw):
        raise AssertionError("khong duoc ket noi DB")

    monkeypatch.setattr(runner.asyncpg, "connect", _must_not_connect)
    args = SimpleNamespace(operator_staff_id=4, reviewer_staff_id=5,
                           approval_ref="test-ref", manifest="x", dry_run=False)

    with pytest.raises(SystemExit) as exc:
        asyncio.run(runner._run_execute(args, _manifest(315)))
    assert "CAP A PRECHECK FAIL" in str(exc.value)


def test_manifest_dung_kich_thuoc_thi_guard_khong_chan(monkeypatch):
    """Đối chứng âm: guard không được chặn manifest hợp lệ. 225 (v2) phải đi qua guard và tiến tới
    bước kế tiếp — ở đây bước kế tiếp là `_require_env`, nên ta khẳng định lỗi nhận được là lỗi
    THIẾU PIN chứ không phải lỗi cap."""
    monkeypatch.delenv("STAGE0P_REHEARSAL_OPERATOR_PIN", raising=False)

    async def _must_not_connect(*a, **kw):
        raise AssertionError("khong duoc ket noi DB")

    monkeypatch.setattr(runner.asyncpg, "connect", _must_not_connect)
    args = SimpleNamespace(operator_staff_id=4, reviewer_staff_id=5,
                           approval_ref="test-ref", manifest="x", dry_run=False)

    with pytest.raises(SystemExit) as exc:
        asyncio.run(runner._run_execute(args, _manifest(225)))
    msg = str(exc.value)
    assert "CAP A" not in msg and "F-A13-01" not in msg
    assert "STAGE0P_REHEARSAL_OPERATOR_PIN" in msg
