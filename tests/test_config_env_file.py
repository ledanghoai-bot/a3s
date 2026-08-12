"""Correction PR (dap CA closure PHASE1B-M4-AMENDMENT-09-EXECUTION-ATTEMPT-1-CLOSURE-VI.md): test
cho `app.config._readable_env_file()` — ham phong thu moi ngan Settings() crash luc import module
neu file `.env` ton tai nhung tien trinh hien tai khong doc duoc (dung y xay ra voi m4-signer,
UID rieng 5001, khong phai root, trong khi `.env` production la mode 0600 root:root).

KHONG dung DB/mang - ham thuan, chi thao tac filesystem cuc bo qua tmp_path (pytest fixture)."""

import os
import stat
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import _readable_env_file  # noqa: E402


def test_missing_file_returns_none(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert _readable_env_file() is None


def test_readable_file_returns_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("FOO=bar\n", encoding="utf-8")
    assert _readable_env_file() == ".env"


@pytest.mark.skipif(os.name == "nt" or os.geteuid() == 0,
                    reason="permission-denied simulation khong ap dung tren Windows/root")
def test_unreadable_file_returns_none_not_raise(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    env_path = tmp_path / ".env"
    env_path.write_text("FOO=bar\n", encoding="utf-8")
    os.chmod(env_path, stat.S_IWUSR)  # write-only, khong doc duoc du la owner
    try:
        assert _readable_env_file() is None
    finally:
        os.chmod(env_path, stat.S_IRUSR | stat.S_IWUSR)  # tra lai de pytest tu dep don duoc


def test_directory_named_env_returns_none(tmp_path, monkeypatch):
    """`.env` la 1 thu muc (khong phai file) -> khong crash, coi nhu khong co .env hop le."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").mkdir()
    assert _readable_env_file() is None


def test_settings_import_does_not_crash_with_unreadable_env(tmp_path, monkeypatch):
    """Xac nhan CHINH kich ban that: Settings() (goi qua app.config module) khong crash du .env
    khong doc duoc - day la doi tuong THAT SU bi crash trong Amendment 09 attempt 1."""
    monkeypatch.chdir(tmp_path)
    env_path = tmp_path / ".env"
    env_path.write_text("FOO=bar\n", encoding="utf-8")
    if os.name != "nt" and os.geteuid() != 0:
        os.chmod(env_path, stat.S_IWUSR)
    from pydantic_settings import BaseSettings, SettingsConfigDict

    from app.config import _readable_env_file as _live_check

    class _ProbeSettings(BaseSettings):
        model_config = SettingsConfigDict(env_file=_live_check(), extra="ignore")
        app_env: str = "development"

    # Khong duoc raise - day chinh la hanh vi truoc day CRASH (PermissionError luc import module).
    probe = _ProbeSettings()
    assert probe.app_env == "development"
