#!/usr/bin/env python3
"""Test startup_verdict (PURE) — CA-REVIEW-M0-DEV-003 §6.
Chứng minh fail-closed: DB/query error KHÔNG tạo readiness giả; half-provisioned FAIL; pre-016 chỉ
skip khi non-strict. Không cần DB.
  docker exec -e PYTHONPATH=/srv -w /srv api python scripts/startup_readiness_test.py
"""
import sys

from app.services.permission_service import startup_verdict

_ERR = Exception("db down")
# (provisioned, ready, reason, error, strict) -> expected_ok
CASES = [
    (False, None, None, None, False, True),    # pre-016, non-strict -> skip hợp lệ
    (False, None, None, None, True, False),    # pre-016, STRICT -> FAIL (sai cấu hình)
    (True, True, "ok", None, True, True),      # fully provisioned + strict -> OK
    (True, True, "ok", None, False, True),     # fully provisioned + non-strict -> OK
    (True, False, "half", None, True, False),  # half-provisioned + strict -> FAIL
    (True, False, "half", None, False, False), # half-provisioned + non-strict -> FAIL (bất kể strict)
    (None, None, None, _ERR, True, False),     # DB/query error + STRICT -> FAIL (không readiness giả)
    (None, None, None, _ERR, False, True),     # DB/query error + non-strict -> tolerate (dev boot)
]


def main() -> int:
    fails = []
    for provisioned, ready, reason, error, strict, exp in CASES:
        ok, _ = startup_verdict(provisioned, ready, reason, error, strict)
        if ok != exp:
            fails.append(f"(prov={provisioned},ready={ready},err={error is not None},strict={strict}) "
                         f"got={ok} exp={exp}")
    if fails:
        print("STARTUP_VERDICT FAIL:")
        for f in fails:
            print("  -", f)
        return 1
    print(f"STARTUP_VERDICT PASS ({len(CASES)} cases): error+strict->FAIL (no false readiness); "
          "half-provisioned->FAIL; pre-016 skip chỉ khi non-strict")
    return 0


if __name__ == "__main__":
    sys.exit(main())
