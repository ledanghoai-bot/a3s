"""I-B M4 Stage 0P: unit test evaluation methodology (F-M4-0P-05A, CLOSED AT DESIGN LEVEL).

Thuan logic, khong DB. Trong tam: chung minh exact-span bat duoc case CA neu ra ma count-only
bo lot (detector bat trung 1 vi tri 2 lan, bo sot vi tri con lai).
"""

from app.services.pii.stage0p_evaluation import (
    aggregate_micro,
    corpus_manifest_hash,
    count_only_match,
    exact_span_match,
    label_set_hash,
    match_by_slot_type,
    overlap_match,
    report_hash,
    result_hash,
    validate_spans,
)


def _span(slot_type, start, end, confidence="high", reason="test"):
    return {"slot_type": slot_type, "start": start, "end": end,
            "confidence": confidence, "reason": reason}


class TestExactSpanVsCountOnly:
    """Case CA Review #3 neu dung: tin nhan co 2 phone, detector bat trung 1 vi tri 2 lan,
    bo sot vi tri con lai. Count-only bao TP gia; exact-span phai bao dung FN=1+FP=1."""

    def test_count_only_bao_TP_gia(self):
        gt = [_span("phone", 0, 10), _span("phone", 20, 30)]
        pred = [_span("phone", 0, 10), _span("phone", 0, 10)]  # bat trung vi tri #1 x2
        result = count_only_match(gt, pred)
        assert result == {"tp": 2, "fn": 0, "fp": 0}  # SAI — day chinh la van de CA neu

    def test_exact_span_bao_dung_fn_fp(self):
        gt = [_span("phone", 0, 10), _span("phone", 20, 30)]
        pred = [_span("phone", 0, 10), _span("phone", 0, 10)]
        result = exact_span_match(gt, pred)
        assert result == {"tp": 1, "fn": 1, "fp": 1}  # DUNG — #1 khop, #2 bo sot, du bat trung

    def test_exact_span_khop_hoan_hao(self):
        gt = [_span("phone", 0, 10), _span("name", 20, 30)]
        pred = [_span("phone", 0, 10), _span("name", 20, 30)]
        assert exact_span_match(gt, pred) == {"tp": 2, "fn": 0, "fp": 0}

    def test_exact_span_lech_1_ky_tu_khong_khop(self):
        # detector bat gan dung nhung lech offset -> KHONG duoc tinh la TP o gate chinh
        gt = [_span("phone", 0, 10)]
        pred = [_span("phone", 0, 11)]  # end lech 1
        assert exact_span_match(gt, pred) == {"tp": 0, "fn": 1, "fp": 1}

    def test_khac_slot_type_khong_khop_du_cung_offset(self):
        gt = [_span("phone", 0, 10)]
        pred = [_span("name", 0, 10)]
        assert exact_span_match(gt, pred) == {"tp": 0, "fn": 1, "fp": 1}


class TestOverlapMatch:
    def test_iou_du_nguong_khop(self):
        gt = [_span("address", 0, 20)]
        pred = [_span("address", 0, 18)]  # IoU = 18/20 = 0.9
        assert overlap_match(gt, pred, threshold=0.8) == {"tp": 1, "fn": 0, "fp": 0}

    def test_iou_duoi_nguong_khong_khop(self):
        gt = [_span("address", 0, 20)]
        pred = [_span("address", 0, 5)]  # IoU = 5/20 = 0.25
        assert overlap_match(gt, pred, threshold=0.8) == {"tp": 0, "fn": 1, "fp": 1}

    def test_case_ca_neu_van_sai_o_overlap_neu_nguong_thap(self):
        # minh hoa vi sao overlap/IoU CHI la metric phu, khong phai gate: nguong thap se
        # van cho phep bat-trung-vi-tri duoc tinh TP mot phan (IoU voi chinh no = 1.0)
        gt = [_span("phone", 0, 10), _span("phone", 20, 30)]
        pred = [_span("phone", 0, 10), _span("phone", 0, 10)]
        result = overlap_match(gt, pred, threshold=0.5)
        assert result["tp"] == 1  # chi khop duoc 1 (greedy, khong tai su dung prediction)


class TestValidateSpans:
    def test_hop_le(self):
        assert validate_spans([_span("phone", 0, 10), _span("name", 15, 20)], 20) == []

    def test_offset_ngoai_bounds(self):
        errors = validate_spans([_span("phone", 0, 25)], 20)
        assert len(errors) == 1 and "offset_out_of_bounds" in errors[0]

    def test_start_ge_end_ngoai_bounds(self):
        errors = validate_spans([_span("phone", 10, 10)], 20)
        assert len(errors) == 1

    def test_overlap_trong_cung_tap(self):
        errors = validate_spans([_span("phone", 0, 10), _span("name", 5, 15)], 20)
        assert any("overlap" in e for e in errors)

    def test_khong_chong_lan_lien_ke_hop_le(self):
        # end cua span truoc = start cua span sau -> KHONG tinh la chong lan
        assert validate_spans([_span("phone", 0, 10), _span("name", 10, 20)], 20) == []


class TestAggregateMicro:
    def test_gop_nhieu_row(self):
        per_row = [
            {"phone": {"tp": 1, "fn": 0, "fp": 0}},
            {"phone": {"tp": 0, "fn": 1, "fp": 1}},
            {"name": {"tp": 2, "fn": 0, "fp": 0}},
        ]
        agg = aggregate_micro(per_row)
        assert agg["phone"]["tp"] == 1 and agg["phone"]["fn"] == 1 and agg["phone"]["fp"] == 1
        assert agg["phone"]["recall"] == 0.5
        assert agg["name"]["recall"] == 1.0

    def test_denom_0_tra_none(self):
        agg = aggregate_micro([{"phone": {"tp": 0, "fn": 0, "fp": 0}}])
        assert agg["phone"]["recall"] is None and agg["phone"]["precision"] is None


class TestMatchBySlotType:
    def test_tach_theo_slot_type(self):
        gt = [_span("phone", 0, 10), _span("name", 20, 30)]
        pred = [_span("phone", 0, 10)]  # thieu name
        result = match_by_slot_type(gt, pred)
        assert result["phone"] == {"tp": 1, "fn": 0, "fp": 0}
        assert result["name"] == {"tp": 0, "fn": 1, "fp": 0}


class TestLabelSetHash:
    def test_deterministic_bat_ke_thu_tu_input(self):
        rows_a = [{"sample_id": "s1", "labeled_slots": [_span("phone", 0, 10)]},
                  {"sample_id": "s2", "labeled_slots": []}]
        rows_b = list(reversed(rows_a))
        assert label_set_hash(rows_a) == label_set_hash(rows_b)

    def test_doi_1_labeled_slots_doi_hash(self):
        h1 = label_set_hash([{"sample_id": "s1", "labeled_slots": [_span("phone", 0, 10)]}])
        h2 = label_set_hash([{"sample_id": "s1", "labeled_slots": [_span("phone", 0, 11)]}])
        assert h1 != h2


class TestCorpusManifestHash:
    """REV2 T1-04: CA yeu cau ro — 2 corpus KHAC NHAU voi CUNG 3 tham so roi (batch_id/
    normalization_version/detector_version) phai ra hash KHAC NHAU (evaluation_hash() cu bi
    XOA vi khong dat duoc dieu nay)."""

    def test_sensitivity_2_corpus_khac_noi_dung_cung_tham_so_roi(self):
        common = {"batch_id": "b1", "normalization_version": "nfc-v1"}
        corpus_a = [{"sample_id": "s1", "labeled_slots": [_span("phone", 0, 10)], "truncated": False}]
        corpus_b = [{"sample_id": "s1", "labeled_slots": [_span("phone", 0, 11)], "truncated": False}]
        h1 = corpus_manifest_hash(samples=corpus_a, **common)
        h2 = corpus_manifest_hash(samples=corpus_b, **common)
        assert h1 != h2

    def test_doi_sample_id_doi_hash(self):
        common = {"batch_id": "b1", "normalization_version": "nfc-v1"}
        h1 = corpus_manifest_hash(samples=[{"sample_id": "s1", "labeled_slots": [], "truncated": False}], **common)
        h2 = corpus_manifest_hash(samples=[{"sample_id": "s2", "labeled_slots": [], "truncated": False}], **common)
        assert h1 != h2

    def test_doi_truncated_doi_hash(self):
        common = {"batch_id": "b1", "normalization_version": "nfc-v1"}
        h1 = corpus_manifest_hash(samples=[{"sample_id": "s1", "labeled_slots": [], "truncated": False}], **common)
        h2 = corpus_manifest_hash(samples=[{"sample_id": "s1", "labeled_slots": [], "truncated": True}], **common)
        assert h1 != h2

    def test_deterministic_bat_ke_thu_tu_input(self):
        common = {"batch_id": "b1", "normalization_version": "nfc-v1"}
        samples = [{"sample_id": "s1", "labeled_slots": [], "truncated": False},
                   {"sample_id": "s2", "labeled_slots": [], "truncated": False}]
        assert corpus_manifest_hash(samples=samples, **common) == \
            corpus_manifest_hash(samples=list(reversed(samples)), **common)


class TestResultAndReportHash:
    def test_result_hash_doi_prediction_doi_hash(self):
        base = {"corpus_hash": "c1", "detector_version": "m4d-0.1.0"}
        h1 = result_hash(ordered_predictions=[{"sample_id": "s1", "predicted_slots": [_span("phone", 0, 10)]}], **base)
        h2 = result_hash(ordered_predictions=[{"sample_id": "s1", "predicted_slots": [_span("phone", 0, 11)]}], **base)
        assert h1 != h2

    def test_result_hash_doi_corpus_hash_doi_hash(self):
        preds = [{"sample_id": "s1", "predicted_slots": []}]
        h1 = result_hash(corpus_hash="c1", detector_version="m4d-0.1.0", ordered_predictions=preds)
        h2 = result_hash(corpus_hash="c2", detector_version="m4d-0.1.0", ordered_predictions=preds)
        assert h1 != h2

    def test_report_hash_doi_metrics_doi_hash(self):
        base = {"corpus_hash": "c1", "result_hash_value": "r1"}
        h1 = report_hash(metrics={"phone": {"tp": 1, "fn": 0, "fp": 0}}, **base)
        h2 = report_hash(metrics={"phone": {"tp": 0, "fn": 1, "fp": 0}}, **base)
        assert h1 != h2

    def test_report_hash_deterministic(self):
        kwargs = {"corpus_hash": "c1", "result_hash_value": "r1",
                  "metrics": {"phone": {"tp": 1, "fn": 0, "fp": 0}}}
        assert report_hash(**kwargs) == report_hash(**kwargs)
