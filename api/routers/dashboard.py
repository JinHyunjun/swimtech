# -*- coding: utf-8 -*-
import os
from datetime import date, timedelta
from fastapi import APIRouter, HTTPException, Cookie
from pydantic import BaseModel, Field
import psycopg2

from routers.auth import verify_token, decode_token

router = APIRouter()

DATABASE_URL = os.getenv("DATABASE_URL", "")


def get_db():
    return psycopg2.connect(DATABASE_URL)


def _require_auth(swimtech_token: str | None):
    if not swimtech_token or not verify_token(swimtech_token):
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")


@router.get("/summary")
def dashboard_summary(swimtech_token: str = Cookie(default=None)):
    _require_auth(swimtech_token)
    payload = decode_token(swimtech_token) if swimtech_token else {}
    customer_id = payload.get("customer_id")  # admin이면 None
    try:
        conn = get_db()
        cur = conn.cursor()
        if customer_id is not None:
            cur.execute("""
                SELECT id, customer_id, stroke_type, overall_score,
                       l_elbow_avg, r_elbow_avg,
                       arm_symmetry, kick_count, kick_freq_hz,
                       head_angle_avg, analyzed_at
                FROM analysis_results
                WHERE customer_id = %s
                ORDER BY analyzed_at ASC
            """, (customer_id,))
        else:
            cur.execute("""
                SELECT id, customer_id, stroke_type, overall_score,
                       l_elbow_avg, r_elbow_avg,
                       arm_symmetry, kick_count, kick_freq_hz,
                       head_angle_avg, analyzed_at
                FROM analysis_results
                ORDER BY analyzed_at ASC
            """)
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return {
            "analyses": [
                {
                    "id": r[0],
                    "customer_id": r[1],
                    "stroke_type": r[2],
                    "overall_score": r[3],
                    "l_elbow_avg": r[4],
                    "r_elbow_avg": r[5],
                    "arm_symmetry": r[6],
                    "kick_count": r[7],
                    "kick_freq_hz": r[8],
                    "head_angle_avg": r[9],
                    "analyzed_at": str(r[10]),
                }
                for r in rows
            ]
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"DB 오류: {e}")


@router.get("/history")
def dashboard_history(swimtech_token: str = Cookie(default=None)):
    _require_auth(swimtech_token)
    payload = decode_token(swimtech_token) if swimtech_token else {}
    customer_id = payload.get("customer_id")
    try:
        conn = get_db()
        cur = conn.cursor()
        if customer_id is not None:
            cur.execute("""
                SELECT id, stroke_type, purpose, overall_score, ai_feedback, analyzed_at
                FROM analysis_results
                WHERE customer_id = %s
                ORDER BY analyzed_at DESC
                LIMIT 10
            """, (customer_id,))
        else:
            cur.execute("""
                SELECT id, stroke_type, purpose, overall_score, ai_feedback, analyzed_at
                FROM analysis_results
                ORDER BY analyzed_at DESC
                LIMIT 10
            """)
        rows = cur.fetchall()
        cur.close()
        conn.close()

        results = []
        for i, r in enumerate(rows):
            curr_score = float(r[3]) if r[3] is not None else None
            prev_score = float(rows[i + 1][3]) if i + 1 < len(rows) and rows[i + 1][3] is not None else None
            if curr_score is not None and prev_score is not None:
                diff = round(curr_score - prev_score, 1)
                trend = "↑" if diff > 0 else ("↓" if diff < 0 else "→")
            else:
                diff = None
                trend = "→"
            results.append({
                "id": r[0],
                "stroke_type": r[1],
                "purpose": r[2],
                "score": curr_score,
                "score_diff": diff,
                "trend": trend,
                "feedback": (r[4] or "")[:200],
                "analyzed_at": str(r[5]) if r[5] else None,
            })
        return {"history": results}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"DB 오류: {e}")


class GoalBody(BaseModel):
    goal: int = Field(..., ge=1, le=7)


def _ensure_weekly_goal_column(conn):
    cur = conn.cursor()
    cur.execute("ALTER TABLE customers ADD COLUMN IF NOT EXISTS weekly_goal INTEGER DEFAULT 3")
    conn.commit()
    cur.close()


@router.get("/weekly")
def dashboard_weekly(swimtech_token: str = Cookie(default=None)):
    _require_auth(swimtech_token)
    payload = decode_token(swimtech_token) if swimtech_token else {}
    customer_id = payload.get("customer_id")
    try:
        conn = get_db()
        _ensure_weekly_goal_column(conn)
        cur = conn.cursor()

        today = date.today()
        week_start = today - timedelta(days=today.weekday())  # 이번 주 월요일
        week_end   = week_start + timedelta(days=6)           # 이번 주 일요일

        if customer_id is not None:
            cur.execute("""
                SELECT COUNT(*) FROM analysis_results
                WHERE customer_id = %s
                  AND analyzed_at::date BETWEEN %s AND %s
            """, (customer_id, week_start, week_end))
        else:
            cur.execute("""
                SELECT COUNT(*) FROM analysis_results
                WHERE analyzed_at::date BETWEEN %s AND %s
            """, (week_start, week_end))
        achieved = cur.fetchone()[0]

        goal = 3
        if customer_id is not None:
            cur.execute("SELECT weekly_goal FROM customers WHERE id = %s", (customer_id,))
            row = cur.fetchone()
            if row and row[0] is not None:
                goal = row[0]

        cur.close()
        conn.close()
        pct = min(100, round(achieved / goal * 100)) if goal else 0
        return {
            "goal": goal,
            "achieved": achieved,
            "percentage": pct,
            "remaining": max(0, goal - achieved),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"DB 오류: {e}")


@router.post("/goal")
def dashboard_set_goal(body: GoalBody, swimtech_token: str = Cookie(default=None)):
    _require_auth(swimtech_token)
    payload = decode_token(swimtech_token) if swimtech_token else {}
    customer_id = payload.get("customer_id")
    if customer_id is None:
        raise HTTPException(403, "관리자 계정은 목표를 설정할 수 없습니다.")
    try:
        conn = get_db()
        _ensure_weekly_goal_column(conn)
        cur = conn.cursor()
        cur.execute("UPDATE customers SET weekly_goal = %s WHERE id = %s", (body.goal, customer_id))
        conn.commit()
        cur.close()
        conn.close()
        return {"goal": body.goal}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"DB 오류: {e}")


@router.get("/frames/{analysis_id}")
def dashboard_frames(analysis_id: int, swimtech_token: str = Cookie(default=None)):
    _require_auth(swimtech_token)
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT id, frame_number, timestamp_sec,
                   left_elbow_angle, right_elbow_angle,
                   hip_angle, shoulder_angle,
                   body_roll_angle, kick_detected
            FROM frame_metrics
            WHERE analysis_id = %s
            ORDER BY frame_number ASC
        """, (analysis_id,))
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return {
            "analysis_id": analysis_id,
            "frames": [
                {
                    "id": r[0],
                    "frame_number": r[1],
                    "timestamp_sec": r[2],
                    "left_elbow_angle": r[3],
                    "right_elbow_angle": r[4],
                    "hip_angle": r[5],
                    "shoulder_angle": r[6],
                    "body_roll_angle": r[7],
                    "kick_detected": r[8],
                }
                for r in rows
            ],
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"DB 오류: {e}")
