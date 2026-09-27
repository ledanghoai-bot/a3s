-- 075 — CA Directive 404 §2C: quan sat quote — tu 1 command_key doi chieu duoc order, snapshot, route decision,
-- endpoint GHN, response class, quote log, route operation, outbox. ADDITIVE (cot NULL, khong backfill, khong sua lich
-- su quote/payment/order). provider_quote_log van append-only (trigger pql_no_mutate khong doi).

ALTER TABLE provider_quote_log ADD COLUMN IF NOT EXISTS trace_key TEXT;            -- command_key | m7_routing:<order>
ALTER TABLE provider_quote_log ADD COLUMN IF NOT EXISTS route_operation_id BIGINT;  -- fulfillment_route_operations.id
ALTER TABLE provider_quote_log ADD COLUMN IF NOT EXISTS endpoint TEXT;             -- path GHN (khong host/token)
ALTER TABLE provider_quote_log ADD COLUMN IF NOT EXISTS response_class TEXT;       -- ok | http_<n> | transport_<x> | skipped_<x>
-- CA Review 406: 1 dong log = 1 lan quote LOGIC; so HTTP request THAT (gom retry fee + leadtime) dem rieng.
ALTER TABLE provider_quote_log ADD COLUMN IF NOT EXISTS http_attempts INTEGER;     -- NULL: ban ghi truoc 075

CREATE INDEX IF NOT EXISTS idx_provider_quote_log_trace ON provider_quote_log (trace_key)
    WHERE trace_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_provider_quote_log_route_op ON provider_quote_log (route_operation_id)
    WHERE route_operation_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_route_operations_command_key ON fulfillment_route_operations (command_key);

-- ROLLBACK (chay tay khi CA/PO quyet; code cu KHONG doc/ghi cac cot nay -> co the giu nguyen):
-- DROP INDEX IF EXISTS idx_route_operations_command_key; DROP INDEX IF EXISTS idx_provider_quote_log_route_op;
-- DROP INDEX IF EXISTS idx_provider_quote_log_trace;
-- ALTER TABLE provider_quote_log DROP COLUMN IF EXISTS http_attempts, DROP COLUMN IF EXISTS response_class,
--     DROP COLUMN IF EXISTS endpoint,
--     DROP COLUMN IF EXISTS route_operation_id, DROP COLUMN IF EXISTS trace_key;
