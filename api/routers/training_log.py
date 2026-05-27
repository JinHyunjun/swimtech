# -*- coding: utf-8 -*-
import os
from datetime import date
from typing import Any, Dict, Optional

import psycopg2
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from routers.auth import verify_token

router = APIRouter()

DATABASE_URL = os.getenv("DATABASE_URL", "")


def _get_db():
    return psycopg2.connect(DATABASE_URL)


def _ensure_table():
    conn = _get_db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS training_logs (
            id          SERIAL PRIMARY KEY,
            username    VARCHAR(100) NOT NULL DEFAULT 'guest',
            plan_name   VARCHAR(200),
            log_date    DATE NOT NULL DEFAULT CURRENT_DATE,
            notes       TEXT,
            plan_data   JSONB,
            created_at  TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    conn.commit()
    cur.close()
    conn.close()


def _get_username(request: Request) -> str:
    token = request.cookies.get("swimtech_token")
    if not token:
        return "guest"
    return verify_token(token) or "guest"


class FromPlanRequest(BaseModel):
    plan_name: str
    log_date: Optional[str] = None
    notes: Optional[str] = None
    plan_data: Dict[str, Any] = {}


@router.post("/from-plan")
def create_log_from_plan(req: FromPlanRequest, request: Request):
    try:
        _ensure_table()
        username = _get_username(request)
        log_date = req.log_date or str(date.today())
        import json
        conn = _get_db()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO training_logs (username, plan_name, log_date, notes, plan_data)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id, created_at
            """,
            (
                username,
                req.plan_name,
                log_date,
                req.notes or "",
                json.dumps(req.plan_data, ensure_ascii=False),
            ),
        )
        row = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()

        # 참여 중인 챌린지에 거리 자동 반영
        try:
            from routers.challenge import update_challenge_progress
            dist = int(req.plan_data.get("total_distance") or req.plan_data.get("distance") or 0)
            update_challenge_progress(username, dist)
        except Exception:
            pass

        return {
            "id": row[0],
            "plan_name": req.plan_name,
            "log_date": log_date,
            "created_at": str(row[1]),
        }
    except Exception as e:
        raise HTTPException(500, f"DB 저장 오류: {e}")


@router.get("")
def list_logs(request: Request):
    try:
        _ensure_table()
        username = _get_username(request)
        conn = _get_db()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, plan_name, log_date, notes, plan_data, created_at
            FROM training_logs
            WHERE username = %s
            ORDER BY log_date DESC, created_at DESC
            LIMIT 100
            """,
            (username,),
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return {
            "logs": [
                {
                    "id": r[0],
                    "plan_name": r[1],
                    "log_date": str(r[2]),
                    "notes": r[3],
                    "plan_data": r[4],
                    "created_at": str(r[5]),
                }
                for r in rows
            ]
        }
    except Exception as e:
        raise HTTPException(500, f"DB 오류: {e}")
