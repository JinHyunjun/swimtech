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
        CREATE TABLE IF NOT EXISTS pool_favorites (
            id         SERIAL PRIMARY KEY,
            username   VARCHAR(100) NOT NULL,
            pool_id    VARCHAR(200) NOT NULL,
            pool_name  VARCHAR(200) NOT NULL,
            address    TEXT,
            created_at TIMESTAMP DEFAULT NOW(),
            UNIQUE (username, pool_id)
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_pool_fav_user ON pool_favorites(username)")
    conn.commit()
    cur.close()
    conn.close()


class FavoriteRequest(BaseModel):
    pool_id: str
    pool_name: str
    address: str


@router.post("/favorite")
def toggle_favorite(body: FavoriteRequest, request: Request):
    username = _get_username(request)
    if not username:
        raise HTTPException(401, "로그인이 필요합니다")
    try:
        _ensure_table()
        conn = _get_db()
        cur = conn.cursor()
        cur.execute(
            "SELECT id FROM pool_favorites WHERE username = %s AND pool_id = %s",
            (username, body.pool_id),
        )
        existing = cur.fetchone()
        if existing:
            cur.execute("DELETE FROM pool_favorites WHERE id = %s", (existing[0],))
            conn.commit()
            cur.close(); conn.close()
            return {"status": "removed"}
        else:
            cur.execute(
                "INSERT INTO pool_favorites (username, pool_id, pool_name, address) VALUES (%s,%s,%s,%s)",
                (username, body.pool_id, body.pool_name, body.address),
            )
            conn.commit()
            cur.close(); conn.close()
            return {"status": "added"}
    except Exception as e:
        raise HTTPException(500, f"DB 오류: {e}")


@router.get("/favorites")
def get_favorites(request: Request):
    username = _get_username(request)
    if not username:
        raise HTTPException(401, "로그인이 필요합니다")
    try:
        _ensure_table()
        conn = _get_db()
        cur = conn.cursor()
        cur.execute(
            "SELECT pool_id, pool_name, address, created_at FROM pool_favorites WHERE username=%s ORDER BY created_at DESC",
            (username,),
        )
        rows = cur.fetchall()
        cur.close(); conn.close()
        return {
            "favorites": [
                {"pool_id": r[0], "pool_name": r[1], "address": r[2], "created_at": str(r[3])}
                for r in rows
            ]
        }
    except Exception as e:
        raise HTTPException(500, f"DB 오류: {e}")
