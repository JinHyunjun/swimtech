# -*- coding: utf-8 -*-
import os
from typing import Optional

import psycopg2
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from routers.auth import verify_token

router = APIRouter()
DATABASE_URL = os.getenv("DATABASE_URL", "")


def _get_db():
    return psycopg2.connect(DATABASE_URL)


def _get_username(request: Request) -> Optional[str]:
    token = request.cookies.get("swimtech_token")
    if not token:
        return None
    return verify_token(token)


def _ensure_table():
    conn = _get_db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS chat_histories (
            id         SERIAL PRIMARY KEY,
            username   VARCHAR(100) NOT NULL,
            role       VARCHAR(10) NOT NULL CHECK (role IN ('user','bot')),
            content    TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_chat_hist_user ON chat_histories(username, created_at DESC)"
    )
    conn.commit()
    cur.close()
    conn.close()


class ChatMessage(BaseModel):
    role: str
    content: str


@router.get("/history")
def get_history(request: Request):
    username = _get_username(request)
    if not username:
        raise HTTPException(401, "로그인이 필요합니다")
    try:
        _ensure_table()
        conn = _get_db()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, role, content, created_at
            FROM chat_histories
            WHERE username = %s
            ORDER BY created_at ASC
            LIMIT 50
            """,
            (username,),
        )
        rows = cur.fetchall()
        cur.close(); conn.close()
        return {
            "history": [
                {"id": r[0], "role": r[1], "content": r[2], "created_at": str(r[3])}
                for r in rows
            ]
        }
    except Exception as e:
        raise HTTPException(500, f"DB 오류: {e}")


@router.post("/history")
def save_message(body: ChatMessage, request: Request):
    username = _get_username(request)
    if not username:
        raise HTTPException(401, "로그인이 필요합니다")
    if body.role not in ("user", "bot"):
        raise HTTPException(400, "role은 'user' 또는 'bot'이어야 합니다")
    try:
        _ensure_table()
        conn = _get_db()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO chat_histories (username, role, content) VALUES (%s,%s,%s) RETURNING id, created_at",
            (username, body.role, body.content),
        )
        row = cur.fetchone()
        conn.commit()
        cur.close(); conn.close()
        return {"id": row[0], "created_at": str(row[1])}
    except Exception as e:
        raise HTTPException(500, f"DB 오류: {e}")


@router.delete("/history")
def clear_history(request: Request):
    username = _get_username(request)
    if not username:
        raise HTTPException(401, "로그인이 필요합니다")
    try:
        _ensure_table()
        conn = _get_db()
        cur = conn.cursor()
        cur.execute("DELETE FROM chat_histories WHERE username = %s", (username,))
        count = cur.rowcount
        conn.commit()
        cur.close(); conn.close()
        return {"deleted": count}
    except Exception as e:
        raise HTTPException(500, f"DB 오류: {e}")
