-- 076 — CA Review 414 §2: them ly do staff_attention 'messaging_window_closed' (tin outbox Messenger phat sinh NGOAI
-- khung 24h tu tin khach gan nhat -> KHONG goi Send API, ket thuc event + chuyen nhan vien). Additive + reversible.
-- Khong doi du lieu.

ALTER TABLE staff_attention DROP CONSTRAINT IF EXISTS staff_attention_reason_check;
ALTER TABLE staff_attention ADD CONSTRAINT staff_attention_reason_check CHECK (reason IN
    ('address', 'quote', 'account', 'method', 'payment_mismatch', 'unmatched_webhook', 'payment_timeout',
     'large_order_review', 'quantity_unit_review', 'provider_error', 'other',
     'refund_required', 'order_cancel_exception', 'shipment_create',
     'eta_question', 'messaging_window_closed'));

-- ============================ ROLLBACK (chay tay khi CA/PO quyet; KHONG tu dong) ============================
-- Precheck: SELECT count(*) FROM staff_attention WHERE reason='messaging_window_closed'; > 0 -> DUNG, bao CA.
-- ALTER TABLE staff_attention DROP CONSTRAINT IF EXISTS staff_attention_reason_check;
-- ALTER TABLE staff_attention ADD CONSTRAINT staff_attention_reason_check CHECK (reason IN
--     ('address', 'quote', 'account', 'method', 'payment_mismatch', 'unmatched_webhook', 'payment_timeout',
--      'large_order_review', 'quantity_unit_review', 'provider_error', 'other',
--      'refund_required', 'order_cancel_exception', 'shipment_create',
--      'eta_question'));
