"""Authenticated Jira connection endpoints for SwimMate coaches."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from typing import Any

import psycopg2
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from integrations.jira_client import (
    JiraApiError,
    JiraClient,
    JiraConfigurationError,
)
from routers.coach import (
    _ensure_tables,
    _get_customer_id,
    _invalidate_jira_analytics_cache,
    _require_coach,
    _require_user,
)

router = APIRouter()


class JiraIssueRequest(BaseModel):
    summary: str = Field(min_length=3, max_length=200)
    description: str = Field(min_length=1, max_length=5000)
    labels: list[str] = Field(default_factory=list, max_length=10)


def _client() -> JiraClient:
    try:
        return JiraClient()
    except JiraConfigurationError as exc:
        raise HTTPException(503, str(exc)) from exc


def _require_registered_coach(request: Request) -> None:
    username = _require_user(request)
    database_url = os.getenv("DATABASE_URL", "")
    if not database_url:
        raise HTTPException(503, "데이터베이스 연결이 설정되지 않았습니다.")
    conn = psycopg2.connect(database_url)
    try:
        customer_id = _get_customer_id(conn, username)
        cur = conn.cursor()
        try:
            _require_coach(cur, customer_id)
        finally:
            cur.close()
    finally:
        conn.close()


def _verify_jira_webhook_signature(
    raw_body: bytes,
    signature_header: str | None,
    secret: str,
) -> None:
    if not signature_header:
        raise HTTPException(401, "Missing Jira webhook signature")
    if "=" not in signature_header:
        raise HTTPException(401, "Invalid Jira webhook signature")
    method, received = signature_header.split("=", 1)
    method = method.strip().lower()
    received = received.strip()
    if not method or not received:
        raise HTTPException(401, "Invalid Jira webhook signature")
    try:
        hashlib.new(method)
    except ValueError as exc:
        raise HTTPException(400, "Unsupported Jira webhook signature method") from exc
    expected = hmac.new(
        secret.encode("utf-8"),
        msg=raw_body,
        digestmod=method,
    ).hexdigest()
    if not hmac.compare_digest(f"{method}={expected}", f"{method}={received}"):
        raise HTTPException(401, "Invalid Jira webhook signature")


def _jira_local_status(payload: dict[str, Any]) -> dict[str, str] | None:
    issue = payload.get("issue") or {}
    key = str(issue.get("key") or "").strip().upper()
    if not key:
        return None
    event = str(payload.get("webhookEvent") or "")
    fields = issue.get("fields") or {}
    status = fields.get("status") or {}
    status_name = str(status.get("name") or "").strip() or "Jira status unknown"
    status_category = str((status.get("statusCategory") or {}).get("key") or "").lower()
    if event == "jira:issue_deleted":
        local_status = "deleted"
        sync_status = "deleted"
    elif status_category == "done" or fields.get("resolutiondate"):
        local_status = "done"
        sync_status = "synced"
    else:
        local_status = "open"
        sync_status = "synced"
    return {
        "key": key,
        "event": event,
        "status_name": status_name,
        "status_category": status_category or "unknown",
        "local_status": local_status,
        "sync_status": sync_status,
    }


def _apply_jira_webhook_sync(payload: dict[str, Any]) -> dict[str, Any]:
    values = _jira_local_status(payload)
    if not values:
        return {"updated": 0, "matched": False, "reason": "missing_issue_key"}
    database_url = os.getenv("DATABASE_URL", "")
    if not database_url:
        raise HTTPException(503, "DATABASE_URL is not configured")

    _ensure_tables()
    conn = psycopg2.connect(database_url)
    cur = conn.cursor()
    try:
        cur.execute(
            """
            UPDATE coach_action_items
               SET status = %s,
                   sync_status = %s,
                   sync_error = NULL,
                   updated_at = NOW()
             WHERE jira_issue_key = %s
             RETURNING id
            """,
            (values["local_status"], values["sync_status"], values["key"]),
        )
        updated_ids = [int(row[0]) for row in cur.fetchall()]
        conn.commit()
        if updated_ids:
            _invalidate_jira_analytics_cache()
        return {
            "updated": len(updated_ids),
            "matched": bool(updated_ids),
            "issue_key": values["key"],
            "local_status": values["local_status"],
            "jira_status": values["status_name"],
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


@router.get("/status")
def jira_status(request: Request):
    _require_user(request)
    try:
        return _client().connection_status()
    except JiraApiError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc


@router.post("/issues")
def create_jira_issue(body: JiraIssueRequest, request: Request):
    _require_registered_coach(request)
    try:
        return _client().create_issue(
            summary=body.summary.strip(),
            description=body.description.strip(),
            labels=body.labels,
        )
    except JiraApiError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc


@router.post("/webhook")
async def jira_webhook(request: Request):
    secret = os.getenv("JIRA_WEBHOOK_SECRET", "").strip()
    if not secret:
        raise HTTPException(503, "JIRA_WEBHOOK_SECRET is not configured")

    raw_body = await request.body()
    _verify_jira_webhook_signature(
        raw_body,
        request.headers.get("X-Hub-Signature"),
        secret,
    )
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(400, "Invalid Jira webhook payload") from exc

    event = str(payload.get("webhookEvent") or "")
    if event not in {"jira:issue_created", "jira:issue_updated", "jira:issue_deleted"}:
        return {"ignored": True, "event": event or None}
    try:
        return _apply_jira_webhook_sync(payload)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, "Failed to sync Jira webhook") from exc
