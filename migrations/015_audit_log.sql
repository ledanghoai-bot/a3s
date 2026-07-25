-- Migration 015: audit_log (I-B M0.3). CA-REVIEW-IMPL-M0 §10.
-- Append-only theo convention + khong endpoint update/delete (CA §7.4: tach DB role = deferred,
-- KHONG tuyen bo enforce o DB trong M0). Actor model: actor_type + actor_ref + actor_staff_id.
-- transactional: true
CREATE TABLE IF NOT EXISTS audit_log (
  id             BIGSERIAL PRIMARY KEY,
  actor_type     TEXT NOT NULL,                       -- staff | bot | worker | api | system | channel
  actor_ref      TEXT,                                -- dinh danh chung (bot name, worker, channel id...)
  actor_staff_id BIGINT REFERENCES staff_users(id),   -- chi khi actor la staff
  action         TEXT NOT NULL,                       -- 'auth.login', 'staff.deactivate', ...
  entity_type    TEXT,
  entity_id      TEXT,
  before         JSONB,                               -- da redact secret/PII thua (audit_service._redact)
  after          JSONB,
  reason         TEXT,
  request_id     TEXT,
  correlation_id TEXT,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS audit_log_entity_idx  ON audit_log(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS audit_log_actor_idx   ON audit_log(actor_type, actor_staff_id);
CREATE INDEX IF NOT EXISTS audit_log_created_idx ON audit_log(created_at DESC);
