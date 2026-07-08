"""Authenticated Jira connection endpoints for SwimMate coaches."""
from __future__ import annotations

import os

import psycopg2
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from integrations.jira_client import (
    JiraApiError,
    JiraClient,
    JiraConfigurationError,
)
from routers.coach import _get_customer_id, _require_coach, _require_user

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
