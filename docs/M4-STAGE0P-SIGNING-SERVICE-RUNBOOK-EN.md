# M4 Stage 0P — Signing Service Operations Runbook (A08-COR-01)

> Answers `PHASE1B-M4-AMENDMENT-08-SIGNING-CLEANUP-CORRECTION-DIRECTIVE-VI.md` A08-COR-01,
> revised per `PHASE1B-M4-AMENDMENT-08-SIGNING-CLEANUP-CORRECTION-REVIEW-1-VI.md`
> F-A08-R1-01/02/03. Read alongside `docs/VPS-RUNBOOK-EN.md` (general VPS ops) and the
> `scripts/m4_stage0p_rehearsal_runner.py` docstring (full PIN/approval ceremony cycle). This
> document covers ONLY the signing service — a separate OS process holding the signing/encryption
> keys, fully isolated from the collector.

## 0. Why a dedicated document — and why the topology changed in REV1

`app/services/pii/stage0p_signing_service.py`, after 14 rounds of CA Technical Review (T10-T13),
must run as a real OS process under a UID different from the collector's. Production previously
deliberately left `M4_STAGE0P_SIGNING_SOCKET` empty — Amendment 08 (Aug 11) failed because nobody
had ever actually started this service.

**REV0** of this correction used a Python script (`m4_stage0p_signing_launcher.py`) that spawned
the process itself via `asyncio` and ran `useradd` while the container was already running. CA
Review 1 (F-A08-R1-01) rejected this direction: runtime-created UIDs are **mutable, ephemeral
state** (lost if the container is recreated), with no real supervisor/restart policy/log sink.

**REV1 (current)**: moved to a **docker-compose profile service** — `docker compose` itself is
the supervisor (manages lifecycle/logs/restarts), the `m4-signer`/`m4-collector` UIDs are created
**at image build time** (Dockerfile, version-controlled, identical on every container built from
the image), and there is no longer any Python script spawning a process at all — no more GC
warning, no more hand-rolled pidfile.

## 1. Full ceremony sequence (summary — see runner docstring for PIN/approval detail)

```
record-approval (staff 3, own PIN)
  -> provision-keys (3 fresh, randomly generated keys)
  -> docker compose --profile m4-signing up -d m4-signer   <-- NEW step (A08-COR-01)
  -> signing_probe.py (canary, confirms the REAL signing path works)  <-- NEW step (F-A08-R1-03)
  -> run --dry-run (confirm preflight)
  -> run (real execute, runs UNDER m4-collector UID)        <-- NEW step (A08-COR-01)
  -> docker compose --profile m4-signing stop m4-signer     <-- NEW step (A08-COR-01)
  -> retire-keys
  -> record-approval --revoke
```

## 2. Mandatory preflight before start

```bash
docker compose -f docker-compose.prod.yml --profile m4-signing ps m4-signer
```

Confirm: no `m4-signer` container is currently `Up` (if one is, `stop` it first — see §5);
deployed HEAD matches the CA-accepted commit (`git rev-parse HEAD`);
`m4_stage0p_transcript_signing_keys`/`m4_stage0p_signing_auth_keys` have no active old key (if
any, `retire-keys` first).

## 3. Start — launch the signing service via docker compose

**Keys MUST be exported in the current shell session BEFORE calling `up`** — `docker compose`
reads `${VAR}` from the environment of the shell invoking it; it does NOT need, and MUST NOT be
given, a `.env` file or any other file:

```bash
export M4_SAMPLE_KEY_B64="..."             # SAME value handed to provision-keys
export M4_TRANSCRIPT_HMAC_KEY_B64="..."    # SAME value handed to provision-keys
export M4_SIGNING_AUTH_VERIFY_KEY_B64="..." # SAME value handed to provision-keys

docker compose -f docker-compose.prod.yml --profile m4-signing up -d m4-signer
```

Check status (no secret revealed):

```bash
docker compose -f docker-compose.prod.yml --profile m4-signing ps m4-signer
docker compose -f docker-compose.prod.yml logs m4-signer --tail 20
```

`STATUS` should read `Up (healthy)` within a few seconds (the `healthcheck` only checks the
socket file exists with the correct mode — see §4 for a deeper proof the signing path actually
works).

`m4-signer` runs under the fixed UID `5001` (group `5000`, both baked into the image via the
`Dockerfile`) — no more runtime `useradd` at all.

## 4. Canary probe — confirm the REAL signing path works (F-A08-R1-03)

Compose's `healthcheck` only proves **the process is listening** (socket file exists with the
right mode) — it does NOT prove peer-UID/rate-limit/nonce/signature/canonicalize/encrypt/sign
actually work end to end. Run a real canary probe (fully synthetic data, no DB write, no
rehearsal/customer data touched) from the exact collector identity:

```bash
docker compose -f docker-compose.prod.yml exec --user m4-collector \
  -e M4_SIGNING_AUTH_VERIFY_KEY_B64 \
  api python scripts/m4_stage0p_signing_probe.py
```

**Note the `-e NAME` form (NO `=value`, F-A08-R1-02)** — this is deliberate, not a typo. The `-e
NAME="$NAME"` form puts the secret value as a literal argv token of the `docker`/`docker compose`
client process on the host (readable by anyone with `ps aux`/`/proc/<pid>/cmdline` access on the
host while the command is running). The bare `-e NAME` form tells the Docker client to read the
value from its OWN environment (already `export`ed per §3) and forward it over the Docker API —
the secret is never an argv token (empirically verified: `docker exec -e VAR <container> printenv
VAR` returns the correct value even though `VAR` never appears with `=value` on the command line).

A `{"event": "m4_signing_probe_ok", "ok": true, ...}` JSON output confirms: the `m4-collector`
peer UID is accepted by the service, the rate-limit/nonce/`signing_authorization` signature
(self-signed with the SAME `M4_SIGNING_AUTH_VERIFY_KEY_B64`, algorithm imported directly from
`stage0p_signing_service.py`, never hand-copied) all check out, and the service genuinely
canonicalizes + encrypts + signs successfully. `ok: false` → see §6 (rollback/troubleshooting),
**do not proceed with the ceremony**.

## 5. Execute — run the rehearsal UNDER the m4-collector UID

Besides `M4_SAMPLE_KEY_B64` (already exported in §3), the operator also needs to `export` their
own 2 PINs (`STAGE0P_REHEARSAL_OPERATOR_PIN`/`STAGE0P_REHEARSAL_REVIEWER_PIN` — the actual
operator/reviewer running this ceremony, unrelated to the 3 signing/encryption keys in §3) before
calling `exec`:

```bash
export M4_STAGE0P_SIGNING_SOCKET=/run/m4-signing/signing.sock   # not a secret, but exported for
                                                                  # a consistent passing convention
docker compose -f docker-compose.prod.yml exec --user m4-collector \
  -e STAGE0P_REHEARSAL_OPERATOR_PIN \
  -e STAGE0P_REHEARSAL_REVIEWER_PIN \
  -e M4_STAGE0P_SIGNING_SOCKET \
  -e M4_SAMPLE_KEY_B64 \
  api python scripts/m4_stage0p_rehearsal_runner.py run \
  --manifest datasets/pii/m4_stage0p_rehearsal_manifest_v2.jsonl \
  --approval-ref "<approval_ref>" \
  --operator-staff-id <N> --reviewer-staff-id <M>
```

Bare `-e NAME` form (no `=value`) — see §4's explanation, applies to all 3 secrets here
(`STAGE0P_REHEARSAL_OPERATOR_PIN`/`STAGE0P_REHEARSAL_REVIEWER_PIN`/`M4_SAMPLE_KEY_B64`): the value
is never an argv token of the `docker compose` client process on the host.

The `api` service shares the `m4_signing_socket` volume with `m4-signer` (see
`docker-compose.prod.yml`), so the socket path `/run/m4-signing/signing.sock` is visible to both.
`M4_SAMPLE_KEY_B64` here is NOT a signing-service secret — it IS genuinely sensitive (the sample
decryption key), but is needed by the prediction writer (runs inside the runner process, not the
signing service) to decrypt the symmetric-AEAD sample when running the detector (a design that
predates A08-COR-01).

**If you forget `--user m4-collector`**: the signing service rejects the connection IMMEDIATELY
(peer UID mismatch, T11-02/T12-01) — fails closed exactly as designed, nothing leaked, the
rehearsal fails cleanly.

## 6. Stop — shut the signing service down (after the rehearsal ends, success or failure)

```bash
docker compose -f docker-compose.prod.yml --profile m4-signing stop m4-signer
docker compose -f docker-compose.prod.yml --profile m4-signing rm -f m4-signer
```

`stop` sends SIGTERM (graceful); the container does not auto-restart (`restart: "no"` is
deliberate — see the comment in `docker-compose.prod.yml`). `rm -f` cleans up the stopped
container (not mandatory but recommended, avoids confusion on the next `ps`).

## 7. Key lifecycle summary

| Key | Generated where | Lives where | Retired when |
|---|---|---|---|
| `M4_SAMPLE_KEY_B64` | Operator runs `openssl rand -base64 32` before `provision-keys` | The operator's shell environment for the whole ceremony (given to `provision-keys`, the `m4-signer` service, and `run`/prediction writer) — no DB table stores it | No DB "retire" needed — simply stop reusing the value after `stop` |
| `M4_TRANSCRIPT_HMAC_KEY_B64` | Same time | `m4_stage0p_transcript_signing_keys` (DB) + the `m4-signer` container environment | `retire-keys` (DB) AFTER `stop` |
| `M4_SIGNING_AUTH_VERIFY_KEY_B64` | Same time | `m4_stage0p_signing_auth_keys` (DB) + the `m4-signer` container environment (+ the operator keeps it to run the canary probe, §4) | `retire-keys` (DB) AFTER `stop` |

**The 3 keys ONLY exist in the operator's shell environment** for the duration of the ceremony —
never written to any file, `.env`, log, or evidence artifact. `docker compose up`/`exec -e <NAME>`
(bare form, no `=value` — see §4/§5) read directly from the operator's shell environment; no
intermediate file is needed or created, and (unlike this document's REV0) the value no longer
leaks into the host-side `docker`/`docker compose` client process's own argv either.

**Remaining inherent limitations (F-A08-R1-02), stated plainly — 2 DIFFERENT channels, do not
conflate them**:

1. **`m4-signer`'s OWN container environment** (`M4_SAMPLE_KEY_B64`/`M4_TRANSCRIPT_HMAC_KEY_B64`/
   `M4_SIGNING_AUTH_VERIFY_KEY_B64` declared via `environment:` in `docker-compose.prod.yml`,
   resolving `${VAR}` at `up` time) genuinely gets baked into the container's `Config.Env` at
   creation, and `docker inspect m4-signer` reveals it in plaintext to anyone with Docker
   API/root access on the host — this is an inherent limitation of Docker's own container
   environment-variable mechanism (not specific to this design, applies to any service using
   `environment:` with a secret), not a vulnerability this runbook introduces.
2. **Secrets passed at `exec` time** (the 3 values in §4/§5: `M4_SIGNING_AUTH_VERIFY_KEY_B64` for
   the probe, `STAGE0P_REHEARSAL_OPERATOR_PIN`/`STAGE0P_REHEARSAL_REVIEWER_PIN`/
   `M4_SAMPLE_KEY_B64` for execute) are NOT part of the container's `Config.Env` (`docker exec -e`
   is a per-exec-session override, not persisted), so `docker inspect` does NOT reveal these —
   the bare `-e NAME` form (already applied in §4/§5) closes the one remaining leak channel (the
   host-side client process's own argv).

Both cases: anyone with Docker API/root access on the host already has the ability to read `.env`
or connect to the DB directly — neither expands the attack surface beyond that existing access
level.

## 8. Rollback / troubleshooting

| Situation | Action |
|---|---|
| `up -d m4-signer` reports a missing env var (`Phai dat M4_...`) | Not all 3 keys were `export`ed in the current shell — export them and retry |
| `ps m4-signer` shows `Exited`/`unhealthy` | `docker compose logs m4-signer --tail 50` to read the REAL reason (e.g. `_validate_socket_directory` refusal) — do NOT retry blindly |
| `signing_probe.py` reports `ok: false` | Check `docker compose ps m4-signer` is still `Up`; confirm `M4_SIGNING_AUTH_VERIFY_KEY_B64` passed to the probe EXACTLY matches the value given to `up -d m4-signer` (a mismatch = signature fails, safe but useless) |
| Execute reports `SigningServiceError: khong ket noi duoc signing service` | Confirm `ps m4-signer` is still `Up`; confirm `--user m4-collector` and `M4_STAGE0P_SIGNING_SOCKET` were passed correctly to the `exec` command |
| Execute reports "chua co signing_auth_key hieu luc" | The keys given to `provision-keys` (DB) and to `up -d m4-signer` do NOT match (e.g. a `retire-keys` ran in between) — `stop`, `retire-keys`, generate FRESH keys, redo from `provision-keys` |
| Need an emergency stop | `docker compose --profile m4-signing stop m4-signer` (SIGTERM, Docker sends SIGKILL after its default timeout if needed) — safe to call any time |
| `m4-signer` crashes mid-rehearsal | **Does NOT auto-recover** (`restart: "no"` is deliberate) — the collector fails closed on its own after a few retries (see `COLLECTOR_MAX_ATTEMPTS`/`_run_collector_with_retry` in the runner), and the runner's own cleanup terminalizes the batch to `'aborted'`. Check `m4-signer`'s logs (if the container is still around, `docker compose logs`) to find the crash cause before attempting a new ceremony — do not `up -d` again mid-gate |

## 9. Evidence commands (no secret leakage)

```bash
docker compose -f docker-compose.prod.yml --profile m4-signing ps m4-signer
docker compose -f docker-compose.prod.yml logs m4-signer --tail 50
docker compose -f docker-compose.prod.yml exec api printenv | grep -iE "M4_SAMPLE_KEY|TRANSCRIPT_HMAC_KEY|SIGNING_AUTH_VERIFY_KEY"  # MUST be empty inside the api container - keys ONLY live in the m4-signer process
```

The last line is an important independent proof: run inside `api` (where the collector/runner
live), the 3 key variables MUST **not appear** — if they do, stop immediately and report to CA.
