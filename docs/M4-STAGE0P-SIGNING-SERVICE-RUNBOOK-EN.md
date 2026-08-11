# M4 Stage 0P — Signing Service Operations Runbook (A08-COR-01)

> Answers `PHASE1B-M4-AMENDMENT-08-SIGNING-CLEANUP-CORRECTION-DIRECTIVE-VI.md` A08-COR-01. Read
> alongside `docs/VPS-RUNBOOK-EN.md` (general VPS ops) and the `scripts/m4_stage0p_rehearsal_runner.py`
> docstring (full PIN/approval ceremony cycle). This document covers ONLY the signing service — a
> separate OS process holding the signing/encryption keys, fully isolated from the collector.

## 0. Why a dedicated document

`app/services/pii/stage0p_signing_service.py`, after 14 rounds of CA Technical Review (T10-T13),
must run as **a real OS process under a different UID than the collector**, reading its signing
key only from its own environment. Production previously **deliberately left**
`M4_STAGE0P_SIGNING_SOCKET` empty — an independent defense layer (if `capture_enabled` is
accidentally turned on, the signing step still fails closed because no service is alive). Amendment
08 (Aug 11) was the first real execution attempt — it failed because **nobody had ever actually
started this service on production** (F-A08-EXEC-01).

`scripts/m4_stage0p_signing_launcher.py` (new, A08-COR-01) is the explicit, reviewed operational
tool to start/stop that service safely — it reuses the already-14-round-reviewed logic in
`scripts/_stage0p_signing_service_helper.py` verbatim (no rewrite). Use it only when (and exactly
when) a real rehearsal ceremony needs it — **it is not part of `docker-compose.prod.yml` or
`deploy.sh`**, and a dormant deploy never auto-starts it.

## 1. Full ceremony sequence (summary — see runner docstring for PIN/approval detail)

```
record-approval (staff 3, own PIN)
  -> provision-keys (3 fresh, randomly generated keys)
  -> signing_launcher.py start (SAME 3 keys)          <-- NEW step (A08-COR-01)
  -> run --dry-run (confirm preflight)
  -> run (real execute, runs UNDER m4-collector UID)  <-- NEW step (A08-COR-01)
  -> signing_launcher.py stop                          <-- NEW step (A08-COR-01)
  -> retire-keys
  -> record-approval --revoke
```

## 2. Mandatory preflight before start

- Confirm deployed HEAD matches the CA-accepted commit (`git rev-parse HEAD`).
- Confirm `signing_launcher.py status` reports `running: false` (no leftover instance).
- Confirm `m4_stage0p_transcript_signing_keys`/`m4_stage0p_signing_auth_keys` have no active old
  key (if any, `retire-keys` first).

```bash
docker exec alpha3s-api-1 python scripts/m4_stage0p_signing_launcher.py status
```

## 3. Start — launch the signing service

**Use the EXACT SAME 3 keys** just handed to `provision-keys` (mismatched keys = the service
signs fine but DB `signing_authorization` verification always rejects — safe but useless, not a
security hole).

```bash
docker exec \
  -e M4_SAMPLE_KEY_B64="$M4_SAMPLE_KEY_B64" \
  -e M4_TRANSCRIPT_HMAC_KEY_B64="$M4_TRANSCRIPT_HMAC_KEY_B64" \
  -e M4_SIGNING_AUTH_VERIFY_KEY_B64="$M4_SIGNING_AUTH_VERIFY_KEY_B64" \
  alpha3s-api-1 python scripts/m4_stage0p_signing_launcher.py start
```

The JSON output confirms (no secret ever printed): `pid`, `signer_uid`, `collector_uid`,
`shared_gid`, `socket_path`. First run auto-creates (idempotent, `useradd`/`groupadd`) two system
accounts `m4-signer`/`m4-collector` plus one shared group `m4-signing-ipc`.

> Note: you may see one line `Exception ignored in: ... RuntimeError: Event loop is closed` right
> after the JSON line — this is a harmless Python asyncio cleanup warning that fires after the
> child process has already successfully detached (verified: it does not affect the exit code and
> does not kill the child; the signing service keeps running). Not an error to act on.

## 4. Execute — run the rehearsal UNDER the m4-collector UID

This is the single most important difference from before Amendment 08: the real `run` (execute)
command MUST now run under UID `m4-collector` (not `docker exec`'s default root) so the signing
service can genuinely distinguish two different UIDs (T12-01) — and MUST point at the correct
socket path:

```bash
docker exec --user m4-collector \
  -e STAGE0P_REHEARSAL_OPERATOR_PIN="$STAGE0P_REHEARSAL_OPERATOR_PIN" \
  -e STAGE0P_REHEARSAL_REVIEWER_PIN="$STAGE0P_REHEARSAL_REVIEWER_PIN" \
  -e M4_STAGE0P_SIGNING_SOCKET=/run/m4-signing/signing.sock \
  -e M4_SAMPLE_KEY_B64="$M4_SAMPLE_KEY_B64" \
  alpha3s-api-1 python scripts/m4_stage0p_rehearsal_runner.py run \
  --manifest datasets/pii/m4_stage0p_rehearsal_manifest_v2.jsonl \
  --approval-ref "<approval_ref>" \
  --operator-staff-id <N> --reviewer-staff-id <M>
```

`M4_SAMPLE_KEY_B64` here is NOT a signing-service secret (already handed to `provision-keys`
earlier) — the prediction writer (runs inside the runner process, not the signing service) needs
this value to decrypt the symmetric-AEAD sample when running the detector, matching a design that
predates A08-COR-01 (see `_run_execute` docstring).

**If you forget `--user m4-collector`**: the command runs under the default UID (usually root/UID
0) — the signing service rejects the connection IMMEDIATELY (peer UID doesn't match
`collector_uid`, T11-02/T12-01), the collector fails closed exactly as designed (nothing leaked,
just logs `m4_signing_peer_rejected`), the rehearsal fails cleanly — fix `--user` and retry under
a fresh ceremony (the prior gate is already consumed, no retry under the same gate).

## 5. Stop — shut the signing service down (after the rehearsal ends, success or failure)

```bash
docker exec alpha3s-api-1 python scripts/m4_stage0p_signing_launcher.py stop
```

Idempotent — calling it with nothing running exits 0 safely (just logs
`signing_service_not_running`). Auto-removes the pidfile + socket + socket directory.

## 6. Key lifecycle summary

| Key | Generated where | Lives where | Retired when |
|---|---|---|---|
| `M4_SAMPLE_KEY_B64` | Operator runs `openssl rand -base64 32` (or equivalent) before `provision-keys` | Only in the environment of `provision-keys` + `signing_launcher start` + `run` (prediction writer) — no DB table stores it | No DB "retire" needed (nothing provisioned in DB) — simply stop reusing the value after `stop` |
| `M4_TRANSCRIPT_HMAC_KEY_B64` | Same time | `m4_stage0p_transcript_signing_keys` (DB) + signing service environment | `retire-keys` (DB) AFTER `signing_launcher stop` |
| `M4_SIGNING_AUTH_VERIFY_KEY_B64` | Same time | `m4_stage0p_signing_auth_keys` (DB) + signing service environment | `retire-keys` (DB) AFTER `signing_launcher stop` |

**Never** write these 3 keys to any file, `.env`, log, or evidence artifact — they only exist in
the environment of the commands above, and disappear when the shell session ends.

## 7. Rollback / troubleshooting

| Situation | Action |
|---|---|
| `start` reports "already running (pid=...)" | An old instance is running — `stop` first, or if you're sure it belongs to the current ceremony, `status` to confirm before proceeding |
| `start` reports `RuntimeError: signing service khong tao socket ... trong 5s` or "exited early" | The signing service itself refused to start (unsafe socket directory, wrong key length, ...) — read the full JSON log in the output, do NOT blindly retry, cross-check against `_validate_socket_directory`/`main()` in `stage0p_signing_service.py` |
| Execute reports `SigningServiceError: khong ket noi duoc signing service` | `status` to confirm the service is alive and the socket path is correct; confirm `--user m4-collector` and `M4_STAGE0P_SIGNING_SOCKET` were passed correctly (not mangled by some shell/tool along the way) |
| Execute reports "chua co signing_auth_key hieu luc" | The keys given to `provision-keys` (DB) and to `signing_launcher start` do NOT match (e.g. a `retire-keys` ran in between from a prior cleanup) — `stop`, `retire-keys`, generate FRESH keys, redo from `provision-keys` |
| Need an emergency stop | `signing_launcher.py stop` (SIGTERM then SIGKILL if needed within 5s) — safe to call any time, does not corrupt already-written data (only stops accepting new requests) |
| Pidfile present but process is dead (crashed) | `status`/`stop` detect this automatically by cross-checking `/proc/<pid>/cmdline` — never signals an unrelated process that happens to have reused the PID |

## 8. Evidence commands (no secret leakage)

```bash
docker exec alpha3s-api-1 python scripts/m4_stage0p_signing_launcher.py status
docker exec alpha3s-api-1 ps aux | grep -i signing_service
docker exec alpha3s-api-1 printenv | grep -iE "M4_SAMPLE_KEY|TRANSCRIPT_HMAC_KEY|SIGNING_AUTH_VERIFY_KEY"  # MUST be empty inside the api container (collector) - keys ONLY live in the signer process
```

The last line is an important independent proof: run inside the `api` container (where the
collector/runner live), the 3 key variables MUST **not appear** — if they do, that's a sign the
key leaked into the wrong environment; stop immediately and report to CA.
