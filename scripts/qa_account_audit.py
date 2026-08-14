"""Audit or explicitly update production QA account classifications.

Credentials are supplied only through environment variables. The JSON artifact
keeps the username required for an explicit update, while excluding email, name,
nickname, IP, cookies, and passwords.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

import requests


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _json(response: requests.Response) -> dict:
    try:
        return response.json()
    except ValueError:
        return {}


def _collect_users(session: requests.Session, base: str, scope: str) -> list[dict]:
    users: list[dict] = []
    page = 1
    while True:
        response = session.get(
            f"{base}/api/admin/users",
            params={"account_scope": scope, "page": page, "page_size": 100},
            timeout=90,
        )
        if response.status_code != 200:
            raise RuntimeError(f"User audit failed for {scope}: HTTP {response.status_code}")
        body = _json(response)
        page_users = body.get("users") or []
        users.extend(page_users)
        if page * int(body.get("page_size") or 100) >= int(body.get("total") or 0):
            return users
        page += 1


def _sanitized_user(user: dict) -> dict:
    evidence = user.get("qa_evidence") or {}
    return {
        "id": user.get("id"),
        "username": user.get("username"),
        "is_qa_account": bool(user.get("is_qa_account")),
        "provider": user.get("provider"),
        "status": user.get("status"),
        "created_at": user.get("created_at"),
        "last_login_at": user.get("last_login_at"),
        "last_activity_at": user.get("last_activity_at"),
        "activity_count": int(user.get("activity_count") or 0),
        "training_log_count": int(user.get("training_log_count") or 0),
        "candidate_confidence": evidence.get("confidence"),
        "candidate_score": int(evidence.get("score") or 0),
        "candidate_reasons": evidence.get("reasons") or [],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=os.getenv("QA_BASE_URL", "https://swimtech.vercel.app"))
    parser.add_argument("--mode", choices=("audit", "apply", "clear"), default="audit")
    parser.add_argument("--usernames", default="")
    parser.add_argument("--output", default="qa_account_audit.json")
    args = parser.parse_args()
    base = args.base.rstrip("/")

    session = requests.Session()
    login = session.post(
        f"{base}/auth/login",
        json={"username": _required_env("ADMIN_ID"), "password": _required_env("ADMIN_PW")},
        timeout=90,
    )
    if login.status_code != 200 or not _json(login).get("is_admin"):
        raise RuntimeError(f"Admin login failed: HTTP {login.status_code}")

    requested = list(dict.fromkeys(
        item.strip() for item in args.usernames.replace("\n", ",").split(",") if item.strip()
    ))
    update_result = None
    if args.mode != "audit":
        if not requested:
            raise RuntimeError("Apply/clear mode requires at least one explicit username")
        response = session.put(
            f"{base}/api/admin/qa-accounts",
            json={"usernames": requested, "is_qa_account": args.mode == "apply"},
            timeout=90,
        )
        if response.status_code != 200:
            raise RuntimeError(f"QA account update failed: HTTP {response.status_code}")
        body = _json(response)
        update_result = {
            "requested_count": len(requested),
            "updated_usernames": [item.get("username") for item in body.get("updated", [])],
            "missing_usernames": body.get("missing") or [],
            "is_qa_account": bool(body.get("is_qa_account")),
        }

    confirmed = _collect_users(session, base, "qa")
    candidates = _collect_users(session, base, "candidate")
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "base": base,
        "mode": args.mode,
        "classification_policy": "explicit admin confirmation; candidate evidence never auto-applies",
        "privacy_scope": "username retained for review; email, name, nickname, IP, cookies, and secrets excluded",
        "confirmed_count": len(confirmed),
        "candidate_count": len(candidates),
        "confirmed_accounts": [_sanitized_user(user) for user in confirmed],
        "candidate_accounts": [_sanitized_user(user) for user in candidates],
        "update_result": update_result,
    }
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"QA account audit complete: confirmed={len(confirmed)}, candidates={len(candidates)}, "
        f"mode={args.mode}, output={args.output}"
    )
    if update_result and update_result["missing_usernames"]:
        print(f"Missing usernames: {len(update_result['missing_usernames'])}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
