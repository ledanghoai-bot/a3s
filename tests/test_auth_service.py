"""Test don vi cho hash/verify mat khau trong auth_service.py (issue #9,
Bat 2) - la phan bao mat quan trong nhat cua he thong dang nhap (Bat 4, #8),
dang test cao nhat dai dien cho file nay.
"""

from app.services.auth_service import _hash_password, _verify_password


class TestHashPassword:
    def test_tu_sinh_salt_neu_khong_truyen(self):
        hash1, salt1 = _hash_password("MatKhau123")
        assert hash1
        assert salt1
        assert len(salt1) == 32  # secrets.token_hex(16) -> 32 ky tu hex

    def test_cung_password_cung_salt_ra_cung_hash(self):
        """Tinh xac dinh - bat buoc de verify hoat dong dung."""
        hash1, salt1 = _hash_password("MatKhau123")
        hash2, salt2 = _hash_password("MatKhau123", salt=salt1)
        assert hash1 == hash2
        assert salt1 == salt2

    def test_cung_password_khac_salt_ra_khac_hash(self):
        """Moi user co salt rieng - 2 user cung mat khau se co hash khac nhau,
        chong ran table attack."""
        hash1, salt1 = _hash_password("MatKhau123")
        hash2, salt2 = _hash_password("MatKhau123")  # salt tu sinh, se khac lan truoc
        assert salt1 != salt2
        assert hash1 != hash2

    def test_khac_password_ra_khac_hash(self):
        salt = "a" * 32
        hash1, _ = _hash_password("MatKhau123", salt=salt)
        hash2, _ = _hash_password("MatKhauKhac456", salt=salt)
        assert hash1 != hash2


class TestVerifyPassword:
    def test_dung_password_verify_thanh_cong(self):
        password_hash, salt = _hash_password("Ho123456@")
        assert _verify_password("Ho123456@", password_hash, salt) is True

    def test_sai_password_verify_that_bai(self):
        password_hash, salt = _hash_password("Ho123456@")
        assert _verify_password("SaiMatKhau", password_hash, salt) is False

    def test_password_dung_nhung_sai_salt_that_bai(self):
        """Dam bao salt thuc su duoc dung trong tinh toan, khong bi bo qua."""
        password_hash, salt = _hash_password("Ho123456@")
        khac_salt = "b" * 32
        assert _verify_password("Ho123456@", password_hash, khac_salt) is False

    def test_phan_biet_hoa_thuong(self):
        password_hash, salt = _hash_password("MatKhau123")
        assert _verify_password("matkhau123", password_hash, salt) is False
