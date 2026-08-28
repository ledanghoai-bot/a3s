"""M4-9 — Dashboard-triggered Production Signing Run (control/approval surface).

Xem docs/M4-9-DASHBOARD-TRIGGER-DESIGN-VI.md. Package nay la LOP DIEU PHOI:
- `run_store`  : state machine + ledger bat bien (bang m4_signing_run*).
- `policy`     : preflight/policy engine fail-closed (window/scope/quota/stale/drift/health).
- `cli_adapter`: boc CLI runner (scripts/m4_stage0p_rehearsal_runner.py) — KHONG viet lai logic ky.

Bat bien: khong secret/PIN/private key/raw token/customer data di qua lop nay vao request/UI/
log/evidence. Execution that su van do CLI + tang RBAC Postgres cua stage0p enforce.
"""
