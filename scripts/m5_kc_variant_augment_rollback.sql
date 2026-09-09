-- M5 Matcher k/c variant — augmentation ROLLBACK (CA Amendment 259 §3.1: delete EXACTLY this batch).
-- Removes only rows created by scripts/m5_kc_variant_augment_seed.sql / migration 063, identified by the
-- source_batch marker. Does NOT touch other augmentation batches or authoritative admin_unit_alias.
-- Idempotent (re-run deletes 0).
DELETE FROM admin_unit_alias_augment WHERE source_batch = 'kc_variant_c2k_v1';
