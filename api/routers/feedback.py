# -*- coding: utf-8 -*-
import os
import logging
from typing import Optional

import psycopg2
from fastapi import APIRouter, HTTPException, Cookie
from pydantic import BaseModel

from routers.admin import _require_admin
from routers.auth import decode_token

router = APIRouter()
logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "")


def _get_db():
    return psycopg2.connect(DATABASE_URL)


def _ensure_table():
    conn = _get_db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS feedback (
            id            SERIAL PRIMARY KEY,
            feedback_type VARCHAR(20) NOT NULL,
            page          TEXT,
            title         TEXT NOT NULL,
            content       TEXT NOT NULL,
            email         TEXT,
            created_at    TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    cur.execute("ALTER TABLE feedback ADD COLUMN IF NOT EXISTS customer_id INTEGER")
    cur.execute("ALTER TABLE feedback ADD COLUMN IF NOT EXISTS username TEXT")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_feedback_created ON feedback(created_at)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_feedback_type ON feedback(feedback_type)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_feedback_customer ON feedback(customer_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_feedback_username ON feedback(username)")
    conn.commit()
    cur.close()
    conn.close()


def _resolve_author(cur, swimtech_token: str | None):
    if not swimtech_token:
        return None, None
    payload = decode_token(swimtech_token)
    username = payload.get("sub") if payload else None
    customer_id = payload.get("customer_id") if payload else None
    if not username:
        return None, None
    if not customer_id:
        try:
            cur.execute("SELECT id FROM customers WHERE username = %s", (username,))
            row = cur.fetchone()
            customer_id = row[0] if row else None
        except Exception:
            customer_id = None
    return customer_id, username


def _normalize_page_size(value, default=50):
    try:
        size = int(value or default)
    except Exception:
        size = default
    return size if size in (20, 50, 100) else default


class FeedbackRequest(BaseModel):
    feedback_type: str
    page: str
    title: str
    content: str
    email: Optional[str] = None


@router.post("")
def submit_feedback(body: FeedbackRequest, swimtech_token: str = Cookie(default=None)):
    title = body.title.strip()
    content = body.content.strip()
    if not title or not content:
        raise HTTPException(400, "제목과 내용을 입력해주세요.")
    email = body.email.strip() if body.email and body.email.strip() else None

    try:
        _ensure_table()
        conn = _get_db()
        cur = conn.cursor()
        customer_id, username = _resolve_author(cur, swimtech_token)
        cur.execute("""
            INSERT INTO feedback (feedback_type, page, title, content, email, customer_id, username)
            VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id
        """, (body.feedback_type, body.page, title, content, email, customer_id, username))
        nid = cur.fetchone()[0]
        conn.commit()
        cur.close()
        conn.close()
        logger.info("피드백 저장 완료: id=%s type=%s", nid, body.feedback_type)
        return {"id": nid, "status": "ok", "message": "피드백이 전송되었습니다."}
    except Exception as e:
        logger.error("피드백 저장 실패: %s", e)
        raise HTTPException(500, f"피드백 저장 오류: {e}")


@router.get("")
def list_feedback(
    swimtech_token: str = Cookie(default=None),
    feedback_type: str = None,
    page: int = 1,
    page_size: int = 50,
):
    """관리자 전용: 피드백 목록 조회."""
    _require_admin(swimtech_token)
    _ensure_table()
    conn = _get_db()
    cur = conn.cursor()
    page = max(1, int(page or 1))
    page_size = _normalize_page_size(page_size, 50)
    offset = max(0, (page - 1) * page_size)

    author_join = """
        LEFT JOIN customers c ON (
            (f.customer_id IS NOT NULL AND c.id = f.customer_id)
            OR (f.customer_id IS NULL AND f.username IS NOT NULL AND c.username = f.username)
            OR (f.customer_id IS NULL AND f.username IS NULL AND f.email IS NOT NULL AND c.email = f.email)
        )
    """
    select_sql = f"""
        SELECT f.id, f.feedback_type, f.page, f.title, f.content, f.email, f.created_at,
               f.customer_id,
               COALESCE(f.username, c.username) AS author_username,
               c.nickname AS author_nickname,
               c.name AS author_name,
               c.email AS author_email,
               COALESCE(c.nickname, c.name, f.username, c.username, f.email, '비로그인') AS author_display
        FROM feedback f
        {author_join}
    """
    if feedback_type:
        cur.execute(select_sql + """
            WHERE f.feedback_type = %s
            ORDER BY f.created_at DESC LIMIT %s OFFSET %s
        """, (feedback_type, page_size, offset))
    else:
        cur.execute(select_sql + """
            ORDER BY f.created_at DESC LIMIT %s OFFSET %s
        """, (page_size, offset))

    items = [{
        "id": r[0], "feedback_type": r[1], "page": r[2], "title": r[3],
        "content": r[4], "email": r[5], "created_at": str(r[6]),
        "customer_id": r[7], "username": r[8], "author_username": r[8],
        "author_nickname": r[9], "author_name": r[10], "author_email": r[11],
        "author_display": r[12],
    } for r in cur.fetchall()]

    cur.execute("SELECT COUNT(*) FROM feedback" + (" WHERE feedback_type = %s" if feedback_type else ""),
                (feedback_type,) if feedback_type else ())
    total = cur.fetchone()[0]

    cur.close()
    conn.close()
    return {"items": items, "total": total, "page": page, "page_size": page_size}
