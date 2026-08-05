"""I-B M4-S0 — taxonomy: slot type, confidence, risk class, reason/failure code.

Theo A3S-PHASE1B-M4-SPEC-001 §6 (do rieng phone/name/address/sensitive) va
DEV-DIRECTIVE-001 §4/§9 (confidence/failure taxonomy). Moi enum la str de
serialize thang vao metrics JSON (khong bao gio chua plaintext PII).
"""

from enum import Enum

# Ban detector — ghi kem moi ket qua de trace evidence/shadow report ve dung code.
DETECTOR_VERSION = "m4d-0.1.0"


class SlotType(str, Enum):
    PHONE = "phone"
    NAME = "name"
    ADDRESS = "address"
    NATIONAL_ID = "national_id"  # CMND/CCCD — xep D2 (high-risk identity)
    BANK_ACCOUNT = "bank_account"  # STK — xep D2 (high-risk finance)


class Confidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

    @property
    def score(self) -> float:
        return {"high": 0.9, "medium": 0.7, "low": 0.4}[self.value]


class RiskClass(str, Enum):
    """D0 = khong PII; D1 = PII co ban (phone/name/address);
    D2 = sensitive/high-risk (suc khoe, giay to tuy than, tai chinh) —
    theo spec §5.6: D2 default deny vendor path khi enforcement."""

    D0 = "D0"
    D1 = "D1"
    D2 = "D2"


class ReasonCode(str, Enum):
    """Vi sao detector ket luan co slot — dung cho failure taxonomy/bao cao gate."""

    # phone
    PHONE_VALID_VN_MOBILE = "phone_valid_vn_mobile"  # dung prefix di dong VN 10 so
    PHONE_VALID_VN_LANDLINE = "phone_valid_vn_landline"  # 02x co dinh 10-11 so
    PHONE_DIGITRUN_WITH_CUE = "phone_digitrun_with_cue"  # 9-11 so + tu khoa lien he
    # name
    NAME_CUE_SURNAME = "name_cue_surname"  # cue ("ten la"...) + ho VN pho bien
    NAME_CUE_CAPITALIZED = "name_cue_capitalized"  # cue + chuoi viet hoa
    NAME_CUE_TOKENS = "name_cue_tokens"  # cue + token thuong (khong dau/thuong)
    NAME_SURNAME_SEQUENCE = "name_surname_sequence"  # khong cue: Ho + ten viet hoa
    # address
    ADDR_MULTI_COMPONENT = "addr_multi_component"  # >=2 thanh phan dia chi gan nhau
    ADDR_NUM_STREET = "addr_num_street"  # so nha + duong/pho don le
    # high-risk slots
    NID_CUE_DIGITS = "nid_cue_digits"  # cmnd/cccd + day so 9/12
    NID_12_DIGITS = "nid_12_digits"  # day 12 so (dinh dang CCCD) khong cue
    BANK_CUE_DIGITS = "bank_cue_digits"  # stk/tai khoan + day so


class SensitiveCategory(str, Enum):
    """Phan loai disclosure nhay cam (D2) — CHI la classification, khong phai slot."""

    HEALTH = "health"  # benh ly, mang thai, thuoc dang dung...
    IDENTITY_DOC = "identity_doc"  # nhac toi CMND/CCCD/ho chieu
    FINANCE = "finance"  # STK, the tin dung


class FailureCode(str, Enum):
    """Loi van hanh cua detector (KHAC voi false negative — do qua eval corpus)."""

    DETECTOR_EXCEPTION = "detector_exception"  # exception bi shadow_scan nuot
    EMPTY_INPUT = "empty_input"
