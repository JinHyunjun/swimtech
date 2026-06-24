"""훈련 기록 중심 대시보드 API."""
import logging
import os
from datetime import date, timedelta

import psycopg2
from fastapi import APIRouter, Cookie, HTTPException
from pydantic import BaseModel, Field

from routers.auth import decode_token, verify_token

router = APIRouter()
logger = logging.getLogger(__name__)
DATABASE_URL = os.getenv("DATABASE_URL", "")


def get_db():
    return psycopg2.connect(DATABASE_URL)


def _customer_id(swimtech_token: str | None) -> int:
    if not swimtech_token or not verify_token(swimtech_token):
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    customer_id = decode_token(swimtech_token).get("customer_id")
    if not customer_id:
        raise HTTPException(status_code=403, detail="훈련 기록이 연결된 계정으로 로그인해주세요.")
    return int(customer_id)


def _current_streak(dates: list[date]) -> int:
    recorded = set(dates)
    if not recorded:
        return 0
    today = date.today()
    cursor = today if today in recorded else today - timedelta(days=1)
    streak = 0
    while cursor in recorded:
        streak += 1
        cursor -= timedelta(days=1)
    return streak


@router.get("/summary")
def dashboard_summary(swimtech_token: str = Cookie(default=None)):
    """누적·이번 달 훈련 현황과 출석 스트릭을 반환한다."""
    customer_id = _customer_id(swimtech_token)
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT
                COUNT(*),
                COALESCE(SUM(total_distance), 0),
                COALESCE(SUM(duration_minutes), 0),
                COALESCE(SUM(CASE
                    WHEN date_trunc('month', log_date) = date_trunc('month', CURRENT_DATE)
                    THEN total_distance ELSE 0 END), 0)
            FROM training_logs
            WHERE customer_id = %s
            """,
            (customer_id,),
        )
        total_logs, total_distance, total_minutes, monthly_distance = cur.fetchone()
        cur.execute(
            "SELECT DISTINCT log_date FROM training_logs WHERE customer_id = %s",
            (customer_id,),
        )
        streak = _current_streak([row[0] for row in cur.fetchall()])
        cur.close()
        conn.close()
        return {
            "total_logs": int(total_logs or 0),
            "total_distance": int(total_distance or 0),
            "total_minutes": int(total_minutes or 0),
            "monthly_distance": int(monthly_distance or 0),
            "current_streak": streak,
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("dashboard_summary: DB error")
        raise HTTPException(500, "훈련 현황을 불러오지 못했습니다.")


@router.get("/history")
def dashboard_history(swimtech_token: str = Cookie(default=None)):
    """최근 훈련 기록과 거리 변화량을 반환한다."""
    customer_id = _customer_id(swimtech_token)
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, log_date, stroke_type, total_distance, duration_minutes,
                   intensity, mood, memo, created_at
            FROM training_logs
            WHERE customer_id = %s
            ORDER BY log_date DESC, created_at DESC
            LIMIT 12
            """,
            (customer_id,),
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()

        history = []
        for index, row in enumerate(rows):
            previous = rows[index + 1][3] if index + 1 < len(rows) else None
            distance = int(row[3] or 0)
            change = distance - int(previous or 0) if previous is not None else None
            history.append({
                "id": row[0],
                "log_date": str(row[1]),
                "stroke_type": row[2],
                "total_distance": distance,
                "duration_minutes": int(row[4] or 0),
                "intensity": row[5],
                "mood": row[6],
                "memo": row[7],
                "created_at": str(row[8]) if row[8] else None,
                "distance_change": change,
            })
        return {"history": history}
    except HTTPException:
        raise
    except Exception:
        logger.exception("dashboard_history: DB error")
        raise HTTPException(500, "최근 훈련 기록을 불러오지 못했습니다.")


class GoalBody(BaseModel):
    goal: int = Field(..., ge=1, le=7)


@router.get("/weekly")
def dashboard_weekly(swimtech_token: str = Cookie(default=None)):
    """이번 주 운동 일수와 거리 목표 진행률을 반환한다."""
    customer_id = _customer_id(swimtech_token)
    week_start = date.today() - timedelta(days=date.today().weekday())
    week_end = week_start + timedelta(days=6)
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT COUNT(DISTINCT log_date), COALESCE(SUM(total_distance), 0)
            FROM training_logs
            WHERE customer_id = %s AND log_date BETWEEN %s AND %s
            """,
            (customer_id, week_start, week_end),
        )
        achieved, distance = cur.fetchone()
        cur.execute("SELECT weekly_goal FROM customers WHERE id = %s", (customer_id,))
        row = cur.fetchone()
        cur.close()
        conn.close()

        goal = int(row[0]) if row and row[0] else 3
        achieved = int(achieved or 0)
        return {
            "goal": goal,
            "achieved": achieved,
            "distance": int(distance or 0),
            "percentage": min(100, round(achieved / goal * 100)) if goal else 0,
            "remaining": max(0, goal - achieved),
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("dashboard_weekly: DB error")
        raise HTTPException(500, "주간 목표를 불러오지 못했습니다.")


@router.post("/goal")
def dashboard_set_goal(body: GoalBody, swimtech_token: str = Cookie(default=None)):
    customer_id = _customer_id(swimtech_token)
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "UPDATE customers SET weekly_goal = %s WHERE id = %s RETURNING weekly_goal",
            (body.goal, customer_id),
        )
        row = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()
        if not row:
            raise HTTPException(404, "사용자를 찾을 수 없습니다.")
        return {"goal": int(row[0])}
    except HTTPException:
        raise
    except Exception:
        logger.exception("dashboard_set_goal: DB error")
        raise HTTPException(500, "주간 목표를 저장하지 못했습니다.")


@router.get("/frames/{analysis_id}")
def retired_analysis_frames(analysis_id: int):
    raise HTTPException(status_code=410, detail="영상 분석 기능은 현재 제공하지 않습니다.")
