"""SwimTech — 훈련 일지 라우터"""
import logging
import os
from datetime import date, timedelta
from typing import Optional

import psycopg2
from fastapi import APIRouter, Cookie, HTTPException, Query
from pydantic import BaseModel

from routers.auth import decode_token

router = APIRouter()
logger = logging.getLogger(__name__)
DATABASE_URL = os.getenv("DATABASE_URL", "")

VALID_STROKES   = {"자유형", "배영", "평영", "접영", "혼영", "자유수영"}
VALID_INTENSITY = {"쉬움", "보통", "힘듦"}
VALID_MOOD      = {"최고", "좋음", "보통", "나쁨"}
VALID_POOL_LEN  = {25, 50}


def _db():
    return psycopg2.connect(DATABASE_URL)


def _require_login(token: Optional[str]) -> dict:
    if not token:
        raise HTTPException(401, "로그인이 필요합니다.")
    payload = decode_token(token)
    if not payload.get("sub"):
        raise HTTPException(401, "세션이 만료되었습니다.")
    return payload


class LogCreate(BaseModel):
    log_date: str
    stroke_type: str
    total_distance: int
    duration_minutes: int
    pool_length: int = 25
    intensity: str
    memo: Optional[str] = None
    mood: Optional[str] = None


class LogUpdate(BaseModel):
    log_date: Optional[str] = None
    stroke_type: Optional[str] = None
    total_distance: Optional[int] = None
    duration_minutes: Optional[int] = None
    pool_length: Optional[int] = None
    intensity: Optional[str] = None
    memo: Optional[str] = None
    mood: Optional[str] = None


# ── 통계 (static route — /{id} 보다 먼저 정의) ───────────────────────────────

@router.get("/stats")
def get_stats(
    year: int = Query(None),
    month: int = Query(None),
    swimtech_token: str = Cookie(default=None),
):
    payload = _require_login(swimtech_token)
    customer_id = payload.get("customer_id")
    if not customer_id:
        raise HTTPException(403, "일반 계정으로 로그인해주세요.")

    today = date.today()
    y = year or today.year
    m = month or today.month

    conn = _db(); cur = conn.cursor()
    try:
        cur.execute("""
            SELECT
                COUNT(*)                             AS count,
                COALESCE(SUM(total_distance), 0)     AS total_distance,
                COALESCE(AVG(total_distance), 0)     AS avg_distance,
                COALESCE(SUM(duration_minutes), 0)   AS total_minutes
            FROM training_logs
            WHERE customer_id = %s
              AND EXTRACT(YEAR  FROM log_date) = %s
              AND EXTRACT(MONTH FROM log_date) = %s
        """, (customer_id, y, m))
        count, total_dist, avg_dist, total_min = cur.fetchone()
        return {
            "year": y, "month": m,
            "count": int(count),
            "total_distance": int(total_dist),
            "avg_distance": round(float(avg_dist), 0),
            "total_minutes": int(total_min),
        }
    except Exception:
        logger.error("get_stats error", exc_info=True)
        raise HTTPException(500, "내부 오류가 발생했습니다.")
    finally:
        cur.close(); conn.close()


# ── 연속 출석 ─────────────────────────────────────────────────────────────────

@router.get("/streak")
def get_streak(swimtech_token: str = Cookie(default=None)):
    payload = _require_login(swimtech_token)
    customer_id = payload.get("customer_id")
    if not customer_id:
        raise HTTPException(403, "일반 계정으로 로그인해주세요.")

    conn = _db(); cur = conn.cursor()
    try:
        cur.execute("""
            SELECT DISTINCT log_date FROM training_logs
            WHERE customer_id = %s
            ORDER BY log_date DESC
        """, (customer_id,))
        rows = cur.fetchall()
        if not rows:
            return {"streak": 0, "last_date": None}

        dates = [r[0] for r in rows]
        today = date.today()

        if dates[0] < today - timedelta(days=1):
            return {"streak": 0, "last_date": str(dates[0])}

        streak = 1
        for i in range(1, len(dates)):
            if dates[i] == dates[i - 1] - timedelta(days=1):
                streak += 1
            else:
                break

        return {"streak": streak, "last_date": str(dates[0])}
    except Exception:
        logger.error("get_streak error", exc_info=True)
        raise HTTPException(500, "내부 오류가 발생했습니다.")
    finally:
        cur.close(); conn.close()


# ── 목록 조회 ─────────────────────────────────────────────────────────────────

@router.get("")
def list_logs(
    year: int = Query(None),
    month: int = Query(None),
    swimtech_token: str = Cookie(default=None),
):
    payload = _require_login(swimtech_token)
    customer_id = payload.get("customer_id")
    if not customer_id:
        raise HTTPException(403, "일반 계정으로 로그인해주세요.")

    today = date.today()
    y = year or today.year
    m = month or today.month

    conn = _db(); cur = conn.cursor()
    try:
        cur.execute("""
            SELECT id, log_date, stroke_type, total_distance, duration_minutes,
                   pool_length, intensity, memo, mood, created_at
            FROM training_logs
            WHERE customer_id = %s
              AND EXTRACT(YEAR  FROM log_date) = %s
              AND EXTRACT(MONTH FROM log_date) = %s
            ORDER BY log_date DESC, created_at DESC
        """, (customer_id, y, m))
        logs = [
            {
                "id":               r[0],
                "log_date":         str(r[1]),
                "stroke_type":      r[2],
                "total_distance":   r[3],
                "duration_minutes": r[4],
                "pool_length":      r[5],
                "intensity":        r[6],
                "memo":             r[7],
                "mood":             r[8],
                "created_at":       r[9].isoformat() if r[9] else None,
            }
            for r in cur.fetchall()
        ]
        return {"logs": logs, "year": y, "month": m}
    except Exception:
        logger.error("list_logs error", exc_info=True)
        raise HTTPException(500, "내부 오류가 발생했습니다.")
    finally:
        cur.close(); conn.close()


# ── 기록 추가 ─────────────────────────────────────────────────────────────────

@router.post("")
def create_log(body: LogCreate, swimtech_token: str = Cookie(default=None)):
    payload = _require_login(swimtech_token)
    customer_id = payload.get("customer_id")
    if not customer_id:
        raise HTTPException(403, "일반 계정으로 로그인해주세요.")

    if body.stroke_type not in VALID_STROKES:
        raise HTTPException(400, "올바르지 않은 영법입니다.")
    if body.intensity not in VALID_INTENSITY:
        raise HTTPException(400, "올바르지 않은 강도입니다.")
    if body.mood and body.mood not in VALID_MOOD:
        raise HTTPException(400, "올바르지 않은 컨디션입니다.")
    if body.pool_length not in VALID_POOL_LEN:
        raise HTTPException(400, "레인 길이는 25m 또는 50m여야 합니다.")
    if not (1 <= body.total_distance <= 100000):
        raise HTTPException(400, "총 거리는 1~100000m여야 합니다.")
    if not (1 <= body.duration_minutes <= 1440):
        raise HTTPException(400, "훈련 시간은 1~1440분이어야 합니다.")

    conn = _db(); cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO training_logs
              (customer_id, log_date, stroke_type, total_distance, duration_minutes,
               pool_length, intensity, memo, mood)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            customer_id, body.log_date, body.stroke_type, body.total_distance,
            body.duration_minutes, body.pool_length, body.intensity,
            body.memo, body.mood,
        ))
        log_id = cur.fetchone()[0]
        conn.commit()
        return {"status": "ok", "id": log_id}
    except HTTPException:
        raise
    except Exception:
        conn.rollback(); logger.error("create_log error", exc_info=True)
        raise HTTPException(500, "내부 오류가 발생했습니다.")
    finally:
        cur.close(); conn.close()


# ── 기록 수정 ─────────────────────────────────────────────────────────────────

@router.put("/{log_id}")
def update_log(log_id: int, body: LogUpdate, swimtech_token: str = Cookie(default=None)):
    payload = _require_login(swimtech_token)
    customer_id = payload.get("customer_id")
    if not customer_id:
        raise HTTPException(403, "일반 계정으로 로그인해주세요.")

    conn = _db(); cur = conn.cursor()
    try:
        cur.execute("SELECT customer_id FROM training_logs WHERE id = %s", (log_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "훈련 기록을 찾을 수 없습니다.")
        if row[0] != customer_id:
            raise HTTPException(403, "수정 권한이 없습니다.")

        updates: list = []; params: list = []
        if body.log_date is not None:
            updates.append("log_date=%s"); params.append(body.log_date)
        if body.stroke_type is not None:
            if body.stroke_type not in VALID_STROKES:
                raise HTTPException(400, "올바르지 않은 영법입니다.")
            updates.append("stroke_type=%s"); params.append(body.stroke_type)
        if body.total_distance is not None:
            updates.append("total_distance=%s"); params.append(body.total_distance)
        if body.duration_minutes is not None:
            updates.append("duration_minutes=%s"); params.append(body.duration_minutes)
        if body.pool_length is not None:
            if body.pool_length not in VALID_POOL_LEN:
                raise HTTPException(400, "레인 길이는 25m 또는 50m여야 합니다.")
            updates.append("pool_length=%s"); params.append(body.pool_length)
        if body.intensity is not None:
            if body.intensity not in VALID_INTENSITY:
                raise HTTPException(400, "올바르지 않은 강도입니다.")
            updates.append("intensity=%s"); params.append(body.intensity)
        if body.memo is not None:
            updates.append("memo=%s"); params.append(body.memo)
        if body.mood is not None:
            updates.append("mood=%s"); params.append(body.mood)

        if updates:
            updates.append("updated_at=NOW()")
            cur.execute(
                f"UPDATE training_logs SET {','.join(updates)} WHERE id=%s",
                params + [log_id],
            )
            conn.commit()
        return {"status": "ok"}
    except HTTPException:
        raise
    except Exception:
        conn.rollback(); logger.error("update_log error", exc_info=True)
        raise HTTPException(500, "내부 오류가 발생했습니다.")
    finally:
        cur.close(); conn.close()


# ── 기록 삭제 ─────────────────────────────────────────────────────────────────

@router.delete("/{log_id}")
def delete_log(log_id: int, swimtech_token: str = Cookie(default=None)):
    payload = _require_login(swimtech_token)
    customer_id = payload.get("customer_id")
    if not customer_id:
        raise HTTPException(403, "일반 계정으로 로그인해주세요.")

    conn = _db(); cur = conn.cursor()
    try:
        cur.execute("SELECT customer_id FROM training_logs WHERE id = %s", (log_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "훈련 기록을 찾을 수 없습니다.")
        if row[0] != customer_id:
            raise HTTPException(403, "삭제 권한이 없습니다.")
        cur.execute("DELETE FROM training_logs WHERE id = %s", (log_id,))
        conn.commit()
        return {"status": "ok"}
    except HTTPException:
        raise
    except Exception:
        conn.rollback(); logger.error("delete_log error", exc_info=True)
        raise HTTPException(500, "내부 오류가 발생했습니다.")
    finally:
        cur.close(); conn.close()
