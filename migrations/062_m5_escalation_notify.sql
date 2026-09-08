-- 062 M5 order-taking polish (CA Directive 251 §3.D + Review 252-03): DURABLE admin-notify khi order-intent
-- transition ESCALATED, va escalation KHONG-gan-intent (handoff), qua outbox_events. Escalation KHONG phai
-- command-bus operation nen command_id can NULL-able CHO RIENG cac escalation event type.
--
-- CA 252-03: KHONG noi long invariant cho MOI event. Them CHECK constraint allowlist: command_id chi duoc
-- NULL cho 'order.escalated.notify' / 'handoff.escalated.notify'; cac event type command-backed hien huu
-- (order.created.notify, order.receipt.customer, ...) VAN bat buoc command_id IS NOT NULL. Invalid combo bi
-- DB tu choi. Additive + reversible; migrations cu KHONG bi sua; khong backfill.

ALTER TABLE outbox_events ALTER COLUMN command_id DROP NOT NULL;

ALTER TABLE outbox_events ADD CONSTRAINT outbox_command_id_required_unless_escalation
  CHECK (
    command_id IS NOT NULL
    OR event_type IN ('order.escalated.notify', 'handoff.escalated.notify')
  );

-- ROLLBACK (runbook) — chi chay khi khong con row command_id IS NULL (escalation notify da drain/purge):
--   ALTER TABLE outbox_events DROP CONSTRAINT IF EXISTS outbox_command_id_required_unless_escalation;
--   ALTER TABLE outbox_events ALTER COLUMN command_id SET NOT NULL;
