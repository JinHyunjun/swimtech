"""Personal data portability and account security endpoints."""

import json
import logging
from datetime import date, datetime, timezone
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
