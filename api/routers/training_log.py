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
            distance_m  INTEGER NOT NULL DEFAULT 0,
            created_at  TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    cur.execute("ALTER TABLE training_logs ADD COLUMN IF NOT EXISTS distance_m INTEGER NOT NULL DEFAULT 0")
    cur.execute("ALTER TABLE training_logs ADD COLUMN IF NOT EXISTS stroke_type VARCHAR(20)")
    cur.execute("ALTER TABLE training_logs ADD COLUMN IF NOT EXISTS pool_length INTEGER")
    cur.execute("ALTER TABLE training_logs ADD COLUMN IF NOT EXISTS duration_minutes INTEGER")
    cur.execute("ALTER TABLE training_logs ADD COLUMN IF NOT EXISTS intensity VARCHAR(10)")
    cur.execute("ALTER TABLE training_logs ADD COLUMN IF NOT EXISTS mood VARCHAR(10)")
    cur.execute("ALTER TABLE training_logs ADD COLUMN IF NOT EXISTS memo TEXT")
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
    stroke_type:      str = ""
    pool_length:      Optional[int] = None
    total_distance:   int
    duration_minutes: Optional[int] = None
    intensity:        str = "보통"
    mood:             Optional[str] = None
    memo:             Optional[str] = None


def _log_summary(stroke, dist):
    return (str(stroke or "").strip() + " " + str(dist) + "m").strip()


@router.post("")
def create_log(req: LogRequest, request: Request):
    """수동 훈련 기록 생성."""
    _ensure_table()
    username = _get_username(request)
    if username == "guest":
        raise HTTPException(401, "로그인이 필요합니다")
    try:
        ld = date.fromisoformat(req.log_date)
    except Exception:
        raise HTTPException(400, "날짜 형식 오류 (YYYY-MM-DD)")
    dist = int(req.total_distance or 0)
    if dist <= 0:
        raise HTTPException(400, "거리를 입력하세요")
    memo = (req.memo or "").strip() or None
    summary = _log_summary(req.stroke_type, dist)
    conn = _get_db()
    cur = conn.cursor()
    try:
        cur.execute("""INSERT INTO training_logs
            (username, plan_name, log_date, notes, distance_m, stroke_type, pool_length, duration_minutes, intensity, mood, memo)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
            (username, summary, ld, memo, dist, req.stroke_type, req.pool_length,
             req.duration_minutes, req.intensity, req.mood, memo))
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
    """훈련 기록 수정 (본인만)."""
    _ensure_table()
    username = _get_username(request)
    try:
        ld = date.fromisoformat(req.log_date)
    except Exception:
        raise HTTPException(400, "날짜 형식 오류 (YYYY-MM-DD)")
    dist = int(req.total_distance or 0)
    if dist <= 0:
        raise HTTPException(400, "거리를 입력하세요")
    memo = (req.memo or "").strip() or None
    summary = _log_summary(req.stroke_type, dist)
    conn = _get_db()
    cur = conn.cursor()
    try:
        cur.execute("SELECT username FROM training_logs WHERE id = %s", (log_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "기록을 찾을 수 없습니다")
        if row[0] != username:
            raise HTTPException(403, "권한이 없습니다")
        cur.execute("""UPDATE training_logs SET
            plan_name=%s, log_date=%s, notes=%s, distance_m=%s, stroke_type=%s,
            pool_length=%s, duration_minutes=%s, intensity=%s, mood=%s, memo=%s
            WHERE id=%s""",
            (summary, ld, memo, dist, req.stroke_type, req.pool_length,
             req.duration_minutes, req.intensity, req.mood, memo, log_id))
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
    """훈련 기록 삭제 (본인만)."""
    _ensure_table()
    username = _get_username(request)
    conn = _get_db()
    cur = conn.cursor()
    try:
        cur.execute("SELECT username FROM training_logs WHERE id = %s", (log_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "기록을 찾을 수 없습니다")
        if row[0] != username:
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
    """월별 통계: 횟수/총거리/평균거리."""
    _ensure_table()
    username = _get_username(request)
    conn = _get_db()
    cur = conn.cursor()
    try:
        cur.execute("""SELECT COUNT(*), COALESCE(SUM(distance_m),0), COALESCE(AVG(distance_m),0)
            FROM training_logs WHERE username=%s
              AND EXTRACT(YEAR FROM log_date)=%s AND EXTRACT(MONTH FROM log_date)=%s""",
            (username, year, month))
        r = cur.fetchone()
        cur.close()
        return {"count": int(r[0] or 0), "total_distance": int(r[1] or 0), "avg_distance": round(float(r[2] or 0))}
    except Exception as e:
        raise HTTPException(500, f"통계 오류: {e}")
    finally:
        conn.close()


@router.get("/streak")
def get_streak(request: Request):
    """오늘(또는 어제) 기준 연속 출석일수."""
    _ensure_table()
    username = _get_username(request)
    conn = _get_db()
    cur = conn.cursor()
    try:
        cur.execute("SELECT DISTINCT log_date FROM training_logs WHERE username=%s", (username,))
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
        _ensure_table()
        username = _get_username(request)
        log_date = req.log_date or str(date.today())
        import json
        dist = int(req.plan_data.get("total_distance") or req.plan_data.get("distance") or 0)
        conn = _get_db()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO training_logs (username, plan_name, log_date, notes, plan_data, distance_m)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id, created_at
            """,
            (
                username,
                req.plan_name,
                log_date,
                req.notes or "",
                json.dumps(req.plan_data, ensure_ascii=False),
                dist,
            ),
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


@router.get("")
def list_logs(request: Request, year: Optional[int] = None, month: Optional[int] = None):
    try:
        _ensure_table()
        username = _get_username(request)
        conn = _get_db()
        cur = conn.cursor()
        if year and month:
            cur.execute(
                """
                SELECT id, plan_name, log_date, notes, distance_m, stroke_type,
                       pool_length, duration_minutes, intensity, mood, memo, created_at
                FROM training_logs WHERE username = %s
                  AND EXTRACT(YEAR FROM log_date) = %s AND EXTRACT(MONTH FROM log_date) = %s
                ORDER BY log_date DESC, created_at DESC
                """,
                (username, year, month),
            )
        else:
            cur.execute(
                """
                SELECT id, plan_name, log_date, notes, distance_m, stroke_type,
                       pool_length, duration_minutes, intensity, mood, memo, created_at
                FROM training_logs WHERE username = %s
                ORDER BY log_date DESC, created_at DESC LIMIT 100
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
                    "total_distance": r[4] or 0,
                    "stroke_type": r[5] or "",
                    "pool_length": r[6],
                    "duration_minutes": r[7],
                    "intensity": r[8] or "보통",
                    "mood": r[9],
                    "memo": r[10],
                    "created_at": str(r[11]),
                }
                for r in rows
            ]
        }
    except Exception as e:
        raise HTTPException(500, f"DB 오류: {e}")
