# -*- coding: utf-8 -*-
import base64
import json
import os
from datetime import date
from typing import Optional

import psycopg2
from fastapi import APIRouter, HTTPException, Query, Request

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


def _empty_plan_performance() -> dict:
    return {
        "completed_sessions": 0,
        "plan_distance": 0,
        "plan_distance_rate": 0,
        "cycle_logs": 0,
        "cycle_adherence_rate": 0,
        "goal_distance": 0,
        "goal_achievement_rate": 0,
    }


def _calc_monthly_stats(username: str, year: int, month: int) -> dict:
    conn = _get_db()
    cur = conn.cursor()

    cur.execute("SELECT id FROM customers WHERE username = %s", (username,))
    crow = cur.fetchone()
    if not crow:
        cur.close(); conn.close()
        return {
            "year": year, "month": month, "total_distance": 0, "total_count": 0,
            "total_time": 0, "calories": 0,
            "by_stroke": {"freestyle": 0, "backstroke": 0, "breaststroke": 0, "butterfly": 0, "other": 0},
            "by_day": [0]*7, "by_week": [0]*5, "prev_distance": 0,
            "growth_rate": 0.0, "streak": 0,
            "plan_performance": _empty_plan_performance(),
        }
    cid = crow[0]

    cur.execute("""
        SELECT log_date, stroke_type, total_distance, duration_minutes
        FROM training_logs
        WHERE customer_id = %s
          AND EXTRACT(YEAR FROM log_date) = %s
          AND EXTRACT(MONTH FROM log_date) = %s
        ORDER BY log_date
    """, (cid, year, month))
    rows = cur.fetchall()

    prev_year, prev_month = (year - 1, 12) if month == 1 else (year, month - 1)
    cur.execute("""
        SELECT COALESCE(SUM(total_distance), 0)
        FROM training_logs
        WHERE customer_id = %s
          AND EXTRACT(YEAR FROM log_date) = %s
          AND EXTRACT(MONTH FROM log_date) = %s
    """, (cid, prev_year, prev_month))
    prev_row = cur.fetchone()
    prev_distance = float(prev_row[0]) if prev_row else 0.0

    cur.execute("SELECT DISTINCT log_date FROM training_logs WHERE customer_id = %s ORDER BY log_date", (cid,))
    all_dates = [r[0] for r in cur.fetchall()]

    plan_performance = _empty_plan_performance()
    cur.execute("SELECT to_regclass('public.plan_completions'), to_regclass('public.training_goals')")
    has_plan_completions, has_training_goals = cur.fetchone()
    if has_plan_completions:
        cur.execute("""
            SELECT COUNT(DISTINCT pc.id),
                   COALESCE(SUM(tl.total_distance), 0),
                   COUNT(DISTINCT CASE WHEN COALESCE(tl.memo, '') LIKE '%@%' THEN pc.id END)
            FROM plan_completions pc
            JOIN training_logs tl ON tl.id = pc.training_log_id
            WHERE pc.customer_id = %s
              AND EXTRACT(YEAR FROM tl.log_date) = %s
              AND EXTRACT(MONTH FROM tl.log_date) = %s
        """, (cid, year, month))
        prow = cur.fetchone() or (0, 0, 0)
        completed_sessions = int(prow[0] or 0)
        plan_distance = int(prow[1] or 0)
        cycle_logs = int(prow[2] or 0)
        plan_performance.update({
            "completed_sessions": completed_sessions,
            "plan_distance": plan_distance,
            "cycle_logs": cycle_logs,
            "cycle_adherence_rate": round(cycle_logs / completed_sessions * 100) if completed_sessions else 0,
        })
    if has_training_goals:
        cur.execute("""
            SELECT goal_distance FROM training_goals
            WHERE customer_id = %s AND year = %s AND month = %s
        """, (cid, year, month))
        grow = cur.fetchone()
        goal_distance = int(grow[0] or 0) if grow else 0
        plan_performance["goal_distance"] = goal_distance
    cur.close()
    conn.close()

    _BUCKET = {"자유형": "freestyle", "배영": "backstroke", "평영": "breaststroke", "접영": "butterfly"}

    total_distance = 0.0
    total_minutes = 0.0
    total_count = len(rows)
    stroke_dist = {"freestyle": 0.0, "backstroke": 0.0, "breaststroke": 0.0, "butterfly": 0.0, "other": 0.0}
    weekday_freq = [0] * 7
    weekly_dist: dict = {}

    for log_date, stroke_type, dist_v, dur_v in rows:
        dist = float(dist_v or 0)
        mins = float(dur_v or 0)
        total_distance += dist
        total_minutes += mins
        bucket = _BUCKET.get((stroke_type or "").strip(), "other")
        stroke_dist[bucket] += dist
        weekday_freq[log_date.weekday()] += 1
        week_num = (log_date.day - 1) // 7 + 1
        weekly_dist[week_num] = weekly_dist.get(week_num, 0) + dist

    weekly_list = [weekly_dist.get(w, 0) for w in range(1, 6)]

    if prev_distance > 0:
        growth_rate = round((total_distance - prev_distance) / prev_distance * 100, 1)
    elif total_distance > 0:
        growth_rate = 100.0
    else:
        growth_rate = 0.0

    if total_distance > 0:
        plan_performance["plan_distance_rate"] = round(plan_performance["plan_distance"] / total_distance * 100)
    if plan_performance["goal_distance"] > 0:
        plan_performance["goal_achievement_rate"] = round(total_distance / plan_performance["goal_distance"] * 100)

    max_streak = cur_streak = 0
    prev_d = None
    for d in all_dates:
        if prev_d is None:
            cur_streak = 1
        elif (d - prev_d).days == 1:
            cur_streak += 1
        else:
            cur_streak = 1
        max_streak = max(max_streak, cur_streak)
        prev_d = d

    return {
        "year": year,
        "month": month,
        "total_distance": int(total_distance),
        "total_count": total_count,
        "total_time": int(total_minutes),
        "calories": round(total_distance / 1000 * 400),
        "by_stroke": {k: int(v) for k, v in stroke_dist.items()},
        "by_day": weekday_freq,
        "by_week": [int(v) for v in weekly_list],
        "prev_distance": int(prev_distance),
        "growth_rate": growth_rate,
        "streak": max_streak,
        "plan_performance": plan_performance,
    }

def _make_share_token(username: str, year: int, month: int) -> str:
    payload = json.dumps({"u": username, "y": year, "m": month}, separators=(",", ":"))
    return base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")


def _parse_share_token(token: str) -> Optional[dict]:
    try:
        pad = 4 - len(token) % 4
        if pad != 4:
            token += "=" * pad
        return json.loads(base64.urlsafe_b64decode(token).decode())
    except Exception:
        return None


@router.get("/heatmap")
def get_training_heatmap(request: Request, days: int = Query(365, le=730)):
    """최근 N일간의 일자별 훈련 거리 — 깃허브 커밋 그래프 스타일 히트맵용."""
    username = _get_username(request)
    if not username:
        raise HTTPException(401, "로그인이 필요합니다")

    conn = _get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM customers WHERE username = %s", (username,))
    crow = cur.fetchone()
    if not crow:
        cur.close(); conn.close()
        return {"days": {}, "current_streak": 0, "longest_streak": 0, "total_days": 0}
    cid = crow[0]

    cur.execute("""
        SELECT log_date, SUM(total_distance)
        FROM training_logs
        WHERE customer_id = %s AND log_date >= CURRENT_DATE - %s::int
        GROUP BY log_date
        ORDER BY log_date
    """, (cid, days))
    rows = cur.fetchall()
    cur.close()
    conn.close()

    day_map = {str(r[0]): int(r[1] or 0) for r in rows}
    date_set = set(r[0] for r in rows)

    # 연속 출석일(현재/최장) 계산
    longest = current = 0
    prev = None
    today = date.today()
    sorted_dates = sorted(date_set)
    for d in sorted_dates:
        if prev is not None and (d - prev).days == 1:
            current += 1
        else:
            current = 1
        longest = max(longest, current)
        prev = d
    current_streak = 0
    cursor_day = today if today in date_set else today.fromordinal(today.toordinal() - 1)
    while cursor_day in date_set:
        current_streak += 1
        cursor_day = cursor_day.fromordinal(cursor_day.toordinal() - 1)

    return {
        "days": day_map,
        "current_streak": current_streak,
        "longest_streak": longest,
        "total_days": len(date_set),
    }


@router.get("/monthly")
def get_monthly_report(
    request: Request,
    year: int = Query(...),
    month: int = Query(...),
):
    username = _get_username(request)
    if not username:
        raise HTTPException(401, "로그인이 필요합니다")
    if not (1 <= month <= 12):
        raise HTTPException(400, "month는 1-12 사이여야 합니다")
    try:
        stats = _calc_monthly_stats(username, year, month)
        stats["share_token"] = _make_share_token(username, year, month)
        return stats
    except HTTPException:
        raise
    except Exception:
        return {
            "total_distance": 0,
            "total_count": 0,
            "total_time": 0,
            "calories": 0,
            "by_stroke": {},
            "by_week": {},
            "by_day": {},
            "growth_rate": 0,
            "streak": 0,
            "plan_performance": _empty_plan_performance(),
        }


@router.get("/share/{token}")
def get_shared_report(token: str):
    parsed = _parse_share_token(token)
    if not parsed or not all(k in parsed for k in ("u", "y", "m")):
        raise HTTPException(400, "유효하지 않은 공유 토큰입니다")
    try:
        return _calc_monthly_stats(parsed["u"], parsed["y"], parsed["m"])
    except Exception as e:
        raise HTTPException(500, f"리포트 조회 오류: {e}")
