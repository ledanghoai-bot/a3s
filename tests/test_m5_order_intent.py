"""M5 order-intent fingerprints + transitions (CA Directive 223 + Amendment 224). Logic THUAN."""
from app.services.command import order_intent as oi


def test_addr_fp_stable_and_distinct():
    a = oi.verified_address_fingerprint("VN-ADMIN-2025-07-v2", "66", "24169", "12 Nguyen Hue")
    a2 = oi.verified_address_fingerprint("VN-ADMIN-2025-07-v2", "66", "24169", "12 Nguyen Hue")
    assert a == a2  # tat dinh
    # cung phuong, KHAC so nha/duong -> KHAC fingerprint (khong collide trong cung ward)
    b = oi.verified_address_fingerprint("VN-ADMIN-2025-07-v2", "66", "24169", "99 Tran Phu")
    assert a != b
    # KHAC ward -> khac
    c = oi.verified_address_fingerprint("VN-ADMIN-2025-07-v2", "66", "24121", "12 Nguyen Hue")
    assert a != c
    # KHAC dataset -> khac
    d = oi.verified_address_fingerprint("VN-ADMIN-2099-01-v1", "66", "24169", "12 Nguyen Hue")
    assert a != d


def test_addr_fp_equivalent_after_normalize():
    # Cung dia chi qua bien the chinh ta/hoa-thuong/space (sau khi verify ra cung code) -> cung fp.
    a = oi.verified_address_fingerprint("v2", "66", "24169", "12 Đường Nguyễn Huệ")
    b = oi.verified_address_fingerprint("v2", "66", "24169", "  12  duong nguyen hue ")
    assert a == b


def test_order_fp_stable_and_distinct():
    fp = oi.order_fingerprint(sku="SP1", quantity=1, customer_name="Nguyen Van A",
                              phone="0912345678", address_fp="AF")
    assert fp == oi.order_fingerprint(sku="SP1", quantity=1, customer_name="Nguyen Van A",
                                      phone="09 1234 5678", address_fp="AF")  # phone chi so
    assert fp != oi.order_fingerprint(sku="SP1", quantity=2, customer_name="Nguyen Van A",
                                      phone="0912345678", address_fp="AF")  # qty khac
    assert fp != oi.order_fingerprint(sku="SP2", quantity=1, customer_name="Nguyen Van A",
                                      phone="0912345678", address_fp="AF")  # sku khac
    assert fp != oi.order_fingerprint(sku="SP1", quantity=1, customer_name="Nguyen Van A",
                                      phone="0912345678", address_fp="AF2")  # dia chi khac


def test_transitions():
    assert oi.can_transition("READY_TO_COMMIT", "COMMITTING")
    assert oi.can_transition("COMMITTING", "COMMITTED")
    assert oi.can_transition("NEEDS_CLARIFICATION", "ADDRESS_CHECK")
    # cam: COLLECTING -> COMMITTED truc tiep
    assert not oi.can_transition("COLLECTING", "COMMITTED")
    # cam: NEEDS_CLARIFICATION -> COMMITTING (phai qua ADDRESS_CHECK)
    assert not oi.can_transition("NEEDS_CLARIFICATION", "COMMITTING")
    # terminal khong reopen
    for t in oi.TERMINAL_STATES:
        assert oi.ALLOWED_TRANSITIONS.get(t, frozenset()) == frozenset()


def test_state_sets():
    assert "COMMITTED" in oi.TERMINAL_STATES and "COMMITTED" not in oi.OPEN_STATES
    assert "READY_TO_COMMIT" in oi.OPEN_STATES
