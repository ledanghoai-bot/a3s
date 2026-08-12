# M4 Stage 0P — Signing Service Operations Runbook (A08-COR-01)

> Answers `PHASE1B-M4-AMENDMENT-08-SIGNING-CLEANUP-CORRECTION-DIRECTIVE-VI.md` A08-COR-01,
> revised per `PHASE1B-M4-AMENDMENT-08-SIGNING-CLEANUP-CORRECTION-REVIEW-1-VI.md`
> F-A08-R1-01/02/03, `PHASE1B-M4-AMENDMENT-08-SIGNING-CLEANUP-CORRECTION-REVIEW-2-VI.md`
> F-A08-R2-01/02, and `PHASE1B-M4-AMENDMENT-08-SIGNING-CLEANUP-CORRECTION-REVIEW-3-VI.md`
> F-A08-R3-01/02. Read alongside `docs/VPS-RUNBOOK-EN.md` (general VPS ops) and the
> `scripts/m4_stage0p_rehearsal_runner.py` docstring (full PIN/approval ceremony cycle). This
> document covers ONLY the signing service — a separate OS process holding the signing/encryption
> keys, fully isolated from the collector.

## 0. Why a dedicated document — and why the topology changed across revisions

`app/services/pii/stage0p_signing_service.py`, after 14 rounds of CA Technical Review (T10-T13),
must run as a real OS process under a UID different from the collector's. Production previously
deliberately left `M4_STAGE0P_SIGNING_SOCKET` empty — Amendment 08 (Aug 11) failed because nobody
had ever actually started this service.

**REV0** of this correction used a Python script (`m4_stage0p_signing_launcher.py`) that spawned
the process itself via `asyncio` and ran `useradd` while the container was already running. CA
Review 1 (F-A08-R1-01) rejected this direction: runtime-created UIDs are **mutable, ephemeral
state** (lost if the container is recreated), with no real supervisor/restart policy/log sink.

**REV1**: moved to a **docker-compose profile service** — `docker compose` itself is the
supervisor (manages lifecycle/logs/restarts), the `m4-signer`/`m4-collector` UIDs are created **at
image build time** (Dockerfile, version-controlled, identical on every container built from the
image), and there is no longer any Python script spawning a process at all — no more GC warning,
no more hand-rolled pidfile.

**REV2**, answering `PHASE1B-M4-AMENDMENT-08-SIGNING-CLEANUP-CORRECTION-REVIEW-2-VI.md`
F-A08-R2-01/02:

- **F-A08-R2-01**: REV1 still put the 3 real keys into `m4-signer`'s `environment:` (`${VAR}`
  interpolation) — `docker inspect m4-signer` revealed the plaintext value in `Config.Env`. REV2
  moves the 3 keys to **files, bind-mounted READ-ONLY** from a host directory the operator
  prepares (chowned to the exact `m4-signer` UID=5001/GID `m4-signing-ipc`=5000, chmod
  owner-only) — `environment:` now only holds a FILE PATH (`..._FILE`), never a value.
  `stage0p_signing_service.py` (`_read_secret_env_or_file`) independently re-verifies file
  permissions at startup (not just trusting the host bind-mount to preserve them — see §3),
  refusing to start if the file has any group/other bit or the wrong owner.
- **F-A08-R2-02**: REV1's `signing_probe.py` handed `M4_SIGNING_AUTH_VERIFY_KEY_B64` (a symmetric
  key) to the `m4-collector` identity itself so it could self-sign a canary token — in theory the
  collector could mint an authorization for ANY content, defeating the signer/collector boundary.
  REV2 splits `probe` into 2 subcommands run under 2 different identities: `mint-token` (operator
  identity, HOLDS the key) + `submit` (the REAL `m4-collector` identity, NEVER receives the key —
  only a pre-signed, single-use token good for 20 seconds and valid only for the fixed canary
  content) — see §4.

**REV3 (current)**, answering `PHASE1B-M4-AMENDMENT-08-SIGNING-CLEANUP-CORRECTION-REVIEW-3-VI.md`
F-A08-R3-01/02:

- **F-A08-R3-01 (a real bug in REV2's own runbook, not theoretical)**: REV2 created
  `/run/m4-signing-secrets` with `install -d -o root -g root` (only root can traverse it) while
  `m4-signer` runs as UID `5001` — signer could NEVER open any file inside, even with correct
  per-file permissions, because it lacked `--x` on the PARENT directory itself. REV3 fixes the
  `install -d` command to chown the directory to the CORRECT UID `5001`/GID `5000`, and adds a
  dedicated fail-closed check for the parent directory
  (`_validate_secret_parent_directory()`, same pattern as `_validate_socket_directory()`) — not
  just per-file checks like REV2.
- **F-A08-R3-02**: two operational gaps — (a) `submit` still used `-e NAME="$TOKEN"` (with `=`)
  for the token instead of the bare form used for every other secret; (b) the runbook exported the
  3 keys/2 PINs/token into the operator's shell but never instructed `unset` after the ceremony,
  contradicting the "only exists for the ceremony's duration" description. REV3 fixes both — see
  §4/§6.

**REV4 (current)**, answering `PHASE1B-M4-AMENDMENT-10-EXECUTION-ATTEMPT-1-ABORT-REVIEW-VI.md`:

- **Image-freshness gap (Amendment 10 Attempt 1, NOT a signer/collector boundary bug)**:
  `m4-signer` uses its own image (`alpha3s-m4-signer`), built from the SAME `Dockerfile` as `api`
  but NOT listed in `deploy.sh SERVICES` — a normal deploy never rebuilds it. `docker compose up
  -d` (without `--build`) only builds an image if it doesn't already exist; after the first build
  (Amendment 09), every subsequent `up -d` SILENTLY reused the stale cached image, even after
  `main`/the deployed commit had a fix (PR #13's `.dockerignore`) — the `.env` bug "recurred" in
  Amendment 10 Attempt 1 despite the code having been correct for hours, purely because the image
  was never rebuilt. REV4 adds an `ARG GIT_COMMIT`/`LABEL git_commit` to the `Dockerfile` plus a
  mandatory explicit build + label-match verification against `git rev-parse HEAD` before EVERY
  `up -d m4-signer` — see §2/§3/§9.

## 1. Full ceremony sequence (summary — see runner docstring for PIN/approval detail)

```
record-approval (staff 3, own PIN)
  -> build m4-signer + verify git_commit label matches deployed HEAD  <-- NEW step (REV4)
  -> prepare 3 key files in /run/m4-signing-secrets (chown/chmod)   <-- NEW step (F-A08-R2-01)
  -> provision-keys (3 fresh, randomly generated keys, SAME values just written to file)
  -> docker compose --profile m4-signing up -d m4-signer   <-- NEW step (A08-COR-01)
  -> mint-token (operator identity, holds the key)          <-- NEW step (F-A08-R2-02)
  -> submit (canary, m4-collector identity, does NOT hold the key) <-- NEW step (F-A08-R1-03/F-A08-R2-02)
  -> run --dry-run (confirm preflight)
  -> run (real execute, runs UNDER m4-collector UID)        <-- NEW step (A08-COR-01)
  -> docker compose --profile m4-signing stop m4-signer     <-- NEW step (A08-COR-01)
  -> retire-keys
  -> delete the 3 key files in /run/m4-signing-secrets       <-- NEW step (F-A08-R2-01)
  -> record-approval --revoke
```

## 2. Mandatory preflight before start

```bash
docker compose -f docker-compose.prod.yml --profile m4-signing ps m4-signer
```

Confirm: no `m4-signer` container is currently `Up` (if one is, `stop` it first — see §6);
deployed HEAD matches the CA-accepted commit (`git rev-parse HEAD`);
`m4_stage0p_transcript_signing_keys`/`m4_stage0p_signing_auth_keys` have no active old key (if
any, `retire-keys` first).

**REV4 — mandatory, answering `PHASE1B-M4-AMENDMENT-10-EXECUTION-ATTEMPT-1-ABORT-REVIEW-VI.md`**:
`m4-signer` is a dormant/profile-only service, **NOT listed in `deploy.sh SERVICES`** — a normal
deploy (`api`/`worker`/bots/`dashboard`) NEVER rebuilds this image. `docker compose ... up -d`
(without `--build`) only builds an image if it doesn't already exist — if it does (from a prior
ceremony), `up` will **silently reuse the old cached image**, regardless of whether source/the
deployed commit changed since (Amendment 10 Attempt 1 hit exactly this: an image cached from
Amendment 09, before PR #13, made the already-fixed `.env` bug "recur" despite merging/deploying
the right commit). **§3 below therefore ALWAYS builds explicitly + verifies the commit label
BEFORE every `up -d m4-signer`, no exceptions, even if you believe the image "should still be
fresh".**

## 3. Start — launch the signing service via docker compose

**REV4 (Correction 2, answering `PHASE1B-M4-SIGNER-IMAGE-FRESHNESS-CORRECTION-REVIEW-1-VI.md`
F-IMG-01) — build explicitly BEFORE `up`, verify the EXACT image Compose will run matches the
deployed commit (NO `--pull`, NO changing the base image):**

**F-IMG-01**: do NOT hard-code the tag `alpha3s-m4-signer:latest` — this name is derived by
Compose from the project name (`COMPOSE_PROJECT_NAME`/directory name/compose file `name:`), which
can differ between runs. Hard-coding it risks the guard inspecting a stale/unrelated old image
while Compose actually runs a different one — a false green that no longer catches the Amendment
10 Attempt 1 failure mode. **Note**: `docker compose config --images m4-signer` lists the
dependency's image too (`redis:7-alpine`, via `depends_on`), NOT only `m4-signer` — do not use that
value directly. Resolve the exact identifier via `config --format json`/`jq` (confirmed present on
the VPS): read `.services["m4-signer"].image` if Compose ever sets it explicitly, otherwise
(today's real case — only `build:`, no `image:`) construct it from the project name Compose itself
resolved (`.name` in the SAME JSON, not an assumed `"alpha3s"`) following Compose's documented
default naming convention (`${project}-${service}`):

```bash
GIT_COMMIT=$(git rev-parse HEAD)

CONFIG_JSON=$(docker compose -f docker-compose.prod.yml --profile m4-signing config --format json)
IMAGE_REF=$(echo "$CONFIG_JSON" | jq -r '.services["m4-signer"].image // empty')
if [ -z "$IMAGE_REF" ]; then
  PROJECT_NAME=$(echo "$CONFIG_JSON" | jq -r '.name')
  if [ -z "$PROJECT_NAME" ] || [ "$PROJECT_NAME" = "null" ]; then
    echo "ERROR: could not resolve the Compose project name - STOP" >&2
    exit 1
  fi
  IMAGE_REF="${PROJECT_NAME}-m4-signer"
fi
echo "resolved image_ref: $IMAGE_REF"

GIT_COMMIT="$GIT_COMMIT" docker compose -f docker-compose.prod.yml --profile m4-signing build m4-signer

IMAGE_COMMIT=$(docker inspect "$IMAGE_REF" --format '{{index .Config.Labels "git_commit"}}' 2>/dev/null)
if [ -z "$IMAGE_COMMIT" ] || [ "$IMAGE_COMMIT" = "<no value>" ] || [ "$IMAGE_COMMIT" = "unknown" ] || [ "$IMAGE_COMMIT" != "$GIT_COMMIT" ]; then
  echo "ERROR: m4-signer image ($IMAGE_REF, label git_commit=$IMAGE_COMMIT) does NOT match deployed HEAD ($GIT_COMMIT) - STOP, do not up -d" >&2
  exit 1
fi
echo "OK: m4-signer image ($IMAGE_REF) matches deployed commit $GIT_COMMIT"
```

`IMAGE_REF` always reflects the EXACT identifier the `up -d m4-signer` step below will use,
regardless of project name — both the `.image` branch (if Compose ever sets it explicitly) and the
`${project}-service` fallback are read FROM the SAME JSON output of the SAME invocation context
(`-f`/`--profile`/current directory) that will run `build`/`up`, never a separately guessed value.
Verified in practice on the VPS (not theoretical): `docker compose ... config --format json | jq
-r '.name'` correctly tracks `COMPOSE_PROJECT_NAME`/`-p` (e.g. `alpha3s` → `differentproj` yields
`differentproj-m4-signer`) — hard-coding `alpha3s-m4-signer:latest` would have made the guard
inspect an unrelated (or nonexistent) image instead of the one Compose actually selected.

The guard fails closed in all 3 cases: (a) `IMAGE_REF` doesn't resolve (empty), (b) the label is
empty/`<no value>`/`unknown` (an image built before REV4, never labeled), (c) the label has a
value but it doesn't match `git rev-parse HEAD`.

Only proceed to the rest below (secret prep + `up -d`) AFTER the `OK:` line appears — if it prints
`ERROR:`, stop immediately, do not `up -d` an unverified image, and report back (do not self-fix
with `--pull` or by editing the Dockerfile mid-ceremony).

**F-A08-R2-01: the 3 keys MUST live in FILES (no longer `environment:`/`${VAR}` like REV1)** —
prepare the directory + files BEFORE `up` (every command below runs as root on the VPS, e.g. the
confirmed root SSH access — see `docs/VPS-RUNBOOK-EN.md`):

```bash
# F-A08-R3-01: the directory MUST be chowned to the CORRECT m4-signer UID (5001)/m4-signing-ipc
# GID (5000) - do NOT leave it root:root (this was a real REV2 bug: signer couldn't traverse INTO
# the directory even with correct per-file permissions, and the service now refuses to start at a
# dedicated parent-directory check, see _validate_secret_parent_directory() in
# stage0p_signing_service.py).
install -d -m 0700 -o 5001 -g 5000 /run/m4-signing-secrets   # /run is tmpfs (RAM) - no disk touched

umask 077
openssl rand -base64 32 > /run/m4-signing-secrets/sample_key
openssl rand -base64 32 > /run/m4-signing-secrets/transcript_hmac_key
openssl rand -base64 32 > /run/m4-signing-secrets/signing_auth_key

# 5001 = m4-signer UID, 5000 = m4-signing-ipc GID (Dockerfile, FIXED, unchanged) - ONLY this UID
# can read the file (owner-only, mode 0400 - no group/other even if the group matches).
chown 5001:5000 /run/m4-signing-secrets/*
chmod 0400 /run/m4-signing-secrets/*
```

Give the SAME 3 values just generated to `provision-keys` (read the files back to get the values,
using the bare `-e NAME` form — see §5 for why):

```bash
export M4_SAMPLE_KEY_B64=$(cat /run/m4-signing-secrets/sample_key)
export M4_TRANSCRIPT_HMAC_KEY_B64=$(cat /run/m4-signing-secrets/transcript_hmac_key)
export M4_SIGNING_AUTH_VERIFY_KEY_B64=$(cat /run/m4-signing-secrets/signing_auth_key)
docker compose -f docker-compose.prod.yml exec \
  -e M4_SAMPLE_KEY_B64 -e M4_TRANSCRIPT_HMAC_KEY_B64 -e M4_SIGNING_AUTH_VERIFY_KEY_B64 \
  api python scripts/m4_stage0p_rehearsal_runner.py provision-keys
```

**No further `export` is needed to `up`** — `docker-compose.prod.yml` already points `..._FILE`
at the fixed path above, and no longer reads any `${VAR}` from the shell (unlike REV1):

```bash
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

If the `chown`/`chmod` above was skipped or wrong (e.g. a world-readable file, or the wrong owner)
— **OR if the `/run/m4-signing-secrets` directory itself has the wrong owner/permissions**
(F-A08-R3-01: this was a real REV2 bug — a `root:root` directory left signer unable to even
traverse INTO it despite correct per-file permissions) — `m4-signer` **detects this itself and
refuses to start**, at BOTH layers: the parent directory
(`_validate_secret_parent_directory()`, checked BEFORE touching any file) and each file
(`_read_secret_env_or_file()` re-`stat()`s each file — not just trusting the host bind-mount to
preserve permissions, the same defense-in-depth philosophy already applied to the socket
directory): `docker compose logs m4-signer` will show `"...thu muc cha ... khong thuoc so
huu..."`/`"...thu muc cha ... qua rong quyen..."` (directory error) or `"...qua rong quyen..."`/
`"...khong thuoc so huu tien trinh nay..."` (per-file error) — fix the directory/file permissions
and `up -d m4-signer` again.

## 4. Canary probe — confirm the REAL signing path works (F-A08-R1-03/F-A08-R2-02)

Compose's `healthcheck` only proves **the process is listening** (socket file exists with the
right mode) — it does NOT prove peer-UID/rate-limit/nonce/signature/canonicalize/encrypt/sign
actually work end to end. The real canary probe (fully synthetic data, no DB write, no
rehearsal/customer data touched) is **split into 2 steps, run under 2 DIFFERENT identities**
(F-A08-R2-02: REV1 handed the key to the `m4-collector` identity itself, letting collector mint
an authorization for any content — defeating the signer/collector boundary; REV2 fixes this by
never letting `m4-collector` hold the key):

**Step 1 — `mint-token`, operator identity (NOT `--user m4-collector`), NEEDS the key:**

```bash
export M4_SIGNING_PROBE_TOKEN=$(docker compose -f docker-compose.prod.yml exec \
  -e M4_SIGNING_AUTH_VERIFY_KEY_B64 \
  api python scripts/m4_stage0p_signing_probe.py mint-token)
```

Signs a SINGLE `signing_authorization` for the fixed canary content (20-second TTL, single-use —
consumes a Redis nonce exactly like a real request), printing one base64(JSON) line with the token
plus the request's descriptive fields (sample_id/txid/canonical_digest_hex/...) — NEVER containing
the key in any form. **F-A08-R3-02**: `export` DIRECTLY into `M4_SIGNING_PROBE_TOKEN` (not a
separate temp variable like REV2's `TOKEN`) — same name `submit` reads, letting step 2 use the
same bare `-e` form as everything else (no need to keep 2 names for 1 value).

**Step 2 — `submit`, the REAL `m4-collector` identity, does NOT need and must NOT be given the
key:**

```bash
docker compose -f docker-compose.prod.yml exec --user m4-collector \
  -e M4_SIGNING_PROBE_TOKEN \
  api python scripts/m4_stage0p_signing_probe.py submit
```

`submit` has no code path that reads `M4_SIGNING_AUTH_VERIFY_KEY_B64` (proven by an automated
static audit, `scripts/m4_stage0p_signing_probe_test.py` [P-08]) — even if that value were
accidentally present in the `exec` command's environment, `submit` never uses it (evidence
[P-09]). If anyone tampers with a field in `$M4_SIGNING_PROBE_TOKEN` before `submit` (e.g.
changing `sample_id`), the service rejects it because the signature no longer matches —
`m4-collector` can only replay the EXACT token it was given, never mint a different one (evidence
[P-10]).

**Note the `-e NAME` form (NO `=value`, F-A08-R1-02, applied CONSISTENTLY to every value including
the token — F-A08-R3-02 fixes the one place REV2 still used `=`)** — this is deliberate, not a
typo. The `-e NAME="$NAME"` form puts the value as a literal argv token of the `docker`/`docker
compose` client process on the host (readable by anyone with `ps aux`/`/proc/<pid>/cmdline` access
on the host while the command is running). The bare `-e NAME` form tells the Docker client to read
the value from its OWN environment and forward it over the Docker API — the value is never an
argv token (empirically verified: `docker exec -e VAR <container> printenv VAR` returns the
correct value even though `VAR` never appears with `=value` on the command line).

A `{"event": "m4_signing_probe_ok", "ok": true, ...}` JSON output confirms: the `m4-collector`
peer UID is accepted by the service, the rate-limit/nonce/`signing_authorization` signature all
check out, and the service genuinely canonicalizes + encrypts + signs successfully. `ok: false` →
see §8 (rollback/troubleshooting), **do not proceed with the ceremony**.

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

**F-A08-R2-01: delete the 3 key files RIGHT AFTER `stop`** (even though `/run` is tmpfs — no disk
ever touched — deleting still closes the readable window as early as possible, matching the same
"only exists for the ceremony's duration" philosophy REV1 applied to environment variables):

```bash
rm -f /run/m4-signing-secrets/sample_key /run/m4-signing-secrets/transcript_hmac_key \
  /run/m4-signing-secrets/signing_auth_key
```

**F-A08-R3-02: `unset` ALL operator shell variables RIGHT AFTER** — the runbook previously exported
these but never instructed cleaning them from the shell, contradicting the "only exists for the
ceremony's duration" description (§7). Run this in the SAME shell session that `export`ed them
(REQUIRED whether the ceremony **succeeded, failed, or was emergency-stopped** — no exception):

```bash
unset M4_SAMPLE_KEY_B64 M4_TRANSCRIPT_HMAC_KEY_B64 M4_SIGNING_AUTH_VERIFY_KEY_B64 \
  M4_SIGNING_PROBE_TOKEN STAGE0P_REHEARSAL_OPERATOR_PIN STAGE0P_REHEARSAL_REVIEWER_PIN
```

Confirm clean (name + `absent`/`SET` status only, NEVER the value — see §9):

```bash
for VAR in M4_SAMPLE_KEY_B64 M4_TRANSCRIPT_HMAC_KEY_B64 M4_SIGNING_AUTH_VERIFY_KEY_B64 \
           M4_SIGNING_PROBE_TOKEN STAGE0P_REHEARSAL_OPERATOR_PIN STAGE0P_REHEARSAL_REVIEWER_PIN; do
  if [ -z "${!VAR+x}" ]; then echo "$VAR: absent"; else echo "$VAR: STILL SET - unset again"; fi
done
```

If the ceremony stops in an emergency (§8) — run BOTH blocks here (delete the files above + the
`unset` above) as the final cleanup step, no matter which step it stopped at.

## 7. Key lifecycle summary

| Key | Generated where | Lives where | Retired when |
|---|---|---|---|
| `M4_SAMPLE_KEY_B64` | Operator runs `openssl rand -base64 32` before `provision-keys` (§3) | `/run/m4-signing-secrets/sample_key` (file, chown 5001:5000/chmod 0400, bind-mounted READ-ONLY into `m4-signer`) + the operator's shell environment (given to `provision-keys`, `run`/prediction writer — see §5) — no DB table stores it | No DB "retire" needed — delete the file + stop reusing the value after `stop` (§6) |
| `M4_TRANSCRIPT_HMAC_KEY_B64` | Same time | `m4_stage0p_transcript_signing_keys` (DB) + `/run/m4-signing-secrets/transcript_hmac_key` (file) | `retire-keys` (DB) AFTER `stop`, delete the file (§6) |
| `M4_SIGNING_AUTH_VERIFY_KEY_B64` | Same time | `m4_stage0p_signing_auth_keys` (DB) + `/run/m4-signing-secrets/signing_auth_key` (file) + the operator keeps it in shell to run `mint-token` (§4) | `retire-keys` (DB) AFTER `stop`, delete the file (§6) |

**F-A08-R2-01 (REV2)**: `m4-signer` no longer receives key values via `environment:`/`${VAR}`
(REV1) — it ONLY receives 3 FILE PATHS (`..._FILE`, see `docker-compose.prod.yml`), read via
`_read_secret_env_or_file()` (`stage0p_signing_service.py`), which independently re-verifies file
permissions/ownership at startup (§3). The files live in `/run` (tmpfs, RAM-backed, no disk
persistence, cleared on reboot) — they only exist for the ceremony's duration, explicitly deleted
after `stop` (§6).

The 3 keys ONLY ever exist: (a) in the files `/run/m4-signing-secrets/*` (read by `m4-signer`,
deleted in §6), and (b) in the operator's shell environment (given to
`provision-keys`/`mint-token`/`run` via `exec -e <NAME>` in bare form, no `=value` — see §4/§5,
**`unset` required in §6 after the ceremony, F-A08-R3-02**) — never written to `.env`, a log, or
an evidence artifact.

**Remaining inherent limitations, stated plainly — 2 DIFFERENT channels, do not conflate them**:

1. **The host-side secret files** (`/run/m4-signing-secrets/*`): anyone with root on the host can
   read them directly (`cat` the file) — this is an inherent limitation of ANY file-based secret
   design on a shared host (not specific to this design); mitigated by 0400 permissions/correct
   ownership + tmpfs (no long-lived on-disk persistence) + explicit deletion after `stop`.
2. **Secrets passed at `exec` time** (§3/§4/§5: `M4_SAMPLE_KEY_B64`/`M4_TRANSCRIPT_HMAC_KEY_B64`/
   `M4_SIGNING_AUTH_VERIFY_KEY_B64` for `provision-keys`, `M4_SIGNING_AUTH_VERIFY_KEY_B64` for
   `mint-token`, `M4_SIGNING_PROBE_TOKEN` for `submit`,
   `STAGE0P_REHEARSAL_OPERATOR_PIN`/`STAGE0P_REHEARSAL_REVIEWER_PIN`/`M4_SAMPLE_KEY_B64` for
   execute) are NOT part of the container's `Config.Env` (`docker exec -e` is a per-exec-session
   override, not persisted), so `docker inspect` does NOT reveal these — the bare `-e NAME` form
   (F-A08-R3-02: now applied CONSISTENTLY across §3/§4/§5, including the token) closes the one
   remaining leak channel (the host-side client process's own argv).

Both cases: anyone with root/Docker API access on the host already has the ability to read `.env`
or connect to the DB directly — neither expands the attack surface beyond that existing access
level.

## 8. Rollback / troubleshooting

| Situation | Action |
|---|---|
| `git_commit` label mismatch at the §3 build step (REV4) | The `m4-signer` image was built from a commit older than the current deployed HEAD — do **NOT** `up -d`; rerun exactly the `build` command in §3 (no `--pull`, no editing the Dockerfile mid-ceremony); if it still mismatches, stop and report to CA/PO — the VPS deployed HEAD may not match the accepted gate |
| `up -d m4-signer` reports `signing service tu choi khoi dong: ... chua duoc dat day du` | The key files don't exist yet under `/run/m4-signing-secrets/` — redo §3 (`openssl rand` + `chown`/`chmod`) |
| `up -d m4-signer` reports `... qua rong quyen (mode=...)` | One of the 3 files has a group/other bit — `chmod 0400 /run/m4-signing-secrets/*` and retry |
| `up -d m4-signer` reports `... khong thuoc so huu tien trinh nay` | One of the 3 files has the wrong owner — `chown 5001:5000 /run/m4-signing-secrets/*` and retry |
| `up -d m4-signer` reports `thu muc cha cua secret file khong thuoc so huu tien trinh nay` (F-A08-R3-01) | The `/run/m4-signing-secrets` directory itself has the wrong owner (e.g. still `root:root` from an old `install -d`) — `chown 5001:5000 /run/m4-signing-secrets` (the directory, NOT just the files inside) and retry; confirm §3's `install -d -m 0700 -o 5001 -g 5000` command was used |
| `up -d m4-signer` reports `thu muc cha cua secret file qua rong quyen` | The directory has a group/other bit — `chmod 0700 /run/m4-signing-secrets` and retry |
| `ps m4-signer` shows `Exited`/`unhealthy` | `docker compose logs m4-signer --tail 50` to read the REAL reason (e.g. `_validate_socket_directory` or `_read_secret_env_or_file`/`_validate_secret_parent_directory` refusal) — do NOT retry blindly |
| `mint-token`/`submit` reports `ok: false` | Check `docker compose ps m4-signer` is still `Up`; confirm `M4_SIGNING_AUTH_VERIFY_KEY_B64` passed to `mint-token` EXACTLY matches the value written to `/run/m4-signing-secrets/signing_auth_key` (a mismatch = signature fails, safe but useless); if `submit` fails after `mint-token` succeeded, check `$M4_SIGNING_PROBE_TOKEN` wasn't truncated/corrupted (`echo -n "$M4_SIGNING_PROBE_TOKEN" | wc -c` to check length, NEVER print the value) |
| Execute reports `SigningServiceError: khong ket noi duoc signing service` | Confirm `ps m4-signer` is still `Up`; confirm `--user m4-collector` and `M4_STAGE0P_SIGNING_SOCKET` were passed correctly to the `exec` command |
| Execute reports "chua co signing_auth_key hieu luc" | The keys given to `provision-keys` (DB) and the ones in `/run/m4-signing-secrets/` (given to `up -d m4-signer`) do NOT match (e.g. a `retire-keys` ran in between) — `stop`, `retire-keys`, generate FRESH keys (overwrite both the 3 files and the DB), redo from `provision-keys` |
| Need an emergency stop | `docker compose --profile m4-signing stop m4-signer` (SIGTERM, Docker sends SIGKILL after its default timeout if needed) — safe to call any time |
| `m4-signer` crashes mid-rehearsal | **Does NOT auto-recover** (`restart: "no"` is deliberate) — the collector fails closed on its own after a few retries (see `COLLECTOR_MAX_ATTEMPTS`/`_run_collector_with_retry` in the runner), and the runner's own cleanup terminalizes the batch to `'aborted'`. Check `m4-signer`'s logs (if the container is still around, `docker compose logs`) to find the crash cause before attempting a new ceremony — do not `up -d` again mid-gate |

## 9. Evidence commands (no secret leakage)

**REV4 — image-freshness proof (run AFTER §3's build, BEFORE `up -d`; F-IMG-01: resolve the
identifier via `config --format json`/`jq`, do NOT hard-code a tag, do NOT use `config --images
<service>` directly since it also lists the dependency's image `redis:7-alpine`):**

```bash
CONFIG_JSON=$(docker compose -f docker-compose.prod.yml --profile m4-signing config --format json)
IMAGE_REF=$(echo "$CONFIG_JSON" | jq -r '.services["m4-signer"].image // empty')
if [ -z "$IMAGE_REF" ]; then
  IMAGE_REF="$(echo "$CONFIG_JSON" | jq -r '.name')-m4-signer"
fi
echo "image_ref=$IMAGE_REF"
docker inspect "$IMAGE_REF" --format 'git_commit={{index .Config.Labels "git_commit"}}'
git rev-parse HEAD
# The label vs git rev-parse HEAD MUST match exactly - proof the image is not a stale cache AND is
# the actual image Compose will run (not a guessed/hard-coded tag).
```

```bash
docker compose -f docker-compose.prod.yml --profile m4-signing ps m4-signer
docker compose -f docker-compose.prod.yml logs m4-signer --tail 50
docker compose -f docker-compose.prod.yml exec api printenv | grep -iE "M4_SAMPLE_KEY|TRANSCRIPT_HMAC_KEY|SIGNING_AUTH_VERIFY_KEY"  # MUST be empty inside the api container - keys only live in m4-signer's mounted file

# F-A08-R2-01: confirm docker inspect does NOT reveal the key value (only the mount path, not the
# secret) - the grep below has nothing to match against (no real value exists to find); it just
# confirms Config.Env/Mounts never contain an "=" right after a key variable name.
docker inspect $(docker compose -f docker-compose.prod.yml --profile m4-signing ps -q m4-signer) \
  --format '{{json .Config.Env}}' | grep -oE "M4_(SAMPLE|TRANSCRIPT_HMAC|SIGNING_AUTH_VERIFY)_KEY_B64=[^,\"]+"
# MUST return no lines (Config.Env only has "..._FILE=/run/m4-signing-secrets/..." - a path, not a
# value) - if any line matches the pattern above, stop immediately and report to CA.
```

The `printenv` line is an important independent proof: run inside `api` (where the collector/
runner live), the 3 key variables MUST **not appear** — if they do, stop immediately and report to
CA. The `docker inspect` line confirms `m4-signer`'s OWN `Config.Env` no longer holds a plaintext
value either (F-A08-R2-01) — only a file path remains.

**F-A08-R3-02 — operator shell cleanup proof** (run AFTER the `unset` in §6, name + status only,
NEVER the value even if still `SET`):

```bash
for VAR in M4_SAMPLE_KEY_B64 M4_TRANSCRIPT_HMAC_KEY_B64 M4_SIGNING_AUTH_VERIFY_KEY_B64 \
           M4_SIGNING_PROBE_TOKEN STAGE0P_REHEARSAL_OPERATOR_PIN STAGE0P_REHEARSAL_REVIEWER_PIN; do
  if [ -z "${!VAR+x}" ]; then echo "$VAR: absent"; else echo "$VAR: STILL SET"; fi
done
ls -la /run/m4-signing-secrets/ 2>&1   # MUST report "No such file or directory" or an empty
                                        # directory (all 3 files deleted) after §6
```

All 6 variables MUST report `absent` AND `/run/m4-signing-secrets/` MUST be empty/gone — if not,
`unset`/`rm -f` again immediately (§6), never carry over into the next SSH session.
