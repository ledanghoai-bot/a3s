"""I-B M4-S2: unit test masking + schema-bounded output (AC-M4-03/05/07 nen tang)."""

import pytest

from app.services.pii.masking import (
    find_placeholders,
    mask_history,
    mask_text,
    rehydrate_response,
)
from app.services.pii.semantic_schema import SchemaViolation, validate_semantic_output


class TestMasking:
    def test_mask_phone(self):
        r = mask_text("sđt của mình là 0912345678 nhé")
        assert "[PII_PHONE_1]" in r.masked_text
        assert "0912345678" not in r.masked_text
        assert r.mapping["[PII_PHONE_1]"] == ("phone", "0912345678")

    def test_mask_combo_khong_lot_gia_tri(self):
        text = "Người nhận Nguyễn Văn An, 0912345678, số 12 đường Lê Lợi, phường 5, quận 3"
        r = mask_text(text)
        for leak in ("0912345678", "Nguyễn Văn An", "Lê Lợi"):
            assert leak not in r.masked_text
        assert len(r.mapping) >= 3

    def test_mask_history_danh_so_lien_tuc_va_mask_assistant(self):
        hist = [
            {"role": "user", "content": "sđt 0912345678"},
            {"role": "assistant", "content": "Đã ghi nhận SĐT 0912345678 cho đơn ạ"},
            {"role": "user", "content": "đổi qua số 0356789012 nhé"},
        ]
        masked, mapping = mask_history(hist)
        joined = " ".join(m["content"] for m in masked)
        assert "0912345678" not in joined and "0356789012" not in joined
        # 3 lan phat hien phone -> 3 placeholder danh so khac nhau
        assert {"[PII_PHONE_1]", "[PII_PHONE_2]", "[PII_PHONE_3]"} <= set(mapping)

    def test_rehydrate_hop_le(self):
        r = mask_text("gọi 0912345678")
        out = rehydrate_response("Dạ em sẽ gọi [PII_PHONE_1] ạ", r.mapping)
        assert out == "Dạ em sẽ gọi 0912345678 ạ"

    @pytest.mark.parametrize("candidate", [
        "Em gọi [PII_PHONE_9] nhé",  # placeholder khong ton tai
        "Em gọi [PII_PHONE_x] nhé",  # mangle (khong dung format)
        "Em gọi [PII_XYZ] nhé",  # bia loai slot
    ])
    def test_rehydrate_fail_closed(self, candidate):
        r = mask_text("gọi 0912345678")
        assert rehydrate_response(candidate, r.mapping) is None

    def test_find_placeholders_chi_nhan_dung_format(self):
        assert find_placeholders("[PII_PHONE_1] [PII_PHONE_x] [PII_ADDRESS_12]") == [
            "[PII_PHONE_1]", "[PII_ADDRESS_12]"]


def _valid_output(**over):
    out = {
        "intent": "order.create",
        "missing_slot_types": [],
        "response_candidate": "Dạ em lên đơn ngay ạ",
        "context": {"items": [{"sku": "3S-500G", "qty": 2}]},
    }
    out.update(over)
    return out


class TestSemanticSchema:
    def test_output_hop_le(self):
        sem = validate_semantic_output(_valid_output())
        assert sem.intent == "order.create" and sem.items == [{"sku": "3S-500G", "qty": 2}]

    def test_unknown_top_key(self):
        with pytest.raises(SchemaViolation) as e:
            validate_semantic_output(_valid_output(tool_hint="create_order"))
        assert "unknown_top_keys" in e.value.reasons

    @pytest.mark.parametrize("payload,code", [
        (_valid_output(context={"items": [{"sku": "X", "qty": 1}], "customer_ref": "B"}),
         "forbidden_key:customer_ref"),  # model chon ref -> cam (invariant #2)
        ({"intent": "other", "missing_slot_types": [], "response_candidate": "",
          "context": {"items": [{"sku": "X", "qty": 1, "phone": "0912345678"}]}},
         "forbidden_key:phone"),  # PII trong tool args -> cam (invariant #3)
    ])
    def test_forbidden_keys_moi_tang(self, payload, code):
        with pytest.raises(SchemaViolation) as e:
            validate_semantic_output(payload)
        assert code in e.value.reasons

    def test_intent_ngoai_allowlist(self):
        with pytest.raises(SchemaViolation) as e:
            validate_semantic_output(_valid_output(intent="run_sql"))
        assert "intent_invalid" in e.value.reasons

    def test_missing_slot_ngoai_askable(self):
        with pytest.raises(SchemaViolation) as e:
            validate_semantic_output(_valid_output(missing_slot_types=["national_id"]))
        assert "missing_slots_invalid" in e.value.reasons

    def test_pii_tho_trong_candidate_bi_chan(self):
        with pytest.raises(SchemaViolation) as e:
            validate_semantic_output(_valid_output(
                response_candidate="Em giao tới số 12 đường Lê Lợi quận 3 SĐT 0912345678 nhé"))
        assert "pii_in_candidate" in e.value.reasons

    def test_placeholder_trong_candidate_duoc_phep(self):
        sem = validate_semantic_output(_valid_output(
            response_candidate="Em sẽ giao tới [PII_ADDRESS_1], gọi [PII_PHONE_1] trước ạ"))
        assert "[PII_ADDRESS_1]" in sem.response_candidate

    @pytest.mark.parametrize("items", [
        [{"sku": "X", "qty": 0}],
        [{"sku": "X", "qty": -2}],
        [{"sku": "X", "qty": True}],
        [{"sku": "", "qty": 1}],
        [{"sku": "X"}],
        "khong phai list",
    ])
    def test_items_khong_hop_le(self, items):
        with pytest.raises(SchemaViolation) as e:
            validate_semantic_output(_valid_output(context={"items": items}))
        assert "items_invalid" in e.value.reasons or "context_invalid" in e.value.reasons

    def test_khong_phai_dict(self):
        with pytest.raises(SchemaViolation):
            validate_semantic_output("intent: order.create")
