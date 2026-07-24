"""Personal data portability and account security endpoints."""

import json
import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import bcrypt
from fastapi import APIRouter, Cookie, HTTPException, Request, Response
from pydantic import BaseModel, Field

from activity_log import log_activity
from db import get_db
from rate_limit import limiter
from routers.auth import (
    _PASSWORD_RE,
    _authenticated_customer,
    _set_auth_cookie,
    _set_refresh_cookie,
    create_refresh_token,
    create_token,
)


router = APIRouter()
logger = logging.getLogger(__name__)


class SensitiveActionRequest(BaseModel):
    current_password: str | None = Field(default=None, max_length=200)


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=8, max_length=200)


def _json_default(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _percent(numerator: int | float, denominator: int | float) -> int:
    return round(float(numerator or 0) / float(denominator or 0) * 100) if denominator else 0


def _shift_month(year: int, month: int, offset: int) -> tuple[int, int]:
    absolute = year * 12 + (month - 1) + offset
    return absolute // 12, absolute % 12 + 1


def _longest_streak(values: list[date]) -> int:
    ordered = sorted(set(values))
    longest = current = 0
    previous = None
    for value in ordered:
        current = current + 1 if previous and value == previous + timedelta(days=1) else 1
        longest = max(longest, current)
        previous = value
    return longest


def _build_personal_insight_cards(
    lifetime: dict,
    recent: dict,
    stroke_distribution: list[dict],
    habits: dict,
    personal_bests: list[dict],
) -> list[dict]:
    if not lifetime["total_sessions"]:
        return [{
            "tone": "start",
            "title": "첫 기록이 데이터의 시작이에요",
            "message": "훈련 일지를 한 번 남기면 거리·시간·영법 추이를 자동으로 정리해 드립니다.",
            "action_label": "첫 훈련 기록하기",
            "action_href": "/training-log?quick=1",
        }]

    cards = []
    change_rate = recent.get("distance_change_rate")
    if change_rate is None:
        cards.append({
            "tone": "neutral",
            "title": "최근 90일 기준선을 만드는 중이에요",
            "message": f"최근 90일에 {recent['sessions']}회, {recent['distance']:,}m를 기록했습니다.",
            "action_label": "월간 흐름 보기",
            "action_href": "/report",
        })
    elif change_rate >= 5:
        cards.append({
            "tone": "positive",
            "title": "최근 훈련량이 늘고 있어요",
            "message": f"최근 90일 거리가 직전 90일보다 {abs(change_rate):g}% 증가했습니다. 회복일도 함께 지켜주세요.",
            "action_label": "다음 훈련 추천",
            "action_href": "/dashboard",
        })
    elif change_rate <= -5:
        cards.append({
            "tone": "attention",
            "title": "최근 훈련량이 줄었어요",
            "message": f"최근 90일 거리가 직전 90일보다 {abs(change_rate):g}% 감소했습니다. 부담 없는 세션부터 다시 이어가 보세요.",
            "action_label": "훈련 플랜 고르기",
            "action_href": "/plan",
        })
    else:
        cards.append({
            "tone": "steady",
            "title": "꾸준한 훈련량을 유지하고 있어요",
            "message": f"최근 90일 거리가 직전 기간과 {abs(change_rate):g}% 이내로 비슷합니다.",
            "action_label": "월간 흐름 보기",
            "action_href": "/report",
        })

    favorite = next((item for item in stroke_distribution if item["distance"] > 0), None)
    if favorite:
        cards.append({
            "tone": "focus",
            "title": f"{favorite['stroke']}이 가장 큰 비중이에요",
            "message": f"전체 기록 거리의 {favorite['share']}%가 {favorite['stroke']}입니다. 다른 영법을 섞으면 훈련 자극을 넓힐 수 있어요.",
            "action_label": "영법별 플랜 보기",
            "action_href": "/plan",
        })

    structured_rate = habits["structured_session_rate"]
    if structured_rate < 50:
        cards.append({
            "tone": "attention",
            "title": "세트 기록을 더 활용해 보세요",
            "message": f"전체 일지 중 {structured_rate}%에 세트 수행 정보가 있습니다. 세트와 사이클을 남기면 훈련 품질 변화까지 볼 수 있어요.",
            "action_label": "훈련 일지 열기",
            "action_href": "/training-log",
        })
    else:
        cards.append({
            "tone": "positive",
            "title": "구조화된 훈련 기록이 쌓이고 있어요",
            "message": f"전체 일지의 {structured_rate}%가 세트 단위로 기록되어 수행률과 사이클 변화를 해석할 수 있습니다.",
            "action_label": "풀사이드 실행",
            "action_href": "/workout",
        })

    if personal_bests:
        event_count = int(habits.get("personal_best_events") or len(personal_bests))
        cards.append({
            "tone": "record",
            "title": f"{event_count}개 종목의 현재 PB가 있어요",
            "message": "25m와 50m 코스를 분리한 현재 최고기록을 다음 테스트 세트의 기준으로 활용해 보세요.",
            "action_label": "테스트 기록 보기",
            "action_href": "/training-log",
        })
    return cards[:4]


def _fetch_rows(cur, query: str, params: tuple = ()) -> list[dict]:
    cur.execute(query, params)
    columns = [item[0] for item in cur.description]
    return [dict(zip(columns, row)) for row in cur.fetchall()]


def _table_exists(cur, table_name: str) -> bool:
    cur.execute("SELECT to_regclass(%s)", (table_name,))
    row = cur.fetchone()
    return bool(row and row[0])


def _optional_rows(
    cur,
    table_name: str,
    where_sql: str,
    params: tuple,
    order_sql: str = "",
) -> list[dict]:
    # table_name/where/order are selected only from the constant mapping below.
    if not _table_exists(cur, table_name):
        return []
    cur.execute("SAVEPOINT swimmate_export_section")
    try:
        rows = _fetch_rows(
            cur,
            f"SELECT * FROM {table_name} WHERE {where_sql} {order_sql}",
            params,
        )
        cur.execute("RELEASE SAVEPOINT swimmate_export_section")
        return rows
    except Exception:
        cur.execute("ROLLBACK TO SAVEPOINT swimmate_export_section")
        cur.execute("RELEASE SAVEPOINT swimmate_export_section")
        logger.warning("personal export section unavailable: %s", table_name, exc_info=True)
        return []


def _account_row(cur, customer_id: int) -> dict:
    rows = _fetch_rows(
        cur,
        """
        SELECT id, name, email, username, nickname, social_provider, role, status,
               level, goal, weekly_goal, preferred_pool_length,
               onboarding_completed_at, created_at, updated_at, last_login_at,
               password_changed_at, COALESCE(auth_version, 0) AS auth_version
        FROM customers
        WHERE id = %s
        """,
        (customer_id,),
    )
    if not rows:
        raise HTTPException(404, "계정 정보를 찾을 수 없습니다.")
    return rows[0]


def _security_row(cur, customer_id: int) -> tuple:
    cur.execute(
        """
        SELECT password_hash, COALESCE(social_provider, 'local'),
               COALESCE(auth_version, 0), COALESCE(status, 'active'), username
        FROM customers
        WHERE id = %s
        """,
        (customer_id,),
    )
    row = cur.fetchone()
    if not row or row[3] == "deleted":
        raise HTTPException(404, "계정 정보를 찾을 수 없습니다.")
    return row


def _verify_sensitive_action(cur, customer_id: int, current_password: str | None) -> tuple:
    row = _security_row(cur, customer_id)
    password_hash, provider = row[0], row[1]
    if provider == "demo":
        raise HTTPException(403, "체험 모드에서는 계정 보안 기능을 변경할 수 없습니다.")
    if provider == "local":
        if not current_password:
            raise HTTPException(400, "현재 비밀번호를 입력해주세요.")
        candidate = current_password.encode("utf-8")[:72]
        if not password_hash or not bcrypt.checkpw(candidate, password_hash.encode("utf-8")):
            raise HTTPException(401, "현재 비밀번호가 올바르지 않습니다.")
    return row


def _build_export(cur, customer_id: int, username: str) -> dict:
    by_customer = (
        ("training_logs", "customer_id = %s", "ORDER BY log_date, id"),
        ("training_log_sets", "customer_id = %s", "ORDER BY training_log_id, set_order, id"),
        ("swim_test_results", "customer_id = %s", "ORDER BY test_date, id"),
        ("training_goals", "customer_id = %s", "ORDER BY year, month, id"),
        ("training_readiness", "customer_id = %s", "ORDER BY check_date, id"),
        ("wearable_workouts", "customer_id = %s", "ORDER BY started_at, id"),
        ("plan_completions", "customer_id = %s", "ORDER BY completed_at, id"),
        ("posts", "customer_id = %s", "ORDER BY created_at, id"),
        ("comments", "customer_id = %s", "ORDER BY created_at, id"),
        ("post_likes", "customer_id = %s", "ORDER BY post_id"),
        ("comment_likes", "customer_id = %s", "ORDER BY comment_id"),
        ("bookmarks", "customer_id = %s", "ORDER BY created_at, post_id"),
        ("notifications", "customer_id = %s", "ORDER BY created_at, id"),
        ("feedback", "customer_id = %s", "ORDER BY created_at, id"),
        ("swim_club_members", "customer_id = %s", "ORDER BY joined_at, id"),
        ("swim_class_members", "customer_id = %s", "ORDER BY joined_at, id"),
        ("swim_class_attendance", "customer_id = %s", "ORDER BY checked_at, id"),
        ("swim_class_notice_reads", "customer_id = %s", "ORDER BY read_at, id"),
        ("coaches", "customer_id = %s", "ORDER BY id"),
        ("coach_feedbacks", "student_id = %s", "ORDER BY created_at, id"),
        ("coach_plans", "student_id = %s", "ORDER BY created_at, id"),
        ("swim_shares", "student_id = %s", "ORDER BY swim_date, id"),
        ("coach_ai_document_recipients", "student_id = %s", "ORDER BY created_at, id"),
    )
    by_username = (
        ("custom_plans", "username = %s", "ORDER BY created_at, id"),
        ("plan_favorites", "username = %s", "ORDER BY created_at, id"),
        ("preset_plan_favorites", "username = %s", "ORDER BY created_at, id"),
        ("user_badges", "username = %s", "ORDER BY earned_at, id"),
        ("challenge_participants", "username = %s", "ORDER BY joined_at, id"),
        ("pool_favorites", "username = %s", "ORDER BY created_at, id"),
        ("chat_histories", "username = %s", "ORDER BY created_at, id"),
    )

    data: dict[str, list[dict]] = {}
    for table_name, where_sql, order_sql in by_customer:
        data[table_name] = _optional_rows(
            cur, table_name, where_sql, (customer_id,), order_sql
        )
    for table_name, where_sql, order_sql in by_username:
        data[table_name] = _optional_rows(
            cur, table_name, where_sql, (username,), order_sql
        )
    if _table_exists(cur, "reports"):
        data["reports"] = _optional_rows(
            cur, "reports", "reporter_id = %s", (customer_id,), "ORDER BY created_at, id"
        )

    return {
        "export_format": "swimmate-personal-data",
        "export_schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "account": _account_row(cur, customer_id),
        "records": data,
        "record_counts": {key: len(value) for key, value in data.items()},
        "security_note": (
            "비밀번호 해시, JWT, 소셜 제공자 식별자, 관리자·외부 서비스 비밀값, "
            "다른 회원의 계정 프로필은 포함하지 않습니다."
        ),
    }


@router.get("/insights")
@limiter.limit("60/minute")
def get_personal_data_insights(
    request: Request,
    swimtech_token: str = Cookie(default=None),
):
    """본인 훈련 기록을 장기 추이와 기록 습관으로 해석해 반환한다."""
    payload, customer_id = _authenticated_customer(swimtech_token)
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT COUNT(*),
                   COALESCE(SUM(total_distance), 0),
                   COALESCE(SUM(duration_minutes), 0),
                   MIN(log_date), MAX(log_date),
                   COUNT(DISTINCT log_date),
                   COUNT(DISTINCT date_trunc('month', log_date))
            FROM training_logs
            WHERE customer_id = %s
            """,
            (customer_id,),
        )
        row = cur.fetchone() or (0, 0, 0, None, None, 0, 0)
        total_sessions = int(row[0] or 0)
        total_distance = int(row[1] or 0)
        total_minutes = int(row[2] or 0)
        lifetime = {
            "total_sessions": total_sessions,
            "total_distance": total_distance,
            "total_minutes": total_minutes,
            "average_distance": round(total_distance / total_sessions) if total_sessions else 0,
            "average_minutes": round(total_minutes / total_sessions) if total_sessions else 0,
            "first_training_date": row[3].isoformat() if row[3] else None,
            "last_training_date": row[4].isoformat() if row[4] else None,
            "active_days": int(row[5] or 0),
            "active_months": int(row[6] or 0),
        }

        cur.execute(
            "SELECT DISTINCT log_date FROM training_logs WHERE customer_id = %s ORDER BY log_date",
            (customer_id,),
        )
        lifetime["longest_streak"] = _longest_streak([item[0] for item in cur.fetchall()])

        today = date.today()
        recent_start = today - timedelta(days=89)
        previous_start = today - timedelta(days=179)
        previous_end = recent_start - timedelta(days=1)
        cur.execute(
            """
            SELECT
                COUNT(*) FILTER (WHERE log_date BETWEEN %s AND %s),
                COALESCE(SUM(total_distance) FILTER (WHERE log_date BETWEEN %s AND %s), 0),
                COALESCE(SUM(duration_minutes) FILTER (WHERE log_date BETWEEN %s AND %s), 0),
                COUNT(*) FILTER (WHERE log_date BETWEEN %s AND %s),
                COALESCE(SUM(total_distance) FILTER (WHERE log_date BETWEEN %s AND %s), 0)
            FROM training_logs
            WHERE customer_id = %s
            """,
            (
                recent_start, today,
                recent_start, today,
                recent_start, today,
                previous_start, previous_end,
                previous_start, previous_end,
                customer_id,
            ),
        )
        recent_row = cur.fetchone() or (0, 0, 0, 0, 0)
        recent_distance = int(recent_row[1] or 0)
        previous_distance = int(recent_row[4] or 0)
        recent = {
            "days": 90,
            "sessions": int(recent_row[0] or 0),
            "distance": recent_distance,
            "minutes": int(recent_row[2] or 0),
            "previous_sessions": int(recent_row[3] or 0),
            "previous_distance": previous_distance,
            "distance_change_rate": (
                round((recent_distance - previous_distance) / previous_distance * 100, 1)
                if previous_distance else None
            ),
        }

        start_year, start_month = _shift_month(today.year, today.month, -11)
        start_date = date(start_year, start_month, 1)
        cur.execute(
            """
            SELECT to_char(date_trunc('month', log_date), 'YYYY-MM'),
                   COUNT(*), COALESCE(SUM(total_distance), 0),
                   COALESCE(SUM(duration_minutes), 0)
            FROM training_logs
            WHERE customer_id = %s AND log_date >= %s AND log_date <= %s
            GROUP BY date_trunc('month', log_date)
            ORDER BY date_trunc('month', log_date)
            """,
            (customer_id, start_date, today),
        )
        monthly_rows = {
            item[0]: {
                "month": item[0],
                "sessions": int(item[1] or 0),
                "distance": int(item[2] or 0),
                "minutes": int(item[3] or 0),
            }
            for item in cur.fetchall()
        }
        monthly_trend = []
        for offset in range(-11, 1):
            year, month = _shift_month(today.year, today.month, offset)
            key = f"{year:04d}-{month:02d}"
            monthly_trend.append(monthly_rows.get(key, {
                "month": key, "sessions": 0, "distance": 0, "minutes": 0,
            }))

        cur.execute(
            """
            SELECT COALESCE(NULLIF(TRIM(stroke_type), ''), '기타'),
                   COUNT(*), COALESCE(SUM(total_distance), 0)
            FROM training_logs
            WHERE customer_id = %s
            GROUP BY COALESCE(NULLIF(TRIM(stroke_type), ''), '기타')
            ORDER BY COALESCE(SUM(total_distance), 0) DESC
            """,
            (customer_id,),
        )
        stroke_distribution = [{
            "stroke": item[0],
            "sessions": int(item[1] or 0),
            "distance": int(item[2] or 0),
            "share": _percent(item[2], total_distance),
        } for item in cur.fetchall()]

        cur.execute(
            """
            SELECT COALESCE(pool_length, 25),
                   COUNT(*), COALESCE(SUM(total_distance), 0)
            FROM training_logs
            WHERE customer_id = %s
            GROUP BY COALESCE(pool_length, 25)
            ORDER BY COALESCE(pool_length, 25)
            """,
            (customer_id,),
        )
        pool_distribution = [{
            "pool_length": int(item[0] or 25),
            "sessions": int(item[1] or 0),
            "distance": int(item[2] or 0),
            "share": _percent(item[2], total_distance),
        } for item in cur.fetchall()]

        structured_sessions = cycle_sessions = total_sets = completed_sets = 0
        if _table_exists(cur, "training_log_sets"):
            cur.execute(
                """
                SELECT COUNT(DISTINCT training_log_id),
                       COUNT(DISTINCT training_log_id) FILTER (
                           WHERE actual_cycle_seconds IS NOT NULL
                       ),
                       COUNT(*),
                       COUNT(*) FILTER (WHERE status = 'completed')
                FROM training_log_sets
                WHERE customer_id = %s
                """,
                (customer_id,),
            )
            set_row = cur.fetchone() or (0, 0, 0, 0)
            structured_sessions = int(set_row[0] or 0)
            cycle_sessions = int(set_row[1] or 0)
            total_sets = int(set_row[2] or 0)
            completed_sets = int(set_row[3] or 0)

        plan_sessions = 0
        if _table_exists(cur, "plan_completions"):
            cur.execute(
                """
                SELECT COUNT(DISTINCT training_log_id)
                FROM plan_completions
                WHERE customer_id = %s AND training_log_id IS NOT NULL
                """,
                (customer_id,),
            )
            plan_sessions = int((cur.fetchone() or (0,))[0] or 0)

        test_attempts = personal_best_events = 0
        personal_bests = []
        if _table_exists(cur, "swim_test_results"):
            cur.execute(
                """
                SELECT COUNT(*),
                       COUNT(DISTINCT (stroke_type, distance_m, pool_length))
                FROM swim_test_results
                WHERE customer_id = %s
                """,
                (customer_id,),
            )
            benchmark_row = cur.fetchone() or (0, 0)
            test_attempts = int(benchmark_row[0] or 0)
            personal_best_events = int(benchmark_row[1] or 0)
            cur.execute(
                """
                SELECT DISTINCT ON (stroke_type, distance_m, pool_length)
                       test_date, stroke_type, distance_m, pool_length, duration_ms
                FROM swim_test_results
                WHERE customer_id = %s
                ORDER BY stroke_type, distance_m, pool_length,
                         duration_ms, test_date, id
                LIMIT 12
                """,
                (customer_id,),
            )
            personal_bests = [{
                "test_date": item[0].isoformat(),
                "stroke_type": item[1],
                "distance_m": int(item[2]),
                "pool_length": int(item[3]),
                "duration_ms": int(item[4]),
            } for item in cur.fetchall()]

        habits = {
            "structured_sessions": structured_sessions,
            "structured_session_rate": _percent(structured_sessions, total_sessions),
            "plan_sessions": plan_sessions,
            "plan_session_rate": _percent(plan_sessions, total_sessions),
            "cycle_sessions": cycle_sessions,
            "cycle_record_rate": _percent(cycle_sessions, structured_sessions),
            "total_sets": total_sets,
            "completed_sets": completed_sets,
            "set_completion_rate": _percent(completed_sets, total_sets),
            "test_attempts": test_attempts,
            "personal_best_events": personal_best_events,
        }
        insight_cards = _build_personal_insight_cards(
            lifetime, recent, stroke_distribution, habits, personal_bests
        )
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "has_data": total_sessions > 0,
            "is_demo": bool(payload.get("is_demo")),
            "privacy_scope": "authenticated_customer_only",
            "lifetime": lifetime,
            "recent_90_days": recent,
            "monthly_trend": monthly_trend,
            "stroke_distribution": stroke_distribution,
            "pool_distribution": pool_distribution,
            "recording_habits": habits,
            "personal_bests": personal_bests,
            "insight_cards": insight_cards,
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("personal data insights failed")
        raise HTTPException(500, "내 수영 데이터를 불러오지 못했습니다.")
    finally:
        cur.close()
        conn.close()


@router.post("/export")
@limiter.limit("10/hour")
def export_personal_data(
    request: Request,
    body: SensitiveActionRequest,
    swimtech_token: str = Cookie(default=None),
):
    payload, customer_id = _authenticated_customer(swimtech_token)
    if payload.get("is_demo"):
        raise HTTPException(403, "체험 모드 데이터는 내보낼 수 없습니다.")

    conn = get_db()
    cur = conn.cursor()
    try:
        _verify_sensitive_action(cur, customer_id, body.current_password)
        document = _build_export(cur, customer_id, payload.get("sub") or "")
    finally:
        cur.close()
        conn.close()

    log_activity(
        customer_id=customer_id,
        username=payload.get("sub"),
        event_type="account_security",
        action="personal_data_export",
    )
    filename = f"swimmate-personal-data-{date.today().isoformat()}.json"
    return Response(
        content=json.dumps(document, ensure_ascii=False, indent=2, default=_json_default),
        media_type="application/json; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/password")
@limiter.limit("5/hour")
def change_password(
    request: Request,
    body: PasswordChangeRequest,
    response: Response,
    swimtech_token: str = Cookie(default=None),
):
    payload, customer_id = _authenticated_customer(swimtech_token)
    if payload.get("is_demo"):
        raise HTTPException(403, "체험 모드에서는 비밀번호를 변경할 수 없습니다.")
    if not _PASSWORD_RE.match(body.new_password):
        raise HTTPException(400, "새 비밀번호는 8자 이상이며 영문과 숫자를 포함해야 합니다.")
    if body.current_password == body.new_password:
        raise HTTPException(400, "현재 비밀번호와 다른 새 비밀번호를 입력해주세요.")

    conn = get_db()
    cur = conn.cursor()
    try:
        row = _verify_sensitive_action(cur, customer_id, body.current_password)
        if row[1] != "local":
            raise HTTPException(400, "소셜 로그인 계정은 연결된 서비스에서 비밀번호를 관리합니다.")
        new_hash = bcrypt.hashpw(
            body.new_password.encode("utf-8")[:72], bcrypt.gensalt()
        ).decode("utf-8")
        cur.execute(
            """
            UPDATE customers
            SET password_hash = %s,
                auth_version = COALESCE(auth_version, 0) + 1,
                password_changed_at = NOW(),
                updated_at = NOW()
            WHERE id = %s
            RETURNING auth_version
            """,
            (new_hash, customer_id),
        )
        auth_version = int(cur.fetchone()[0])
        conn.commit()
    except HTTPException:
        conn.rollback()
        raise
    except Exception:
        conn.rollback()
        logger.exception("password change failed")
        raise HTTPException(500, "비밀번호를 변경하지 못했습니다.")
    finally:
        cur.close()
        conn.close()

    username = payload.get("sub") or row[4]
    _set_auth_cookie(
        response,
        create_token(username, customer_id, auth_version=auth_version),
    )
    _set_refresh_cookie(
        response,
        create_refresh_token(username, customer_id, auth_version=auth_version),
    )
    log_activity(
        customer_id=customer_id,
        username=username,
        event_type="account_security",
        action="password_changed",
    )
    return {
        "status": "ok",
        "message": "비밀번호를 변경하고 다른 기기의 기존 세션을 종료했습니다.",
    }


@router.post("/logout-all")
@limiter.limit("5/hour")
def logout_all_devices(
    request: Request,
    body: SensitiveActionRequest,
    response: Response,
    swimtech_token: str = Cookie(default=None),
):
    payload, customer_id = _authenticated_customer(swimtech_token)
    if payload.get("is_demo"):
        raise HTTPException(403, "체험 모드에서는 세션을 변경할 수 없습니다.")

    conn = get_db()
    cur = conn.cursor()
    try:
        _verify_sensitive_action(cur, customer_id, body.current_password)
        cur.execute(
            """
            UPDATE customers
            SET auth_version = COALESCE(auth_version, 0) + 1,
                updated_at = NOW()
            WHERE id = %s
            RETURNING auth_version
            """,
            (customer_id,),
        )
        if not cur.fetchone():
            raise HTTPException(404, "계정 정보를 찾을 수 없습니다.")
        conn.commit()
    except HTTPException:
        conn.rollback()
        raise
    except Exception:
        conn.rollback()
        logger.exception("logout all devices failed")
        raise HTTPException(500, "전체 세션을 종료하지 못했습니다.")
    finally:
        cur.close()
        conn.close()

    log_activity(
        customer_id=customer_id,
        username=payload.get("sub"),
        event_type="account_security",
        action="logout_all_devices",
    )
    response.delete_cookie("swimtech_token")
    response.delete_cookie("swimtech_refresh_token")
    return {"status": "ok", "message": "모든 기기에서 로그아웃했습니다."}
