-- 074 — CA Directive 396 §2 (F1): them ly do staff_attention 'eta_question' (khach hoi thoi gian giao khi don CHUA co
-- ETA that -> escalate THAT cho nhan vien, khong hua suong). Additive + reversible. Khong doi du lieu.

ALTER TABLE staff_attention DROP CONSTRAINT IF EXISTS staff_attention_reason_check;
ALTER TABLE staff_attention ADD CONSTRAINT staff_attention_reason_check CHECK (reason IN
    ('address', 'quote', 'account', 'method', 'payment_mismatch', 'unmatched_webhook', 'payment_timeout',
     'large_order_review', 'quantity_unit_review', 'provider_error', 'other',
     'refund_required', 'order_cancel_exception', 'shipment_create',
     'eta_question'));

-- ============================ ROLLBACK (chay tay khi CA/PO quyet; KHONG tu dong) ============================
-- Precheck: SELECT count(*) FROM staff_attention WHERE reason='eta_question'; > 0 -> DUNG, bao CA (ho so attention).
-- ALTER TABLE staff_attention DROP CONSTRAINT IF EXISTS staff_attention_reason_check;
-- ALTER TABLE staff_attention ADD CONSTRAINT staff_attention_reason_check CHECK (reason IN
--     ('address', 'quote', 'account', 'method', 'payment_mismatch', 'unmatched_webhook', 'payment_timeout',
--      'large_order_review', 'quantity_unit_review', 'provider_error', 'other',
--      'refund_required', 'order_cancel_exception', 'shipment_create'));
