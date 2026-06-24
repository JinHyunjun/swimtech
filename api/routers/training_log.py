# -*- coding: utf-8 -*-
import os
from datetime import date, timedelta
from typing import Any, Dict, Optional

import psycopg2
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from routers.auth import verify_token, decode_token

router = APIRouter()

DATABASE_URL = os.getenv("DATABASE_URL", "")


def _get_db():
    return psycopg2.connect(DATABASE_URL)


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


class GoalRequest(BaseModel):
    year: int
    month: int
    goal_distance: int


def _get_customer_id(request: Request) -> Optional[int]:
    token = request.cookies.get("swimtech_token")
    if not token:
        return None
    payload = decode_token(token)
    return payload.get("customer_id")


def _ensure_log_columns():
    """기존에 배포된 training_logs 테이블에 used_fins 컬럼이 없을 수 있어 추가 보장."""
    conn = _get_db()
    cur = conn.cursor()
    cur.execute("ALTER TABLE training_logs ADD COLUMN IF NOT EXISTS used_fins BOOLEAN DEFAULT FALSE")
    conn.commit()
    cur.close()
    conn.close()


def _ensure_goals_table():
    conn = _get_db()
    cur = conn.cursor()
    # 구버전(username 컬럼) 테이블이 있으면 삭제 후 재생성
    cur.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name='training_goals' AND column_name='username'
    """)
    if cur.fetchone():
        cur.execute("DROP TABLE IF EXISTS training_goals")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS training_goals (
            id            SERIAL PRIMARY KEY,
            customer_id   INTEGER NOT NULL,
            year          INTEGER NOT NULL,
            month         INTEGER NOT NULL,
            goal_distance INTEGER NOT NULL DEFAULT 0,
            created_at    TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE (customer_id, year, month)
        )
    """)
    conn.commit()
    cur.close()
    conn.close()


class LogRequest(BaseModel):
    log_date:         str
    stroke_type:      str = "자유형"
    pool_length:      int = 25
    total_distance:   int
    duration_minutes: int = 0
    intensity:        str = "보통"
    mood:             Optional[str] = None
    memo:             Optional[str] = None
    used_fins:        bool = False


@router.post("")
def create_log(req: LogRequest, request: Request):
    cid = _get_customer_id(request)
    if not cid:
        raise HTTPException(401, "로그인이 필요합니다")
    try:
        ld = date.fromisoformat(req.log_date)
    except Exception:
        raise HTTPException(400, "날짜 형식 오류 (YYYY-MM-DD)")
    dist = int(req.total_distance or 0)
    if dist <= 0:
        raise HTTPException(400, "거리를 입력하세요")
    memo = (req.memo or "").strip() or None
    conn = _get_db()
    cur = conn.cursor()
    try:
        _ensure_log_columns()
        cur.execute("""INSERT INTO training_logs
            (customer_id, log_date, stroke_type, total_distance, duration_minutes, pool_length, intensity, memo, mood, used_fins)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
            (cid, ld, req.stroke_type, dist, int(req.duration_minutes or 0),
             int(req.pool_length or 25), req.intensity, memo, req.mood, req.used_fins))
        nid = cur.fetchone()[0]
        conn.commit()
        return {"id": nid, "status": "created"}
    except Exception as e:
        conn.rollback()
        raise HTTPException(500, f"저장 오류: {e}")
    finally:
        cur.close(); conn.close()


@router.put("/{log_id}")
def update_log(log_id: int, req: LogRequest, request: Request):
    cid = _get_customer_id(request)
    if not cid:
        raise HTTPException(401, "로그인이 필요합니다")
    try:
        ld = date.fromisoformat(req.log_date)
    except Exception:
        raise HTTPException(400, "날짜 형식 오류 (YYYY-MM-DD)")
    dist = int(req.total_distance or 0)
    if dist <= 0:
        raise HTTPException(400, "거리를 입력하세요")
    memo = (req.memo or "").strip() or None
    conn = _get_db()
    cur = conn.cursor()
    try:
        _ensure_log_columns()
        cur.execute("SELECT customer_id FROM training_logs WHERE id = %s", (log_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "기록을 찾을 수 없습니다")
        if row[0] != cid:
            raise HTTPException(403, "권한이 없습니다")
        cur.execute("""UPDATE training_logs SET
            log_date=%s, stroke_type=%s, total_distance=%s, duration_minutes=%s,
            pool_length=%s, intensity=%s, memo=%s, mood=%s, used_fins=%s, updated_at=NOW()
            WHERE id=%s""",
            (ld, req.stroke_type, dist, int(req.duration_minutes or 0),
             int(req.pool_length or 25), req.intensity, memo, req.mood, req.used_fins, log_id))
        conn.commit()
        return {"status": "updated"}
    except HTTPException:
        conn.rollback(); raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(500, f"수정 오류: {e}")
    finally:
        cur.close(); conn.close()


@router.delete("/{log_id}")
def delete_log(log_id: int, request: Request):
    cid = _get_customer_id(request)
    if not cid:
        raise HTTPException(401, "로그인이 필요합니다")
    conn = _get_db()
    cur = conn.cursor()
    try:
        cur.execute("SELECT customer_id FROM training_logs WHERE id = %s", (log_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "기록을 찾을 수 없습니다")
        if row[0] != cid:
            raise HTTPException(403, "권한이 없습니다")
        cur.execute("DELETE FROM training_logs WHERE id = %s", (log_id,))
        conn.commit()
        return {"status": "deleted"}
    except HTTPException:
        conn.rollback(); raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(500, f"삭제 오류: {e}")
    finally:
        cur.close(); conn.close()


@router.get("/stats")
def get_stats(request: Request, year: int, month: int):
    cid = _get_customer_id(request)
    if not cid:
        return {"count": 0, "total_distance": 0, "avg_distance": 0}
    conn = _get_db()
    cur = conn.cursor()
    try:
        cur.execute("""SELECT COUNT(*), COALESCE(SUM(total_distance),0), COALESCE(AVG(total_distance),0)
            FROM training_logs WHERE customer_id=%s
              AND EXTRACT(YEAR FROM log_date)=%s AND EXTRACT(MONTH FROM log_date)=%s""",
            (cid, year, month))
        r = cur.fetchone()
        cur.close()
        return {"count": int(r[0] or 0), "total_distance": int(r[1] or 0), "avg_distance": round(float(r[2] or 0))}
    except Exception as e:
        raise HTTPException(500, f"통계 오류: {e}")
    finally:
        conn.close()


@router.get("/streak")
def get_streak(request: Request):
    cid = _get_customer_id(request)
    if not cid:
        return {"streak": 0}
    conn = _get_db()
    cur = conn.cursor()
    try:
        cur.execute("SELECT DISTINCT log_date FROM training_logs WHERE customer_id=%s", (cid,))
        dates = set(r[0] for r in cur.fetchall())
        cur.close()
        if not dates:
            return {"streak": 0}
        today = date.today()
        cursor_day = today if today in dates else today - timedelta(days=1)
        if cursor_day not in dates:
            return {"streak": 0}
        streak = 0
        while cursor_day in dates:
            streak += 1
            cursor_day = cursor_day - timedelta(days=1)
        return {"streak": streak}
    except Exception as e:
        raise HTTPException(500, f"연속출석 오류: {e}")
    finally:
        conn.close()

@router.post("/from-plan")
def create_log_from_plan(req: FromPlanRequest, request: Request):
    try:
        username = _get_username(request)
        cid = _get_customer_id(request)
        if not cid:
            raise HTTPException(401, "로그인이 필요합니다")
        log_date = req.log_date or str(date.today())
        pd = req.plan_data or {}
        dist = int(pd.get("total_distance") or pd.get("distance") or 0)
        _stroke = pd.get("stroke_type") or pd.get("stroke") or "자유형"
        _dur = int(pd.get("duration_minutes") or pd.get("duration") or 0)
        _pool = int(pd.get("pool_length") or 25)
        _inten = pd.get("intensity") or "보통"
        _memo = (str(req.plan_name or "") + ((" - " + req.notes) if req.notes else "")).strip() or None
        conn = _get_db()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO training_logs (customer_id, log_date, stroke_type, total_distance, duration_minutes, pool_length, intensity, memo)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, created_at
            """,
            (cid, log_date, _stroke, dist, _dur, _pool, _inten, _memo),
        )
        row = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()

        # 참여 중인 챌린지에 거리 자동 반영
        try:
            from routers.challenge import update_challenge_progress
            update_challenge_progress(username, dist)
        except Exception:
            pass

        # 훈련 일지 뱃지 자동 체크
        try:
            from routers.badge import check_badges_on_log
            check_badges_on_log(username)
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


@router.post("/goal")
def set_goal(req: GoalRequest, request: Request):
    customer_id = _get_customer_id(request)
    if not customer_id:
        raise HTTPException(401, "로그인이 필요합니다.")
    try:
        _ensure_goals_table()
        conn = _get_db()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO training_goals (customer_id, year, month, goal_distance)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (customer_id, year, month)
            DO UPDATE SET goal_distance = EXCLUDED.goal_distance, created_at = NOW()
            RETURNING id
        """, (customer_id, req.year, req.month, req.goal_distance))
        row = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()
        return {"id": row[0], "goal_distance": req.goal_distance}
    except Exception as e:
        raise HTTPException(500, f"DB 오류: {e}")


@router.get("/goal")
def get_goal(year: int, month: int, request: Request):
    customer_id = _get_customer_id(request)
    if not customer_id:
        return {"goal_distance": 0, "achieved_distance": 0}
    try:
        _ensure_goals_table()
        conn = _get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT goal_distance FROM training_goals
            WHERE customer_id = %s AND year = %s AND month = %s
        """, (customer_id, year, month))
        row = cur.fetchone()
        goal = row[0] if row else 0
        cur.execute("""
            SELECT COALESCE(SUM(total_distance), 0) FROM training_logs
            WHERE customer_id = %s
              AND EXTRACT(YEAR FROM log_date) = %s
              AND EXTRACT(MONTH FROM log_date) = %s
        """, (customer_id, year, month))
        achieved = int(cur.fetchone()[0])
        cur.close()
        conn.close()
        return {"goal_distance": goal, "achieved_distance": achieved}
    except Exception as e:
        raise HTTPException(500, f"DB 오류: {e}")


@router.get("/recent")
def get_most_recent_log(request: Request):
    """빠른 기록 작성에 사용할 가장 최근 훈련 기록을 반환한다."""
    cid = _get_customer_id(request)
    if not cid:
        raise HTTPException(401, "로그인이 필요합니다")
    conn = _get_db()
    cur = conn.cursor()
    try:
        _ensure_log_columns()
        cur.execute(
            """SELECT id, log_date, stroke_type, total_distance, duration_minutes,
                      pool_length, intensity, mood, memo, created_at, used_fins
                 FROM training_logs
                WHERE customer_id = %s
                ORDER BY log_date DESC, created_at DESC
                LIMIT 1""",
            (cid,),
        )
        row = cur.fetchone()
        if not row:
            return {"log": None}
        return {"log": {
            "id": row[0],
            "log_date": str(row[1]),
            "stroke_type": row[2],
            "total_distance": row[3],
            "duration_minutes": row[4],
            "pool_length": row[5],
            "intensity": row[6],
            "mood": row[7],
            "memo": row[8],
            "created_at": str(row[9]),
            "used_fins": row[10],
        }}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"최근 기록 조회 오류: {e}")
    finally:
        cur.close()
        conn.close()


@router.get("")
def list_logs(request: Request, year: Optional[int] = None, month: Optional[int] = None):
    cid = _get_customer_id(request)
    if not cid:
        return {"logs": []}
    conn = _get_db()
    cur = conn.cursor()
    try:
        _ensure_log_columns()
        if year and month:
            cur.execute("""SELECT id, log_date, stroke_type, total_distance, duration_minutes,
                       pool_length, intensity, mood, memo, created_at, used_fins
                FROM training_logs WHERE customer_id=%s
                  AND EXTRACT(YEAR FROM log_date)=%s AND EXTRACT(MONTH FROM log_date)=%s
                ORDER BY log_date DESC, created_at DESC""",
                (cid, year, month))
        else:
            cur.execute("""SELECT id, log_date, stroke_type, total_distance, duration_minutes,
                       pool_length, intensity, mood, memo, created_at, used_fins
                FROM training_logs WHERE customer_id=%s
                ORDER BY log_date DESC, created_at DESC LIMIT 100""",
                (cid,))
        rows = cur.fetchall()
        cur.close(); conn.close()
        return {"logs": [
            {
                "id": r[0],
                "log_date": str(r[1]),
                "stroke_type": r[2],
                "total_distance": r[3],
                "duration_minutes": r[4],
                "pool_length": r[5],
                "intensity": r[6],
                "mood": r[7],
                "memo": r[8],
                "created_at": str(r[9]),
                "used_fins": r[10],
            }
            for r in rows
        ]}
    except Exception as e:
        raise HTTPException(500, f"DB 오류: {e}")
