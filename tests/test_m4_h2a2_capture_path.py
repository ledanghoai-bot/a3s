"""I-B M4 H2-A-2 — test cho phan NOI dual-tag vao capture path.

BAN NAY LA BAN VIET LAI. Ban dau Dev tu "tai tao" doan client trong test roi assert tren ban tai
tao do — nen khi Dev co tinh doi client that sang `.get("signature_asym_b64", "")`, ca 11 test VAN
XANH. Test chi kiem chinh no, khong gac duoc hoi quy. Do dung la lop loi "xanh vi khong co gi de
kiem" da lap lai nhieu lan trong du an nay.

Ban nay goi `request_signature()` THAT qua mot signing service GIA LAP tren unix socket that. Phep
thu pha hoai (doi client sang `.get`) PHAI lam test do.

Pham vi: hop dong service <-> client + tinh fail-closed. Duong day du (service that + DB + verifier)
nam o kich ban sandbox rieng.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import socket
import tempfile

import pytest

from app.services.pii.signing_backend import (
    SIGNATURE_ALGORITHM,
    LocalDevBackend,
    verify_signature,
)
from app.services.pii.stage0p_signing_client import (
    SigningServiceError,
    request_signature,
)

_RAW = "noi dung canary"


@pytest.fixture()
def backend(monkeypatch: pytest.MonkeyPatch) -> LocalDevBackend:
    monkeypatch.setenv("M4_ALLOW_LOCALDEV_SIGNING", "1")
    return LocalDevBackend(app_env="test")


def _transcript(sample_id: str) -> bytes:
    return json.dumps({"v": 1, "sample_id": sample_id}, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


class _SignerGiaLap:
    """Signing service gia lap: dung giao thuc 4-byte length prefix + JSON nhu ban that.

    `bo_truong` cho phep mo phong mot signer CU (chua co H2-A-2) de kiem client co fail-closed
    khong. Day la diem mau chot ma ban test truoc bo sot.
    """

    def __init__(self, backend: LocalDevBackend, *, bo_truong: str | None = None) -> None:
        self.backend, self.bo_truong = backend, bo_truong
        self.so_request = 0
        self._server: asyncio.AbstractServer | None = None
        self.path = os.path.join(tempfile.mkdtemp(prefix="h2a2-"), "signing.sock")

    async def __aenter__(self) -> _SignerGiaLap:
        self._server = await asyncio.start_unix_server(self._xu_ly, path=self.path)
        return self

    async def __aexit__(self, *exc) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    async def _xu_ly(self, reader: asyncio.StreamReader,
                     writer: asyncio.StreamWriter) -> None:
        self.so_request += 1
        n = int.from_bytes(await reader.readexactly(4), "big")
        req = json.loads((await reader.readexactly(n)).decode("utf-8"))

        transcript = _transcript(req["sample_id"])
        resp = {
            "ok": True,
            "ciphertext_b64": base64.b64encode(b"ciphertext").decode("ascii"),
            "transcript_b64": base64.b64encode(transcript).decode("ascii"),
            "signature_b64": base64.b64encode(b"\x01" * 32).decode("ascii"),
            "key_version": "sample-transcript-hmac-v1",
            "canonical_len": len(_RAW),
            "truncated": False,
            "canonical_digest_hex": "ab" * 32,
            "signature_asym_b64": base64.b64encode(
                self.backend.sign(transcript)).decode("ascii"),
            "sig_alg": SIGNATURE_ALGORITHM,
            "sig_key_id": self.backend.key_id(),
            "sig_key_ver": self.backend.key_version(),
        }
        if self.bo_truong:
            resp.pop(self.bo_truong, None)
        payload = json.dumps(resp).encode("utf-8")
        writer.write(len(payload).to_bytes(4, "big") + payload)
        await writer.drain()
        writer.close()


async def _goi(signer: _SignerGiaLap, sample_id: str = "22222222-2222-2222-2222-222222222222"):
    """Goi HAM THAT `request_signature` — day la diem khac biet so voi ban test cu."""
    return await request_signature(
        signer.path, batch_id="11111111-1111-1111-1111-111111111111",
        conversation_id=1, message_id=2, sample_id=sample_id, raw_content=_RAW,
        customer_ref="c1", conversation_ref="1", purpose_code="P12_PII_DETECTOR_EVAL",
        txid=99, signing_authorization="tok", timeout=5.0)


def _chay(coro):
    return asyncio.run(coro)


@pytest.mark.skipif(not hasattr(socket, "AF_UNIX"), reason="can unix socket")
def test_client_that_nhan_du_bon_truong_asym(backend: LocalDevBackend) -> None:
    async def m():
        async with _SignerGiaLap(backend) as s:
            kq = await _goi(s)
            assert s.so_request == 1
            return kq
    kq = _chay(m())
    assert kq.sig_alg == "Ed25519"
    assert kq.sig_key_id == backend.key_id()
    assert kq.sig_key_ver == backend.key_version()
    assert len(kq.signature_asym) == 64


@pytest.mark.skipif(not hasattr(socket, "AF_UNIX"), reason="can unix socket")
def test_the_asym_ky_tren_DUNG_transcript_client_nhan_duoc(backend: LocalDevBackend) -> None:
    """Hai the phai noi ve CUNG noi dung: verify chu ky asym tren chinh `kq.transcript`."""
    async def m():
        async with _SignerGiaLap(backend) as s:
            return await _goi(s)
    kq = _chay(m())
    assert verify_signature(backend.public_key_raw(kq.sig_key_ver), kq.transcript,
                            kq.signature_asym) is True
    assert verify_signature(backend.public_key_raw(kq.sig_key_ver), b'{"sample_id":"khac"}',
                            kq.signature_asym) is False


@pytest.mark.skipif(not hasattr(socket, "AF_UNIX"), reason="can unix socket")
@pytest.mark.parametrize("thieu", ["signature_asym_b64", "sig_alg", "sig_key_id", "sig_key_ver"])
def test_signer_CU_thieu_truong_asym_lam_client_HONG(backend: LocalDevBackend,
                                                     thieu: str) -> None:
    """Diem mau chot: mot signer chua co H2-A-2 PHAI lam collector hong, khong duoc di tiep.

    Neu client dung `.get(...)`, sample van duoc ghi nhung thieu bang chung quy trach nhiem — sai
    lech im lang ma H2 sinh ra de loai bo. Test nay goi client THAT nen no do duoc thay doi do.
    """
    async def m():
        async with _SignerGiaLap(backend, bo_truong=thieu) as s:
            return await _goi(s)
    with pytest.raises((KeyError, SigningServiceError, TypeError)):
        _chay(m())


@pytest.mark.skipif(not hasattr(socket, "AF_UNIX"), reason="can unix socket")
def test_rotation_mau_ky_truoc_van_verify_duoc(backend: LocalDevBackend) -> None:
    async def m():
        async with _SignerGiaLap(backend) as s:
            cu = await _goi(s, "22222222-2222-2222-2222-222222222222")
            backend.rotate()
            moi = await _goi(s, "33333333-3333-3333-3333-333333333333")
            return cu, moi
    cu, moi = _chay(m())
    assert cu.sig_key_ver != moi.sig_key_ver
    assert verify_signature(backend.public_key_raw(cu.sig_key_ver), cu.transcript,
                            cu.signature_asym) is True
    assert verify_signature(backend.public_key_raw(cu.sig_key_ver), moi.transcript,
                            moi.signature_asym) is False


# ---------------------------------------------------------------------------
# Fail-closed o phia service: khong duong lui ve chi-HMAC
# ---------------------------------------------------------------------------

def test_service_lay_backend_qua_factory_fail_closed() -> None:
    import inspect

    from app.services.pii import stage0p_signing_service as svc

    src = inspect.getsource(svc._signing_backend)
    assert "get_signing_backend" in src
    assert "except" not in src, "khong duoc nuot loi cau hinh backend"


def test_service_luon_dat_bon_truong_asym_vao_response() -> None:
    import inspect

    from app.services.pii import stage0p_signing_service as svc

    src = inspect.getsource(svc)
    for truong in ("signature_asym_b64", "sig_alg", "sig_key_id", "sig_key_ver"):
        assert f'"{truong}"' in src


def test_collector_luu_chu_ky_bang_ham_migration_044() -> None:
    """Collector phai GHI the asym xuong DB — khong chi nhan roi bo di."""
    import inspect

    from app.services.pii import stage0p_sampling as sp

    src = inspect.getsource(sp)
    assert "m4_stage0p_record_transcript_signature" in src
    assert "signed.signature_asym" in src


# ---------------------------------------------------------------------------
# F-H2A2-01: fail-closed nam o SIGNER, khong o parse-time cua Compose
# ---------------------------------------------------------------------------

def test_signer_tu_choi_khoi_dong_khi_backend_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """Deploy dormant phai parse duoc khi `M4_SIGNING_BACKEND` unset (xem evidence Compose), nhung
    SIGNER thi khong duoc chay. Test nay khoa nua sau cua doi do."""
    from app.services.pii import stage0p_signing_service as svc
    from app.services.pii.signing_backend import SigningBackendMisconfigured

    monkeypatch.setattr(svc, "_BACKEND", None)
    monkeypatch.delenv("M4_SIGNING_BACKEND", raising=False)
    with pytest.raises(SigningBackendMisconfigured, match="M4_SIGNING_BACKEND"):
        svc._signing_backend()


def test_signer_tu_choi_khoi_dong_khi_backend_rong_hoac_la(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Chuoi rong (dung gia tri Compose truyen qua khi chua chon) va gia tri la deu bi tu choi."""
    from app.services.pii import stage0p_signing_service as svc
    from app.services.pii.signing_backend import SigningBackendMisconfigured

    for gia_tri in ("", "hmac", "localdev-that"):
        monkeypatch.setattr(svc, "_BACKEND", None)
        monkeypatch.setenv("M4_SIGNING_BACKEND", gia_tri)
        with pytest.raises(SigningBackendMisconfigured):
            svc._signing_backend()
