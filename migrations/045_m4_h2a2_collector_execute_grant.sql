-- Migration 045: M4 H2-A-2 — cap EXECUTE cho collector tren
-- `m4_stage0p_record_transcript_signature` (migration 044).
--
-- PHAT HIEN NAY DEN TU DAU
-- Migration 044 lam dung nua dau cua quy uoc quyen (039 dong 1404/2550): REVOKE EXECUTE khoi
-- PUBLIC. Nhung no THIEU nua sau — GRANT EXECUTE cho role thuc su goi ham. Ham chi duoc goi tu
-- MOT cho duy nhat: fenced unit cua collector (`app/services/pii/stage0p_sampling.py`), chay duoi
-- role `alpha3s_m4_sample_collector`.
--
-- Hau qua neu khong co migration nay: capture path dual-tag KHONG THE chay. Fenced unit nem
-- `InsufficientPrivilegeError: permission denied for function
-- m4_stage0p_record_transcript_signature` ngay sau `record_sample`, transaction cuon lai, va
-- KHONG sample nao duoc commit. Tuc la H2-A-2 se fail-closed 100% khi bat len — an toan, nhung
-- hoan toan khong dung duoc.
--
-- Bug nay sông sót qua ca PR #24 lan PR #27 vi khong test nao cham vao DB THAT: 10 test cua PR #27
-- kiem hop dong client<->service qua unix socket, con `m4_h2a_e2e_sandbox.py` goi ham 044 bang
-- ket noi ADMIN (khong phai role collector), nen ca hai deu khong bao gio thuc thi dung to hop
-- (role collector + ham 044) ma production se chay. No lo ra ngay o lan chay dau tien cua
-- `scripts/m4_h2a2_e2e_capture_path.py` — dung ly do CA yeu cau E2E o F-H2A2-02.
--
-- VI SAO LA MIGRATION MOI CHU KHONG SUA 044
-- 044 DA duoc ap o production qua deploy path binh thuong va checksum cua no da nam trong ledger
-- (CA PHASE1B-M4-PR25-MERGE-DEPLOY-DORMANT-CLOSURE-VI, `migration_044_checksum`). Sua file 044
-- bay gio se tao checksum drift tren moi DB da ap — runner canh bao/fail dung theo thiet ke. Nen
-- phan bo sung phai la mot migration rieng, thuan cong them.
--
-- PHAM VI: DUNG MOT CAU GRANT. Khong tao/sua bang, cot, ham, trigger, du lieu nao. Khong doi hanh
-- vi cua bat ky duong ghi nao dang chay (H2-A-2 van dormant, capture flags van OFF).

BEGIN;

-- Quyen toi thieu: CHI collector, va CHI EXECUTE. Ham la SECURITY DEFINER (owner
-- alpha3s_m4_definer) nen collector VAN khong co quyen doc/ghi truc tiep tren
-- `m4_stage0p_transcript_signatures` hay registry public key — moi rang buoc cau truc cua 044
-- (khoa phai ton tai, chua thu hoi, sample_id trong transcript phai khop) van la duong duy nhat
-- de mot hang chu ky ra doi.
GRANT EXECUTE ON FUNCTION m4_stage0p_record_transcript_signature(UUID, BYTEA, BYTEA, TEXT, TEXT, TEXT)
  TO alpha3s_m4_sample_collector;

COMMIT;

-- ===========================================================================
-- ROLLBACK (thu cong):
--   REVOKE EXECUTE ON FUNCTION m4_stage0p_record_transcript_signature(UUID, BYTEA, BYTEA, TEXT, TEXT, TEXT)
--     FROM alpha3s_m4_sample_collector;
-- Sau rollback, capture path dual-tag quay lai trang thai fail-closed hoan toan (khong ghi duoc
-- sample nao) — khong mat du lieu da co.
-- ===========================================================================
