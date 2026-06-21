# -*- coding: utf-8 -*-
import json
import os
import secrets
from typing import Any, Dict

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
        CREATE TABLE IF NOT EXISTS custom_plans (
            id               SERIAL PRIMARY KEY,
            username         VARCHAR(100) NOT NULL DEFAULT 'guest',
            plan_name        VARCHAR(200) NOT NULL,
            goal             VARCHAR(50),
            sessions_per_week INTEGER,
            session_duration  INTEGER,
            focus_stroke     VARCHAR(50),
            level            VARCHAR(50),
            plan_content     JSONB,
            share_token      VARCHAR(64),
            created_at       TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    cur.execute("ALTER TABLE custom_plans ADD COLUMN IF NOT EXISTS share_token VARCHAR(64)")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS plan_favorites (
            id         SERIAL PRIMARY KEY,
            username   VARCHAR(100) NOT NULL,
            plan_id    INTEGER NOT NULL REFERENCES custom_plans(id) ON DELETE CASCADE,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE (username, plan_id)
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_plan_fav_user ON plan_favorites(username)")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS preset_plan_favorites (
            id         SERIAL PRIMARY KEY,
            username   VARCHAR(100) NOT NULL,
            plan_key   VARCHAR(50) NOT NULL,
            plan_title VARCHAR(200),
            created_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE (username, plan_key)
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_preset_fav_user ON preset_plan_favorites(username)")
    conn.commit()
    cur.close()
    conn.close()


def _get_username(request: Request) -> str:
    token = request.cookies.get("swimtech_token")
    if not token:
        return "guest"
    return verify_token(token) or "guest"


class PlanRequest(BaseModel):
    plan_name: str
    goal: str
    sessions_per_week: int
    session_duration: int
    focus_stroke: str
    level: str
    plan_content: Dict[str, Any] = {}


@router.get("")
def list_plans(request: Request):
    try:
        _ensure_table()
        username = _get_username(request)
        conn = _get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT cp.id, cp.plan_name, cp.goal, cp.sessions_per_week, cp.session_duration,
                   cp.focus_stroke, cp.level, cp.plan_content, cp.created_at,
                   (pf.id IS NOT NULL) AS is_favorite
            FROM custom_plans cp
            LEFT JOIN plan_favorites pf ON pf.plan_id = cp.id AND pf.username = %s
            WHERE cp.username = %s
            ORDER BY cp.created_at DESC
        """, (username, username))
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return {
            "plans": [
                {
                    "id": r[0],
                    "plan_name": r[1],
                    "goal": r[2],
                    "sessions_per_week": r[3],
                    "session_duration": r[4],
                    "focus_stroke": r[5],
                    "level": r[6],
                    "plan_content": r[7],
                    "created_at": str(r[8]),
                    "is_favorite": r[9],
                }
                for r in rows
            ]
        }
    except Exception as e:
        raise HTTPException(500, f"DB 오류: {e}")


@router.post("")
def create_plan(req: PlanRequest, request: Request):
    try:
        _ensure_table()
        username = _get_username(request)
        conn = _get_db()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO custom_plans
                (username, plan_name, goal, sessions_per_week, session_duration,
                 focus_stroke, level, plan_content)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, created_at
            """,
            (
                username,
                req.plan_name,
                req.goal,
                req.sessions_per_week,
                req.session_duration,
                req.focus_stroke,
                req.level,
                json.dumps(req.plan_content, ensure_ascii=False),
            ),
        )
        row = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()
        return {
            "id": row[0],
            "plan_name": req.plan_name,
            "plan_content": req.plan_content,
            "created_at": str(row[1]),
        }
    except Exception as e:
        raise HTTPException(500, f"DB 저장 오류: {e}")


@router.delete("/{plan_id}")
def delete_plan(plan_id: int, request: Request):
    try:
        _ensure_table()
        username = _get_username(request)
        conn = _get_db()
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM custom_plans WHERE id = %s AND username = %s RETURNING id",
            (plan_id, username),
        )
        deleted = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()
        if not deleted:
            raise HTTPException(404, "플랜을 찾을 수 없습니다")
        return {"deleted": True, "id": plan_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"DB 오류: {e}")


@router.post("/{plan_id}/favorite")
def toggle_plan_favorite(plan_id: int, request: Request):
    username = _get_username(request)
    if username == "guest":
        raise HTTPException(401, "로그인이 필요합니다")
    try:
        _ensure_table()
        conn = _get_db()
        cur = conn.cursor()
        cur.execute("SELECT id FROM custom_plans WHERE id = %s AND username = %s", (plan_id, username))
        if not cur.fetchone():
            cur.close(); conn.close()
            raise HTTPException(404, "플랜을 찾을 수 없습니다")
        cur.execute("SELECT id FROM plan_favorites WHERE username = %s AND plan_id = %s", (username, plan_id))
        existing = cur.fetchone()
        if existing:
            cur.execute("DELETE FROM plan_favorites WHERE id = %s", (existing[0],))
            conn.commit()
            cur.close(); conn.close()
            return {"status": "removed"}
        else:
            cur.execute("INSERT INTO plan_favorites (username, plan_id) VALUES (%s,%s)", (username, plan_id))
            conn.commit()
            cur.close(); conn.close()
            return {"status": "added"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"DB 오류: {e}")


@router.get("/favorites")
def get_plan_favorites(request: Request):
    username = _get_username(request)
    if username == "guest":
        raise HTTPException(401, "로그인이 필요합니다")
    try:
        _ensure_table()
        conn = _get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT cp.id, cp.plan_name, cp.goal, cp.sessions_per_week, cp.session_duration,
                   cp.focus_stroke, cp.level, cp.plan_content, cp.created_at
            FROM plan_favorites pf
            JOIN custom_plans cp ON cp.id = pf.plan_id
            WHERE pf.username = %s
            ORDER BY pf.created_at DESC
        """, (username,))
        rows = cur.fetchall()
        cur.close(); conn.close()
        return {
            "plans": [
                {
                    "id": r[0], "plan_name": r[1], "goal": r[2],
                    "sessions_per_week": r[3], "session_duration": r[4],
                    "focus_stroke": r[5], "level": r[6],
                    "plan_content": r[7], "created_at": str(r[8]),
                    "is_favorite": True,
                }
                for r in rows
            ]
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"DB 오류: {e}")


@router.get("/{plan_id}/share")
def get_plan_share(plan_id: int, request: Request):
    username = _get_username(request)
    if username == "guest":
        raise HTTPException(401, "로그인이 필요합니다")
    try:
        _ensure_table()
        conn = _get_db()
        cur = conn.cursor()
        cur.execute("SELECT id, share_token FROM custom_plans WHERE id = %s AND username = %s",
                    (plan_id, username))
        row = cur.fetchone()
        if not row:
            cur.close(); conn.close()
            raise HTTPException(404, "플랜을 찾을 수 없습니다")
        token = row[1]
        if not token:
            token = secrets.token_urlsafe(32)
            cur.execute("UPDATE custom_plans SET share_token = %s WHERE id = %s", (token, plan_id))
            conn.commit()
        cur.close(); conn.close()
        return {"plan_id": plan_id, "share_token": token, "share_url": f"/plan/share/{token}"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"DB 오류: {e}")


class PresetFavoriteRequest(BaseModel):
    plan_title: str = ""


@router.post("/preset/{plan_key}/favorite")
def toggle_preset_plan_favorite(plan_key: str, body: PresetFavoriteRequest, request: Request):
    """프리셋(빌트인) 플랜 즐겨찾기 — DB에 저장되지 않은 고정 플랜(speed/masters/fitness/correction 등) 전용."""
    username = _get_username(request)
    if username == "guest":
        raise HTTPException(401, "로그인이 필요합니다")
    try:
        _ensure_table()
        conn = _get_db()
        cur = conn.cursor()
        cur.execute("SELECT id FROM preset_plan_favorites WHERE username = %s AND plan_key = %s",
                    (username, plan_key))
        existing = cur.fetchone()
        if existing:
            cur.execute("DELETE FROM preset_plan_favorites WHERE id = %s", (existing[0],))
            conn.commit()
            cur.close(); conn.close()
            return {"status": "removed"}
        else:
            cur.execute(
                "INSERT INTO preset_plan_favorites (username, plan_key, plan_title) VALUES (%s,%s,%s)",
                (username, plan_key, body.plan_title),
            )
            conn.commit()
            cur.close(); conn.close()
            return {"status": "added"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"DB 오류: {e}")


@router.get("/preset/favorites")
def get_preset_plan_favorites(request: Request):
    username = _get_username(request)
    if username == "guest":
        return {"plan_keys": []}
    try:
        _ensure_table()
        conn = _get_db()
        cur = conn.cursor()
        cur.execute("SELECT plan_key, plan_title FROM preset_plan_favorites WHERE username = %s ORDER BY created_at DESC", (username,))
        rows = cur.fetchall()
        cur.close(); conn.close()
        return {
            "plan_keys": [r[0] for r in rows],
            "favorites": [{"plan_key": r[0], "plan_title": r[1]} for r in rows],
        }
    except Exception as e:
        raise HTTPException(500, f"DB 오류: {e}")
