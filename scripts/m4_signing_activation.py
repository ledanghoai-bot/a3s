"""M4 — CLI Production Signing Activation (Tier B). Design 71/72.

Flow: request → preflight → approve (SoD) → activate → (close) | revoke | (auto expire).
KHONG nhan secret qua argument/env/history (digest/scope/ticket khong phai secret). Moi buoc audit.
CHUA cap production signing — day chi cap capability co scope+TTL; rehearsal khong cham dat.

Vi du:
  python scripts/m4_signing_activation.py request --request-id R1 --digest <sha256> \
     --scope '{"tenant":"internal","batch":"eval-1"}' --ticket T-1 --reason "..." \
     --requester-staff-id 5 --rollback-owner hoai --actor signer1
  python scripts/m4_signing_activation.py preflight --activation-id <id> --actor system
  python scripts/m4_signing_activation.py approve --activation-id <id> --approver-staff-id 1 \
     --window-minutes 30 --actor hoai
  python scripts/m4_signing_activation.py activate --activation-id <id> --activator-staff-id 5 --actor signer1
  python scripts/m4_signing_activation.py revoke --activation-id <id> --reason "..." --actor hoai
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db_pool import close_pool  # noqa: E402
from app.services.m4_signing import activation as A  # noqa: E402


def _out(obj):
    print(json.dumps(obj, ensure_ascii=False, default=str, indent=2))


async def _run(args) -> int:
    try:
        if args.command == "request":
            r = await A.create_request(
                request_id=args.request_id, scope=json.loads(args.scope),
                artifact_digest=args.digest, manifest_ref=args.manifest,
                max_sign_count=args.max_sign, reason=args.reason, ticket=args.ticket,
                requester_staff_id=args.requester_staff_id, delegated_by=args.delegated_by,
                rollback_owner=args.rollback_owner, actor=args.actor)
            _out({"activation_id": str(r["activation_id"]), "state": r["state"]})
        elif args.command == "preflight":
            _out(await A.run_preflight(args.activation_id, actor=args.actor))
        elif args.command == "approve":
            r = await A.approve(args.activation_id, approver_staff_id=args.approver_staff_id,
                                actor=args.actor, window_minutes=args.window_minutes,
                                emergency=args.emergency, emergency_reason=args.emergency_reason)
            _out({"state": r["state"], "window_end": str(r["window_end"])})
        elif args.command == "activate":
            _out(await A.activate(args.activation_id, activator_staff_id=args.activator_staff_id,
                                  actor=args.actor))
        elif args.command == "revoke":
            r = await A.revoke(args.activation_id, actor=args.actor, reason=args.reason,
                               staff_id=args.staff_id)
            _out({"state": r["state"], "terminal_reason": r["terminal_reason"]})
        elif args.command == "close":
            r = await A.close(args.activation_id, actor=args.actor, staff_id=args.staff_id)
            _out({"state": r["state"]})
        elif args.command == "status":
            r = await A.get(args.activation_id)
            _out(None if r is None else {"activation_id": str(r["activation_id"]),
                                         "state": r["state"], "digest": r["artifact_digest"],
                                         "window_end": str(r["window_end"])})
        elif args.command == "expire-due":
            _out({"expired": await A.expire_due()})
        return 0
    except A.ActivationError as e:
        print(f"Loi: {e}")
        return 2
    finally:
        await close_pool()


def main() -> int:
    p = argparse.ArgumentParser(description="M4 Production Signing Activation (Tier B)")
    sub = p.add_subparsers(dest="command", required=True)

    q = sub.add_parser("request")
    q.add_argument("--request-id", required=True)
    q.add_argument("--scope", required=True, help="JSON boundary (KHONG secret)")
    q.add_argument("--digest", required=True, help="artifact_digest (khoa boundary)")
    q.add_argument("--manifest", default=None)
    q.add_argument("--max-sign", type=int, default=1)
    q.add_argument("--ticket", required=True)
    q.add_argument("--reason", required=True)
    q.add_argument("--requester-staff-id", type=int, required=True)
    q.add_argument("--delegated-by", default=None)
    q.add_argument("--rollback-owner", required=True)
    q.add_argument("--actor", required=True)

    for name in ("preflight", "status"):
        s = sub.add_parser(name)
        s.add_argument("--activation-id", required=True)
        if name == "preflight":
            s.add_argument("--actor", required=True)

    s = sub.add_parser("approve")
    s.add_argument("--activation-id", required=True)
    s.add_argument("--approver-staff-id", type=int, required=True)
    s.add_argument("--window-minutes", type=int, required=True)
    s.add_argument("--actor", required=True)
    s.add_argument("--emergency", action="store_true")
    s.add_argument("--emergency-reason", default=None)

    s = sub.add_parser("activate")
    s.add_argument("--activation-id", required=True)
    s.add_argument("--activator-staff-id", type=int, required=True)
    s.add_argument("--actor", required=True)

    s = sub.add_parser("revoke")
    s.add_argument("--activation-id", required=True)
    s.add_argument("--reason", required=True)
    s.add_argument("--actor", required=True)
    s.add_argument("--staff-id", type=int, default=None)

    s = sub.add_parser("close")
    s.add_argument("--activation-id", required=True)
    s.add_argument("--actor", required=True)
    s.add_argument("--staff-id", type=int, default=None)

    sub.add_parser("expire-due")

    args = p.parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
