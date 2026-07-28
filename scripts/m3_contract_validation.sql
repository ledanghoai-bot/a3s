-- m3_contract_validation.sql — OPERATIONAL post-migration validation cho contract M3 (029-036).
-- PO Decision Record M3 muc 5; mau theo operational_seed_validation.sql (F-R1-01):
-- EXISTING-SAFE: chi kiem STRUCTURAL + seed bat bien theo thiet ke (khong exact-count du lieu van hanh
-- co the tang hop le: consent_records, retention_run_log, template version moi...).
-- RAISE EXCEPTION -> migrate.py `up` VALIDATION FAIL -> exit != 0.
DO $val$
DECLARE
  n int; cdef text;
BEGIN
  -- 029: orders co 'delivered' trong CHECK + cot delivered_at
  SELECT pg_get_constraintdef(oid) INTO cdef FROM pg_constraint WHERE conname='orders_status_check';
  IF cdef IS NULL OR strpos(cdef, '''delivered''') = 0 THEN
    RAISE EXCEPTION 'M3 FAIL: orders_status_check thieu delivered'; END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                 WHERE table_name='orders' AND column_name='delivered_at') THEN
    RAISE EXCEPTION 'M3 FAIL: thieu orders.delivered_at'; END IF;

  -- 030: du 5 cot UTM tren orders + conversations
  SELECT count(*) INTO n FROM information_schema.columns WHERE table_name='orders'
    AND column_name IN ('utm_source','utm_medium','utm_campaign','utm_content','utm_term');
  IF n <> 5 THEN RAISE EXCEPTION 'M3 FAIL: orders thieu cot UTM (%/5)', n; END IF;
  SELECT count(*) INTO n FROM information_schema.columns WHERE table_name='conversations'
    AND column_name IN ('utm_source','utm_medium','utm_campaign','utm_content','utm_term');
  IF n <> 5 THEN RAISE EXCEPTION 'M3 FAIL: conversations thieu cot UTM (%/5)', n; END IF;

  -- 031: consent ledger + unique revision index (chong ghi de)
  IF to_regclass('public.consent_records') IS NULL THEN
    RAISE EXCEPTION 'M3 FAIL: thieu consent_records'; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname='consent_records_rev_uq') THEN
    RAISE EXCEPTION 'M3 FAIL: thieu consent_records_rev_uq'; END IF;

  -- 032+034+036: template registry + trigger immutability + seed toi thieu
  IF to_regclass('public.outbound_templates') IS NULL THEN
    RAISE EXCEPTION 'M3 FAIL: thieu outbound_templates'; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname='outbound_templates_guard_trg') THEN
    RAISE EXCEPTION 'M3 FAIL: thieu trigger outbound_templates_guard_trg (immutability)'; END IF;
  SELECT count(*) INTO n FROM outbound_templates WHERE version=1 AND status IN ('approved','retired')
    AND template_key IN ('order_status_confirmed','order_status_fulfilled','order_status_delivered',
                         'order_status_cancelled','order_status_cancelled_by_exception',
                         'order_status_completed');
  IF n <> 6 THEN RAISE EXCEPTION 'M3 FAIL: seed template v1 thieu (%/6)', n; END IF;
  -- F-M3-GATE-R1-02: EXACT TUPLE cho fulfilled v2 (khong chi ton tai + approved)
  IF (SELECT count(*) FROM outbound_templates
      WHERE template_key='order_status_fulfilled' AND version=2
        AND purpose_code='P03_TRANSACTIONAL'
        AND body='Đơn #{id} của bạn đã được bàn giao cho đơn vị vận chuyển.'
        AND status='approved') <> 1 THEN
    RAISE EXCEPTION 'M3 FAIL: order_status_fulfilled v2 khong khop EXACT tuple PO duyet (036/PO #4)'; END IF;
  -- Seed v1 exact content (cung md5 nhu 034 apply-time — validation chay MOI deploy)
  IF (SELECT md5(string_agg(template_key || '|' || version || '|' || purpose_code || '|' || status
                            || '|' || body, E'\n' ORDER BY template_key))
        FROM outbound_templates
       WHERE version = 1
         AND template_key IN ('order_status_confirmed','order_status_fulfilled','order_status_delivered',
                              'order_status_cancelled','order_status_cancelled_by_exception',
                              'order_status_completed'))
     IS DISTINCT FROM '538cf5f754455679ae4bd3beb6eab009' THEN
    RAISE EXCEPTION 'M3 FAIL: seed template v1 content drift (md5 khong khop)'; END IF;

  -- 033+035+037: retention policy/log/hold + EXACT approved contract (F-M3-GATE-R1-01) + trigger
  IF to_regclass('public.retention_policies') IS NULL OR to_regclass('public.retention_run_log') IS NULL
     OR to_regclass('public.legal_holds') IS NULL THEN
    RAISE EXCEPTION 'M3 FAIL: thieu bang retention/legal_holds'; END IF;
  IF (SELECT count(*) FROM retention_policies
      WHERE rule_id='RET-04' AND version=1 AND data_category='raw_chat' AND action='delete'
        AND retention_period_days=730 AND respect_legal_hold=true AND status='approved') <> 1 THEN
    RAISE EXCEPTION 'M3 FAIL: RET-04 v1 khong khop EXACT approved contract (raw_chat/delete/730/hold=true)'; END IF;
  IF (SELECT count(*) FROM retention_policies
      WHERE rule_id='RET-09' AND version=1 AND data_category='deletion_requests' AND action='delete'
        AND retention_period_days=730 AND respect_legal_hold=true AND status='approved') <> 1 THEN
    RAISE EXCEPTION 'M3 FAIL: RET-09 v1 khong khop EXACT approved contract (deletion_requests/delete/730/hold=true)'; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname='retention_policies_guard_trg') THEN
    RAISE EXCEPTION 'M3 FAIL: thieu trigger retention_policies_guard_trg (037 immutability)'; END IF;
END $val$;
