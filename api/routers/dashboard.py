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


def _ensure_readiness_table(cur):
    """오늘의 컨디션을 기기와 세션을 넘어 유지할 수 있도록 저장소를 보장한다."""
    # 배포 직후 readiness/advisor 요청이 동시에 들어와도 DDL이 경합하지 않도록 직렬화한다.
    cur.execute("SELECT pg_advisory_xact_lock(81420260628)")
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS training_readiness (
            id                 SERIAL PRIMARY KEY,
            customer_id        INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
            check_date         DATE NOT NULL DEFAULT CURRENT_DATE,
            sleep_quality      SMALLINT NOT NULL CHECK (sleep_quality BETWEEN 1 AND 5),
            fatigue            SMALLINT NOT NULL CHECK (fatigue BETWEEN 1 AND 5),
            muscle_soreness    SMALLINT NOT NULL CHECK (muscle_soreness BETWEEN 1 AND 5),
            available_minutes  SMALLINT NOT NULL CHECK (available_minutes BETWEEN 15 AND 180),
            note               VARCHAR(160),
            readiness_score    SMALLINT NOT NULL CHECK (readiness_score BETWEEN 0 AND 100),
            created_at         TIMESTAMPTZ DEFAULT NOW(),
            updated_at         TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE (customer_id, check_date)
        )
        """
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_training_readiness_customer_date "
        "ON training_readiness(customer_id, check_date DESC)"
    )


def _readiness_score(sleep_quality: int, fatigue: int, muscle_soreness: int) -> int:
    """수면 40%, 피로 회복 30%, 근육 회복 30%로 0~100 준비도를 계산한다."""
    score = (
        ((sleep_quality - 1) / 4) * 40
        + ((5 - fatigue) / 4) * 30
        + ((5 - muscle_soreness) / 4) * 30
    )
    return max(0, min(100, round(score)))


def _readiness_status(score: int) -> str:
    if score >= 75:
        return "좋음"
    if score >= 50:
        return "조절 필요"
    return "회복 우선"


def _serialize_readiness(row):
    if not row:
        return None
    score = int(row[6] or 0)
    return {
        "check_date": str(row[0]),
        "sleep_quality": int(row[1]),
        "fatigue": int(row[2]),
        "muscle_soreness": int(row[3]),
        "available_minutes": int(row[4]),
        "note": row[5],
        "score": score,
        "status": _readiness_status(score),
        "updated_at": str(row[7]) if row[7] else None,
    }


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


def _row_date(value) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _pool_preference(rows) -> int:
    pools = [int(row[5] or 25) for row in rows if row[5]]
    if not pools:
        return 25
    return 50 if pools.count(50) > pools.count(25) else 25


def _build_training_advisor(
    week_rows,
    recent_rows,
    weekly_goal: int,
    plan_completion_count: int,
    readiness=None,
):
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)
    recorded_days = {_row_date(row[0]) for row in week_rows}
    sessions_this_week = len(recorded_days)
    week_distance = sum(int(row[1] or 0) for row in week_rows)
    week_minutes = sum(int(row[2] or 0) for row in week_rows)
    hard_sessions = sum(1 for row in week_rows if row[3] == "힘듦")
    preferred_pool = _pool_preference(recent_rows)
    remaining_sessions = max(0, weekly_goal - sessions_this_week)

    last_row = recent_rows[0] if recent_rows else None
    last_date = _row_date(last_row[0]) if last_row else None
    days_since_last = (today - last_date).days if last_date else None
    last_intensity = last_row[3] if last_row else None
    avg_distance = round(week_distance / sessions_this_week) if sessions_this_week else 0

    readiness_score = int(readiness.get("score", 0)) if readiness else None
    available_minutes = int(readiness.get("available_minutes", 0)) if readiness else None

    if readiness and readiness_score < 50:
        focus = "회복 우선 세션"
        session = f"{preferred_pool}m 풀 기준 가벼운 회복 드릴 또는 휴식 · 최대 {available_minutes}분"
        intensity = "쉬움"
        message = "오늘 준비도가 낮아요. 훈련량을 채우기보다 통증 없는 범위에서 물감각만 유지하거나 쉬는 편이 좋습니다."
    elif readiness and readiness_score < 75:
        focus = "컨디션 조절 세션"
        session = f"{preferred_pool}m 풀 기준 기술 드릴 + 짧은 유산소 · 최대 {available_minutes}분"
        intensity = "쉬움"
        message = "오늘 컨디션은 조절이 필요해요. 대시 비중을 줄이고 자세가 흐트러지기 전에 마무리하세요."
    elif not recent_rows:
        focus = "첫 기록 만들기"
        session = f"{preferred_pool}m 풀 기준 기술 적응 1,000~1,400m"
        intensity = "쉬움"
        message = "아직 기록이 없어요. 오늘은 무리하지 않고 기준 기록을 하나 남기는 것이 가장 좋아요."
    elif days_since_last is not None and days_since_last >= 4:
        focus = "재시동 세션"
        session = f"{preferred_pool}m 풀 기준 회복 + 기초 지구력 1,200~1,800m"
        intensity = "보통"
        message = f"마지막 훈련 후 {days_since_last}일이 지났어요. 대시보다 리듬 회복을 먼저 가져가면 좋아요."
    elif hard_sessions >= 2 or (last_intensity == "힘듦" and days_since_last is not None and days_since_last <= 1):
        focus = "회복·기술 정리"
        session = f"{preferred_pool}m 풀 기준 드릴 중심 1,200~1,600m"
        intensity = "쉬움"
        message = "이번 주 강한 훈련이 충분히 들어갔어요. 다음 세션은 자세와 호흡을 정리하는 편이 안전해요."
    elif remaining_sessions == 0:
        focus = "목표 달성 유지"
        session = f"{preferred_pool}m 풀 기준 가벼운 폼 점검 800~1,200m"
        intensity = "쉬움"
        message = "이번 주 목표 일수를 채웠어요. 컨디션이 좋다면 짧게 물감각만 유지해도 충분합니다."
    elif sessions_this_week == 0:
        focus = "주간 루틴 시작"
        session = f"{preferred_pool}m 풀 기준 지구력 빌드업 1,500~2,000m"
        intensity = "보통"
        message = "이번 주 첫 훈련을 시작할 차례예요. 너무 빠른 대시보다 일정한 페이스가 좋습니다."
    elif remaining_sessions >= 2:
        focus = "볼륨 확보"
        session = f"{preferred_pool}m 풀 기준 메인셋 1,600~2,400m"
        intensity = "보통"
        message = f"목표까지 {remaining_sessions}회 남았어요. 오늘은 안정적인 거리 확보가 가장 효율적입니다."
    else:
        focus = "마무리 품질 세션"
        session = f"{preferred_pool}m 풀 기준 짧은 대시 + 충분한 휴식"
        intensity = "보통"
        message = "이번 주 마무리 세션이에요. 피로가 적다면 짧은 대시로 페이스 감각을 확인해보세요."

    if readiness and readiness_score >= 75:
        session += f" · {available_minutes}분 내 구성"
        message += " 오늘 준비도는 좋아 계획한 핵심 세트를 수행해도 좋습니다."

    if plan_completion_count:
        message += f" 이번 주 플랜 수행 기록은 {plan_completion_count}개입니다."

    return {
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "goal": weekly_goal,
        "sessions_this_week": sessions_this_week,
        "remaining_sessions": remaining_sessions,
        "week_distance": week_distance,
        "week_minutes": week_minutes,
        "avg_distance": avg_distance,
        "hard_sessions": hard_sessions,
        "plan_completion_count": int(plan_completion_count or 0),
        "preferred_pool_length": preferred_pool,
        "last_training_date": last_date.isoformat() if last_date else None,
        "days_since_last": days_since_last,
        "focus": focus,
        "recommended_session": session,
        "recommended_intensity": intensity,
        "message": message,
        "readiness_applied": bool(readiness),
        "readiness": readiness,
        "actions": [
            {"label": "추천 플랜 고르기", "href": "/plan"},
            {"label": "오늘 훈련 기록", "href": "/training-log?quick=1"},
            {"label": "월간 흐름 보기", "href": "/report"},
        ],
    }


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


class ReadinessBody(BaseModel):
    sleep_quality: int = Field(..., ge=1, le=5)
    fatigue: int = Field(..., ge=1, le=5)
    muscle_soreness: int = Field(..., ge=1, le=5)
    available_minutes: int = Field(..., ge=15, le=180)
    note: str | None = Field(default=None, max_length=160)


@router.get("/readiness")
def dashboard_readiness(swimtech_token: str = Cookie(default=None)):
    """오늘 체크인과 최근 7회 준비도 흐름을 반환한다."""
    customer_id = _customer_id(swimtech_token)
    try:
        conn = get_db()
        cur = conn.cursor()
        _ensure_readiness_table(cur)
        cur.execute(
            """
            SELECT check_date, sleep_quality, fatigue, muscle_soreness,
                   available_minutes, note, readiness_score, updated_at
            FROM training_readiness
            WHERE customer_id = %s
            ORDER BY check_date DESC
            LIMIT 7
            """,
            (customer_id,),
        )
        history = [_serialize_readiness(row) for row in cur.fetchall()]
        conn.commit()
        cur.close()
        conn.close()
        today = next((item for item in history if item["check_date"] == date.today().isoformat()), None)
        average = round(sum(item["score"] for item in history) / len(history)) if history else None
        return {"today": today, "history": history, "average_score": average}
    except HTTPException:
        raise
    except Exception:
        logger.exception("dashboard_readiness: DB error")
        raise HTTPException(500, "훈련 준비도를 불러오지 못했습니다.")


@router.post("/readiness")
def dashboard_save_readiness(body: ReadinessBody, swimtech_token: str = Cookie(default=None)):
    """당일 체크인을 한 건으로 갱신해 추천 입력값으로 사용한다."""
    customer_id = _customer_id(swimtech_token)
    score = _readiness_score(body.sleep_quality, body.fatigue, body.muscle_soreness)
    note = (body.note or "").strip() or None
    try:
        conn = get_db()
        cur = conn.cursor()
        _ensure_readiness_table(cur)
        cur.execute(
            """
            INSERT INTO training_readiness
                (customer_id, check_date, sleep_quality, fatigue, muscle_soreness,
                 available_minutes, note, readiness_score)
            VALUES (%s, CURRENT_DATE, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (customer_id, check_date) DO UPDATE SET
                sleep_quality = EXCLUDED.sleep_quality,
                fatigue = EXCLUDED.fatigue,
                muscle_soreness = EXCLUDED.muscle_soreness,
                available_minutes = EXCLUDED.available_minutes,
                note = EXCLUDED.note,
                readiness_score = EXCLUDED.readiness_score,
                updated_at = NOW()
            RETURNING check_date, sleep_quality, fatigue, muscle_soreness,
                      available_minutes, note, readiness_score, updated_at
            """,
            (
                customer_id,
                body.sleep_quality,
                body.fatigue,
                body.muscle_soreness,
                body.available_minutes,
                note,
                score,
            ),
        )
        saved = _serialize_readiness(cur.fetchone())
        conn.commit()
        cur.close()
        conn.close()
        return {"checkin": saved}
    except HTTPException:
        raise
    except Exception:
        logger.exception("dashboard_save_readiness: DB error")
        raise HTTPException(500, "훈련 준비도를 저장하지 못했습니다.")


@router.delete("/readiness")
def dashboard_delete_readiness(swimtech_token: str = Cookie(default=None)):
    """오늘 체크인을 초기화한다. QA 정리와 사용자의 재입력을 모두 지원한다."""
    customer_id = _customer_id(swimtech_token)
    try:
        conn = get_db()
        cur = conn.cursor()
        _ensure_readiness_table(cur)
        cur.execute(
            "DELETE FROM training_readiness WHERE customer_id = %s AND check_date = CURRENT_DATE",
            (customer_id,),
        )
        deleted = cur.rowcount
        conn.commit()
        cur.close()
        conn.close()
        return {"status": "deleted", "deleted": deleted}
    except HTTPException:
        raise
    except Exception:
        logger.exception("dashboard_delete_readiness: DB error")
        raise HTTPException(500, "훈련 준비도를 초기화하지 못했습니다.")


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


@router.get("/training-advisor")
def dashboard_training_advisor(swimtech_token: str = Cookie(default=None)):
    """최근 기록과 주간 목표를 바탕으로 다음 훈련 방향을 추천한다."""
    customer_id = _customer_id(swimtech_token)
    week_start = date.today() - timedelta(days=date.today().weekday())
    week_end = week_start + timedelta(days=6)
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT log_date, total_distance, duration_minutes, intensity, mood, pool_length
            FROM training_logs
            WHERE customer_id = %s AND log_date BETWEEN %s AND %s
            ORDER BY log_date DESC, created_at DESC
            """,
            (customer_id, week_start, week_end),
        )
        week_rows = cur.fetchall()
        cur.execute(
            """
            SELECT log_date, total_distance, duration_minutes, intensity, mood, pool_length
            FROM training_logs
            WHERE customer_id = %s
            ORDER BY log_date DESC, created_at DESC
            LIMIT 8
            """,
            (customer_id,),
        )
        recent_rows = cur.fetchall()
        cur.execute("SELECT weekly_goal FROM customers WHERE id = %s", (customer_id,))
        row = cur.fetchone()
        weekly_goal = int(row[0]) if row and row[0] else 3

        plan_completion_count = 0
        cur.execute("SELECT to_regclass('public.plan_completions')")
        has_plan_completions = cur.fetchone()[0]
        if has_plan_completions:
            cur.execute(
                """
                SELECT COUNT(DISTINCT pc.id)
                FROM plan_completions pc
                LEFT JOIN training_logs tl ON tl.id = pc.training_log_id
                WHERE pc.customer_id = %s
                  AND COALESCE(tl.log_date, pc.completed_at::date) BETWEEN %s AND %s
                """,
                (customer_id, week_start, week_end),
            )
            plan_completion_count = int((cur.fetchone() or [0])[0] or 0)

        _ensure_readiness_table(cur)
        cur.execute(
            """
            SELECT check_date, sleep_quality, fatigue, muscle_soreness,
                   available_minutes, note, readiness_score, updated_at
            FROM training_readiness
            WHERE customer_id = %s AND check_date = CURRENT_DATE
            LIMIT 1
            """,
            (customer_id,),
        )
        readiness = _serialize_readiness(cur.fetchone())

        conn.commit()
        cur.close()
        conn.close()
        return _build_training_advisor(
            week_rows,
            recent_rows,
            weekly_goal,
            plan_completion_count,
            readiness,
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("dashboard_training_advisor: DB error")
        raise HTTPException(500, "훈련 추천을 불러오지 못했습니다.")


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
