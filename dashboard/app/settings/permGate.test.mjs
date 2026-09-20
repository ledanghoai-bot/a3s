// CA Review 311-01 — test hành vi FAIL-CLOSED cho cổng quyền UI Settings. Chạy: `node --test`.
// Bao phủ 6 trạng thái: PO, shop_manager, staff, loading, auth-me error, unprovisioned.
import assert from "node:assert/strict";
import { test } from "node:test";
import { makeGate } from "./permGate.mjs";

const ALL = ["settings.integration.view", "settings.integration.manage_public", "settings.integration.secret_write",
  "settings.integration.secret_purge", "settings.integration.test", "settings.integration.activate"];
const SHOP_MGR = ["settings.integration.view", "settings.integration.manage_public", "settings.integration.test"];

test("PO (loaded, tất cả quyền) -> mọi action hiện, purge hiện", () => {
  const g = makeGate("loaded", ALL);
  assert.equal(g.ready, true);
  for (const p of ALL) assert.equal(g.can(p), true, p);
  assert.equal(g.can("settings.integration.secret_purge"), true);
});

test("shop_manager (loaded) -> view/manage_public/test hiện; secret/purge/activate ẨN", () => {
  const g = makeGate("loaded", SHOP_MGR);
  assert.equal(g.can("settings.integration.view"), true);
  assert.equal(g.can("settings.integration.manage_public"), true);
  assert.equal(g.can("settings.integration.test"), true);
  assert.equal(g.can("settings.integration.secret_write"), false);
  assert.equal(g.can("settings.integration.secret_purge"), false);
  assert.equal(g.can("settings.integration.activate"), false);
});

test("staff (loaded, [] ) -> mọi action ẨN", () => {
  const g = makeGate("loaded", []);
  assert.equal(g.ready, true);
  for (const p of ALL) assert.equal(g.can(p), false, p);
});

test("loading -> KHÔNG ready, mọi action ẨN (fail-closed), purge ẨN", () => {
  const g = makeGate("loading", []);
  assert.equal(g.ready, false);
  assert.equal(g.loading, true);
  for (const p of ALL) assert.equal(g.can(p), false, p);
  assert.equal(g.can("settings.integration.secret_purge"), false);
});

test("auth-me error -> KHÔNG ready, mọi action ẨN, cờ error", () => {
  const g = makeGate("error", []);
  assert.equal(g.ready, false);
  assert.equal(g.error, true);
  for (const p of ALL) assert.equal(g.can(p), false, p);
});

test("unprovisioned -> KHÔNG ready, mọi action ẨN, cờ unprovisioned", () => {
  const g = makeGate("unprovisioned", []);
  assert.equal(g.ready, false);
  assert.equal(g.unprovisioned, true);
  for (const p of ALL) assert.equal(g.can(p), false, p);
});

test("perms không phải mảng khi loaded -> fail-closed", () => {
  const g = makeGate("loaded", null);
  assert.equal(g.ready, false);
  assert.equal(g.can("settings.integration.view"), false);
});
