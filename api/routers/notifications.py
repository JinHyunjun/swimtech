"""
SwimTech — 알림 라우터
GET  /api/notifications        — 목록 (최대 50개)
GET  /api/notifications/count  — 미읽음 수 (30초 폴링용)
PUT  /api/notifications/read-all — 전체 읽음
PUT  /api/notifications/{id}/read — 개별 읽음
"""
import logging
import os
from typing import Optional

import psycopg2
from fastapi import APIRouter, Cookie, HTTPException

from routers.auth import decode_token

router = APIRouter()
logger = logging.getLogger(__name__)
DATABASE_URL = os.getenv("DATABASE_URL", "")


def _get_db():
    return psycopg2.connect(DATABASE_URL)


def _require_login(token: Optional[str]) -> dict:
    if not token:
        raise HTTPException(401, "로그인이 필요합니다.")
    payload = decode_token(token)
    if not payload.get("sub"):
        raise HTTPException(401, "세션이 만료되었습니다.")
    return payload


@router.get("")
def list_notifications(swimtech_token: str = Cookie(default=None)):
    payload = _require_login(swimtech_token)
    me_id = payload.get("customer_id")
    if not me_id:
        raise HTTPException(403, "일반 계정으로 로그인해주세요.")
    conn = _get_db(); cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT id, type, message, target_id, is_read, created_at
            FROM notifications
            WHERE customer_id = %s
            ORDER BY created_at DESC
            LIMIT 50
            """,
            (me_id,),
        )
        rows = cur.fetchall()
        return {"notifications": [
            {
                "id": r[0], "type": r[1], "message": r[2],
                "target_id": r[3], "is_read": r[4],
                "created_at": r[5].isoformat() if r[5] else None,
            }
            for r in rows
        ]}
    except Exception:
        logger.error("list_notifications error", exc_info=True)
        raise HTTPException(500, "내부 오류가 발생했습니다.")
    finally:
        cur.close(); conn.close()


@router.get("/count")
def count_unread(swimtech_token: str = Cookie(default=None)):
    if not swimtech_token:
        return {"count": 0}
    payload = decode_token(swimtech_token)
    me_id = payload.get("customer_id")
    if not me_id:
        return {"count": 0}
    conn = _get_db(); cur = conn.cursor()
    try:
        cur.execute(
            "SELECT COUNT(*) FROM notifications WHERE customer_id = %s AND is_read = FALSE",
            (me_id,),
        )
        return {"count": cur.fetchone()[0]}
    except Exception:
        return {"count": 0}
    finally:
        cur.close(); conn.close()


@router.put("/read-all")
def mark_all_read(swimtech_token: str = Cookie(default=None)):
    payload = _require_login(swimtech_token)
    me_id = payload.get("customer_id")
    if not me_id:
        raise HTTPException(403, "일반 계정으로 로그인해주세요.")
    conn = _get_db(); cur = conn.cursor()
    try:
        cur.execute(
            "UPDATE notifications SET is_read = TRUE WHERE customer_id = %s AND is_read = FALSE",
            (me_id,),
        )
        conn.commit()
        return {"status": "ok"}
    except Exception:
        conn.rollback()
        raise HTTPException(500, "내부 오류가 발생했습니다.")
    finally:
        cur.close(); conn.close()


@router.put("/{notif_id}/read")
def mark_read(notif_id: int, swimtech_token: str = Cookie(default=None)):
    payload = _require_login(swimtech_token)
    me_id = payload.get("customer_id")
    if not me_id:
        raise HTTPException(403, "일반 계정으로 로그인해주세요.")
    conn = _get_db(); cur = conn.cursor()
    try:
        cur.execute(
            "UPDATE notifications SET is_read = TRUE WHERE id = %s AND customer_id = %s",
            (notif_id, me_id),
        )
        conn.commit()
        return {"status": "ok"}
    except Exception:
        conn.rollback()
        raise HTTPException(500, "내부 오류가 발생했습니다.")
    finally:
        cur.close(); conn.close()
