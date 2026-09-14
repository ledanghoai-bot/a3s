-- 067 M7 route-op: them state 'provider_started' (CA Review 277 blocker 277-01). ADDITIVE / EXPAND-ONLY.
-- Khong sua 066; chi noi rong CHECK de nhan them 1 state trung gian BEN VUNG ghi TRUOC khi goi provider (HTTP).
-- Ly do: 066 chi co 'claimed' truoc provider call -> neu crash SAU khi provider da nhan/tra request nhung TRUOC
--   record_provider(), row van 'claimed' -> request khac takeover goi provider LAN HAI. Them 'provider_started'
--   (ghi atomically truoc HTTP) => chi 'claimed' (chua bat dau provider) moi duoc takeover-goi-provider; 'provider_started'
--   het lease ma chua co result = AMBIGUOUS -> chuyen staff, KHONG tu goi lai (at-most-once provider request).
-- Idempotent: DROP CONSTRAINT IF EXISTS roi ADD lai.

ALTER TABLE fulfillment_route_operations
    DROP CONSTRAINT IF EXISTS fulfillment_route_operations_state_check;

ALTER TABLE fulfillment_route_operations
    ADD CONSTRAINT fulfillment_route_operations_state_check
    CHECK (state IN ('claimed', 'provider_started', 'provider_recorded', 'done', 'failed'));
