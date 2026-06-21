# -*- coding: utf-8 -*-
import os
import logging
from typing import Optional

import psycopg2
from fastapi import APIRouter, HTTPException, Cookie
from pydantic import BaseModel

from routers.admin import _require_admin

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
    cur.execute("CREATE INDEX IF NOT EXISTS idx_feedback_created ON feedback(created_at)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_feedback_type ON feedback(feedback_type)")
    conn.commit()
    cur.close()
    conn.close()


class FeedbackRequest(BaseModel):
    feedback_type: str
    page: str
    title: str
    content: str
    email: Optional[str] = None


@router.post("")
def submit_feedback(body: FeedbackRequest):
    title = body.title.strip()
    content = body.content.strip()
    if not title or not content:
        raise HTTPException(400, "제목과 내용을 입력해주세요.")
    email = body.email.strip() if body.email and body.email.strip() else None

    try:
        _ensure_table()
        conn = _get_db()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO feedback (feedback_type, page, title, content, email)
            VALUES (%s, %s, %s, %s, %s) RETURNING id
        """, (body.feedback_type, body.page, title, content, email))
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
    offset = max(0, (page - 1) * page_size)

    if feedback_type:
        cur.execute("""
            SELECT id, feedback_type, page, title, content, email, created_at
            FROM feedback WHERE feedback_type = %s
            ORDER BY created_at DESC LIMIT %s OFFSET %s
        """, (feedback_type, page_size, offset))
    else:
        cur.execute("""
            SELECT id, feedback_type, page, title, content, email, created_at
            FROM feedback
            ORDER BY created_at DESC LIMIT %s OFFSET %s
        """, (page_size, offset))

    items = [{
        "id": r[0], "feedback_type": r[1], "page": r[2], "title": r[3],
        "content": r[4], "email": r[5], "created_at": str(r[6]),
    } for r in cur.fetchall()]

    cur.execute("SELECT COUNT(*) FROM feedback" + (" WHERE feedback_type = %s" if feedback_type else ""),
                (feedback_type,) if feedback_type else ())
    total = cur.fetchone()[0]

    cur.close()
    conn.close()
    return {"items": items, "total": total, "page": page, "page_size": page_size}
