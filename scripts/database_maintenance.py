#!/usr/bin/env python3
"""Audit or apply bounded production database retention through the admin API.

The script intentionally never receives DATABASE_URL and never emits credentials,
row contents, email addresses, IPs, or cookies. GitHub Actions supplies the normal
administrator login and stores only aggregate before/after evidence as an artifact.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import requests


DEFAULT_BASE = "https://swimtech.vercel.app"
CONFIRMATION = "DELETE_EXPIRED_QA_ACTIVITY"


def _request_json(response: requests.Response) -> dict:
    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError(
            f"maintenance API returned non-JSON response ({response.status_code})"
        ) from exc
    if response.status_code >= 400:
        detail = str(payload.get("detail") or payload.get("error") or "request failed")
        raise RuntimeError(f"maintenance API failed ({response.status_code}): {detail[:240]}")
    return payload


def run(mode: str, base: str, qa_days: int, regular_days: int) -> dict:
    admin_id = os.getenv("ADMIN_ID", "").strip()
    admin_pw = os.getenv("ADMIN_PW", "")
    if not admin_id or not admin_pw:
        raise RuntimeError("ADMIN_ID and ADMIN_PW are required")

    session = requests.Session()
    login = session.post(
        f"{base.rstrip('/')}/auth/login",
        json={"username": admin_id, "password": admin_pw},
        timeout=120,
    )
    _request_json(login)

    params = {
        "qa_log_retention_days": qa_days,
        "regular_log_retention_days": regular_days,
    }
    if mode == "audit":
        response = session.get(
            f"{base.rstrip('/')}/api/admin/maintenance/database-audit",
            params=params,
            timeout=180,
        )
    else:
        response = session.post(
            f"{base.rstrip('/')}/api/admin/maintenance/database-cleanup",
            json={
                "dry_run": mode != "apply",
                "confirm": CONFIRMATION if mode == "apply" else None,
                **params,
            },
            timeout=300,
        )
    result = _request_json(response)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "base": base,
        "mode": mode,
        "privacy_scope": "aggregate counts and table statistics only; no row data or credentials",
        "result": result,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("audit", "dry-run", "apply"), default="audit")
    parser.add_argument("--base", default=os.getenv("QA_BASE_URL", DEFAULT_BASE))
    parser.add_argument("--qa-days", type=int, default=3)
    parser.add_argument("--regular-days", type=int, default=90)
    parser.add_argument("--output", default="database_maintenance_report.json")
    args = parser.parse_args()
    if not 1 <= args.qa_days <= 30:
        parser.error("--qa-days must be between 1 and 30")
    if not 30 <= args.regular_days <= 365:
        parser.error("--regular-days must be between 30 and 365")

    report = run(args.mode, args.base, args.qa_days, args.regular_days)
    Path(args.output).write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    result = report["result"]
    if args.mode == "audit":
        activity = result.get("activity") or {}
        print(
            "Database audit: "
            f"rows={activity.get('total_rows', 0)}, "
            f"qa={activity.get('qa_rows', 0)}, "
            f"expired_qa={activity.get('expired_qa_rows', 0)}, "
            f"bytes={result.get('database_bytes', 0)}"
        )
    else:
        deleted = result.get("deleted") or {}
        planned = result.get("planned") or {}
        print(
            f"Database maintenance {result.get('status')}: "
            f"planned_qa={planned.get('expired_qa_activity', 0)}, "
            f"deleted={deleted.get('total', 0)}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
