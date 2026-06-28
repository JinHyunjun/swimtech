"""
SwimMate - 관리자(슈퍼계정) API
role='admin' 컬럼 기반 권한 체계.
대시보드 / 사용자 관리 / 메뉴 사용 분석 / 훈련 운영 / 운영 로그.
"""
import os
import psycopg2
from fastapi import APIRouter, Request, HTTPException, Cookie
from pydantic import BaseModel, Field
from routers.auth import decode_token
from activity_log import log_activity, resolve_menu_name

router = APIRouter()
DATABASE_URL = os.getenv("DATABASE_URL", "")


def _get_db():
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    cur.execute("SET TIME ZONE 'Asia/Seoul'")
    cur.close()
    return conn


def _ensure_table():
    conn = _get_db()
    cur = conn.cursor()
    cur.execute("ALTER TABLE customers ADD COLUMN IF NOT EXISTS role TEXT")
    cur.execute("ALTER TABLE customers ADD COLUMN IF NOT EXISTS status TEXT")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS user_activity_logs (
            id          SERIAL PRIMARY KEY,
            customer_id INTEGER,
            username    TEXT,
            event_type  TEXT NOT NULL,
            page        TEXT,
            menu_name   TEXT,
            action      TEXT,
            method      TEXT,
            path        TEXT,
            ip_address  TEXT,
            user_agent  TEXT,
            metadata    JSONB,
            created_at  TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_activity_created ON user_activity_logs(created_at)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_activity_customer ON user_activity_logs(customer_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_activity_event ON user_activity_logs(event_type)")
    conn.commit()
    cur.close()
    conn.close()


def _safe_int(value, default=0):
    try:
        return int(value or default)
    except Exception:
        return default


def _safe_float(value, default=0.0):
    try:
        return float(value or default)
    except Exception:
        return default


def _normalize_page_size(value, default=20):
    size = _safe_int(value, default)
    return size if size in (20, 50, 100) else default


def _ensure_coach_verification(cur):
    cur.execute("SELECT to_regclass('public.coaches')")
    if not cur.fetchone()[0]:
        return False
    cur.execute("ALTER TABLE coaches ADD COLUMN IF NOT EXISTS credential_type VARCHAR(60)")
    cur.execute("ALTER TABLE coaches ADD COLUMN IF NOT EXISTS credential_number VARCHAR(120)")
    cur.execute("ALTER TABLE coaches ADD COLUMN IF NOT EXISTS credential_organization VARCHAR(120)")
    cur.execute("ALTER TABLE coaches ADD COLUMN IF NOT EXISTS verification_status VARCHAR(12) NOT NULL DEFAULT 'pending'")
    cur.execute("ALTER TABLE coaches ADD COLUMN IF NOT EXISTS verification_note TEXT")
    cur.execute("ALTER TABLE coaches ADD COLUMN IF NOT EXISTS verified_at TIMESTAMPTZ")
    cur.execute("ALTER TABLE coaches ADD COLUMN IF NOT EXISTS verified_by VARCHAR(100)")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS coach_verification_events (
            id          SERIAL PRIMARY KEY,
            coach_id    INTEGER NOT NULL REFERENCES coaches(id) ON DELETE CASCADE,
            reviewer    VARCHAR(100) NOT NULL,
            status      VARCHAR(12) NOT NULL,
            note        TEXT,
            created_at  TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    return True


class CoachVerificationBody(BaseModel):
    status: str = Field(..., max_length=12)
    note: str | None = Field(default=None, max_length=500)


def _require_admin(swimtech_token: str):
    """role='admin' 우선 확인, 없으면 ADMIN_ID 폴백(과도기 호환)."""
    if not swimtech_token:
        raise HTTPException(401, "로그인이 필요합니다.")
    payload = decode_token(swimtech_token)
    username = payload.get("sub")
    customer_id = payload.get("customer_id")
    if not username:
        raise HTTPException(401, "세션이 만료되었습니다. 다시 로그인해주세요.")

    conn = _get_db()
    cur = conn.cursor()
    is_admin = False
    if customer_id:
        cur.execute("SELECT role FROM customers WHERE id = %s", (customer_id,))
        row = cur.fetchone()
        if row and row[0] == "admin":
            is_admin = True
    if not is_admin and username == os.getenv("ADMIN_ID", "admin"):
        is_admin = True  # 환경변수 ADMIN_ID 계정도 관리자로 인정 (과도기 호환)
    cur.close()
    conn.close()

    if not is_admin:
        raise HTTPException(403, "관리자 권한이 필요합니다.")
    return username


@router.post("/track")
def track_page_view(request: Request, swimtech_token: str = Cookie(default=None)):
    """프론트(theme.js)에서 호출하는 페이지뷰 추적. 인증 불필요(비로그인 방문도 기록 가능)."""
    try:
        page = request.query_params.get("page")
        menu = resolve_menu_name(page) if page else None
        if not menu:
            return {"status": "skipped"}

        username = None
        customer_id = None
        if swimtech_token:
            try:
                payload = decode_token(swimtech_token)
                username = payload.get("sub")
                customer_id = payload.get("customer_id")
            except Exception:
                pass

        log_activity(
            customer_id=customer_id, username=username,
            event_type="page_view", page=page, menu_name=menu,
            method="GET", path=page,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
        return {"status": "ok"}
    except Exception:
        return {"status": "error"}


@router.get("/dashboard")
def get_dashboard(swimtech_token: str = Cookie(default=None)):
    _require_admin(swimtech_token)
    _ensure_table()
    conn = _get_db()
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM customers WHERE COALESCE(status,'active') <> 'deleted'")
    total_users = cur.fetchone()[0]

    cur.execute("""
        SELECT COUNT(*) FROM customers
        WHERE created_at >= CURRENT_DATE AND COALESCE(status,'active') <> 'deleted'
    """)
    today_signups = cur.fetchone()[0]

    cur.execute("""
        SELECT COUNT(*) FROM customers
        WHERE created_at >= NOW() - INTERVAL '7 days' AND COALESCE(status,'active') <> 'deleted'
    """)
    week_signups = cur.fetchone()[0]

    cur.execute("""
        SELECT COALESCE(social_provider, 'local') AS provider, COUNT(*)
        FROM customers
        WHERE COALESCE(status,'active') <> 'deleted'
        GROUP BY provider
    """)
    by_provider = {row[0]: row[1] for row in cur.fetchall()}

    cur.execute("""
        SELECT id, name, username, COALESCE(social_provider,'local'),
               created_at AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Seoul' AS created_at
        FROM customers
        WHERE COALESCE(status,'active') <> 'deleted'
        ORDER BY created_at DESC
        LIMIT 10
    """)
    recent = [
        {"id": r[0], "name": r[1], "username": r[2], "provider": r[3], "created_at": str(r[4])}
        for r in cur.fetchall()
    ]

    cur.close()
    conn.close()
    return {
        "total_users": total_users,
        "today_signups": today_signups,
        "week_signups": week_signups,
        "by_provider": {
            "kakao": by_provider.get("kakao", 0),
            "google": by_provider.get("google", 0),
            "local": by_provider.get("local", 0),
        },
        "recent_signups": recent,
    }


@router.get("/users")
def list_users(swimtech_token: str = Cookie(default=None), q: str = None, page: int = 1, page_size: int = 20):
    _require_admin(swimtech_token)
    conn = _get_db()
    cur = conn.cursor()
    page = max(1, _safe_int(page, 1))
    page_size = _normalize_page_size(page_size, 20)
    offset = max(0, (page - 1) * page_size)

    if q:
        like = f"%{q}%"
        cur.execute("""
            SELECT id, name, email, username, nickname,
                   COALESCE(social_provider,'local'),
                   created_at AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Seoul' AS created_at,
                   last_login_at AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Seoul' AS last_login_at,
                   COALESCE(status,'active')
            FROM customers
            WHERE (name ILIKE %s OR email ILIKE %s OR username ILIKE %s OR nickname ILIKE %s)
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
        """, (like, like, like, like, page_size, offset))
    else:
        cur.execute("""
            SELECT id, name, email, username, nickname,
                   COALESCE(social_provider,'local'),
                   created_at AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Seoul' AS created_at,
                   last_login_at AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Seoul' AS last_login_at,
                   COALESCE(status,'active')
            FROM customers
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
        """, (page_size, offset))

    users = [{
        "id": r[0], "name": r[1], "email": r[2], "username": r[3], "nickname": r[4],
        "provider": r[5], "created_at": str(r[6]),
        "last_login_at": str(r[7]) if r[7] else None, "status": r[8],
    } for r in cur.fetchall()]

    if q:
        cur.execute("""
            SELECT COUNT(*) FROM customers
            WHERE (name ILIKE %s OR email ILIKE %s OR username ILIKE %s OR nickname ILIKE %s)
        """, (like, like, like, like))
    else:
        cur.execute("SELECT COUNT(*) FROM customers")
    total = cur.fetchone()[0]
    cur.close()
    conn.close()
    return {"users": users, "total": total, "page": page, "page_size": page_size}


@router.get("/activity")
def get_activity(swimtech_token: str = Cookie(default=None)):
    """메뉴 사용 분석: 오늘 인기 메뉴, 최근 7일 메뉴별 클릭, 사용자별 자주 쓰는 메뉴."""
    _require_admin(swimtech_token)
    _ensure_table()
    conn = _get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT menu_name, COUNT(*) AS cnt
        FROM user_activity_logs
        WHERE event_type = 'page_view' AND menu_name IS NOT NULL
              AND created_at >= CURRENT_DATE
        GROUP BY menu_name ORDER BY cnt DESC LIMIT 10
    """)
    today_top_menus = [{"menu": r[0], "count": r[1]} for r in cur.fetchall()]

    cur.execute("""
        SELECT menu_name, COUNT(*) AS cnt
        FROM user_activity_logs
        WHERE event_type = 'page_view' AND menu_name IS NOT NULL
              AND created_at >= NOW() - INTERVAL '7 days'
        GROUP BY menu_name ORDER BY cnt DESC LIMIT 20
    """)
    week_menu_clicks = [{"menu": r[0], "count": r[1]} for r in cur.fetchall()]

    cur.execute("""
        SELECT event_type, COUNT(*) AS cnt
        FROM user_activity_logs
        WHERE created_at >= NOW() - INTERVAL '7 days'
              AND event_type IN ('training_log_create','plan_share')
        GROUP BY event_type
    """)
    counts = {r[0]: r[1] for r in cur.fetchall()}

    cur.close()
    conn.close()
    return {
        "today_top_menus": today_top_menus,
        "week_menu_clicks": week_menu_clicks,
        "training_log_writes_7d": counts.get("training_log_create", 0),
        "plan_shares_7d": counts.get("plan_share", 0),
    }


@router.get("/coaches")
def list_coach_verifications(
    swimtech_token: str = Cookie(default=None),
    status: str = "pending",
    page: int = 1,
    page_size: int = 20,
):
    """코치 자격 검토 목록. 자격 번호는 관리자에게만 노출한다."""
    _require_admin(swimtech_token)
    page = max(1, _safe_int(page, 1))
    page_size = _normalize_page_size(page_size, 20)
    offset = (page - 1) * page_size
    status = status if status in ("pending", "verified", "rejected", "all") else "pending"
    conn = _get_db()
    cur = conn.cursor()
    try:
        if not _ensure_coach_verification(cur):
            conn.commit()
            return {"coaches": [], "total": 0, "page": page, "page_size": page_size, "status": status,
                    "summary": {"pending": 0, "verified": 0, "rejected": 0, "documents_30d": 0, "published_30d": 0}}
        cur.execute("""
            SELECT COUNT(*) FILTER (WHERE COALESCE(verification_status, 'pending') = 'pending'),
                   COUNT(*) FILTER (WHERE verification_status = 'verified'),
                   COUNT(*) FILTER (WHERE verification_status = 'rejected')
            FROM coaches
        """)
        counts = cur.fetchone()
        summary = {
            "pending": _safe_int(counts[0]), "verified": _safe_int(counts[1]),
            "rejected": _safe_int(counts[2]), "documents_30d": 0, "published_30d": 0,
        }
        cur.execute("SELECT to_regclass('public.coach_ai_documents')")
        if cur.fetchone()[0]:
            cur.execute("""
                SELECT COUNT(*) FILTER (WHERE created_at >= NOW() - INTERVAL '30 days'),
                       COUNT(*) FILTER (WHERE published_at >= NOW() - INTERVAL '30 days')
                FROM coach_ai_documents
            """)
            docs = cur.fetchone()
            summary["documents_30d"] = _safe_int(docs[0])
            summary["published_30d"] = _safe_int(docs[1])
        where = "" if status == "all" else "WHERE COALESCE(co.verification_status, 'pending') = %s"
        params = [] if status == "all" else [status]
        cur.execute(
            f"""
            SELECT co.id, c.name, c.username, c.email, co.specialty, co.career,
                   co.credential_type, co.credential_number, co.credential_organization,
                   COALESCE(co.verification_status, 'pending'), co.verification_note,
                   co.created_at, co.verified_at, co.verified_by
            FROM coaches co JOIN customers c ON c.id = co.customer_id
            {where}
            ORDER BY CASE COALESCE(co.verification_status, 'pending') WHEN 'pending' THEN 0 ELSE 1 END,
                     co.created_at DESC
            LIMIT %s OFFSET %s
            """,
            (*params, page_size, offset),
        )
        coaches = [{
            "id": r[0], "name": r[1], "username": r[2], "email": r[3],
            "specialty": r[4], "career": r[5], "credential_type": r[6],
            "credential_number": r[7], "credential_organization": r[8],
            "verification_status": r[9], "verification_note": r[10],
            "created_at": str(r[11]), "verified_at": str(r[12]) if r[12] else None,
            "verified_by": r[13],
        } for r in cur.fetchall()]
        cur.execute(
            f"SELECT COUNT(*) FROM coaches co {where}",
            tuple(params),
        )
        total = _safe_int(cur.fetchone()[0])
        conn.commit()
        return {"coaches": coaches, "total": total, "page": page, "page_size": page_size,
                "status": status, "summary": summary}
    finally:
        cur.close()
        conn.close()


@router.patch("/coaches/{coach_id}/verification")
def update_coach_verification(
    coach_id: int,
    body: CoachVerificationBody,
    swimtech_token: str = Cookie(default=None),
):
    """관리자가 코치 자격을 승인하거나 사유와 함께 반려한다."""
    reviewer = _require_admin(swimtech_token)
    status = (body.status or "").strip().lower()
    note = (body.note or "").strip() or None
    if status not in ("verified", "rejected"):
        raise HTTPException(400, "승인 또는 반려 상태만 선택할 수 있습니다.")
    if status == "rejected" and not note:
        raise HTTPException(400, "반려 사유를 입력해주세요.")
    conn = _get_db()
    cur = conn.cursor()
    try:
        if not _ensure_coach_verification(cur):
            raise HTTPException(404, "코치 정보를 찾을 수 없습니다.")
        cur.execute(
            """
            UPDATE coaches SET verification_status = %s, verification_note = %s,
                verified_at = CASE WHEN %s = 'verified' THEN NOW() ELSE NULL END,
                verified_by = CASE WHEN %s = 'verified' THEN %s ELSE NULL END
            WHERE id = %s RETURNING customer_id
            """,
            (status, note, status, status, reviewer, coach_id),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "코치 정보를 찾을 수 없습니다.")
        cur.execute(
            "INSERT INTO coach_verification_events (coach_id, reviewer, status, note) VALUES (%s,%s,%s,%s)",
            (coach_id, reviewer, status, note),
        )
        cur.execute("SELECT to_regclass('public.notifications')")
        if cur.fetchone()[0]:
            message = "코치 본인 확인이 완료되었습니다." if status == "verified" else f"코치 본인 확인이 반려되었습니다: {note}"
            cur.execute(
                "INSERT INTO notifications (customer_id, type, message, target_id) VALUES (%s,%s,%s,%s)",
                (row[0], "coach_verification", message, coach_id),
            )
        conn.commit()
        return {"coach_id": coach_id, "verification_status": status, "reviewer": reviewer}
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(500, f"코치 인증 처리 오류: {e}")
    finally:
        cur.close()
        conn.close()


@router.get("/training-health")
def get_training_health(swimtech_token: str = Cookie(default=None)):
    """관리자용 훈련 운영 지표.

    신규 훈련 기능이 늘어날수록 슈퍼계정에서 확인해야 하는 값도 늘어나므로,
    훈련 일지·월간 목표·플랜 완료·수영장 길이/영법 분포를 한 번에 집계한다.
    """
    _require_admin(swimtech_token)
    _ensure_table()
    conn = _get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT to_regclass('public.training_logs'),
               to_regclass('public.training_goals'),
               to_regclass('public.custom_plans'),
               to_regclass('public.plan_completions'),
               to_regclass('public.training_readiness')
    """)
    (
        has_training_logs,
        has_training_goals,
        has_custom_plans,
        has_plan_completions,
        has_training_readiness,
    ) = [
        bool(x) for x in cur.fetchone()
    ]

    summary = {
        "logs_30d": 0,
        "active_users_30d": 0,
        "distance_30d": 0,
        "avg_distance_30d": 0,
        "avg_duration_30d": 0,
        "goal_users_this_month": 0,
        "goal_achievement_rate": 0,
        "custom_plans_30d": 0,
        "custom_plan_users_30d": 0,
        "plan_completions_30d": 0,
        "plan_completion_users_30d": 0,
        "plan_completion_logs_30d": 0,
        "plan_completion_distance_30d": 0,
        "readiness_checkins_7d": 0,
        "readiness_users_7d": 0,
        "readiness_avg_score_7d": 0,
        "readiness_recovery_rate_7d": 0,
    }
    pool_distribution = []
    stroke_distribution = []
    recent_logs = []

    if has_training_logs:
        cur.execute("""
            SELECT COUNT(*),
                   COUNT(DISTINCT customer_id),
                   COALESCE(SUM(total_distance), 0),
                   COALESCE(AVG(NULLIF(total_distance, 0)), 0),
                   COALESCE(AVG(NULLIF(duration_minutes, 0)), 0)
            FROM training_logs
            WHERE log_date >= CURRENT_DATE - INTERVAL '30 days'
        """)
        row = cur.fetchone()
        summary.update({
            "logs_30d": _safe_int(row[0]),
            "active_users_30d": _safe_int(row[1]),
            "distance_30d": _safe_int(row[2]),
            "avg_distance_30d": round(_safe_float(row[3]), 1),
            "avg_duration_30d": round(_safe_float(row[4]), 1),
        })

        cur.execute("""
            SELECT COALESCE(pool_length, 25), COUNT(*), COALESCE(SUM(total_distance), 0)
            FROM training_logs
            WHERE log_date >= CURRENT_DATE - INTERVAL '30 days'
            GROUP BY COALESCE(pool_length, 25)
            ORDER BY COALESCE(pool_length, 25)
        """)
        pool_distribution = [
            {"pool_length": _safe_int(r[0]), "count": _safe_int(r[1]), "distance": _safe_int(r[2])}
            for r in cur.fetchall()
        ]

        cur.execute("""
            SELECT COALESCE(stroke_type, '기타'), COUNT(*), COALESCE(SUM(total_distance), 0)
            FROM training_logs
            WHERE log_date >= CURRENT_DATE - INTERVAL '30 days'
            GROUP BY COALESCE(stroke_type, '기타')
            ORDER BY COALESCE(SUM(total_distance), 0) DESC
            LIMIT 8
        """)
        stroke_distribution = [
            {"stroke_type": r[0], "count": _safe_int(r[1]), "distance": _safe_int(r[2])}
            for r in cur.fetchall()
        ]

        cur.execute("""
            SELECT tl.log_date,
                   COALESCE(c.username, '-'),
                   COALESCE(c.name, '-'),
                   tl.stroke_type,
                   tl.total_distance,
                   tl.duration_minutes,
                   COALESCE(tl.pool_length, 25),
                   tl.intensity
            FROM training_logs tl
            LEFT JOIN customers c ON c.id = tl.customer_id
            ORDER BY tl.log_date DESC, tl.created_at DESC
            LIMIT 8
        """)
        recent_logs = [{
            "log_date": str(r[0]),
            "username": r[1],
            "name": r[2],
            "stroke_type": r[3],
            "total_distance": _safe_int(r[4]),
            "duration_minutes": _safe_int(r[5]),
            "pool_length": _safe_int(r[6], 25),
            "intensity": r[7],
        } for r in cur.fetchall()]

    if has_training_logs and has_training_goals:
        cur.execute("""
            WITH monthly AS (
                SELECT customer_id, COALESCE(SUM(total_distance), 0) AS achieved
                FROM training_logs
                WHERE EXTRACT(YEAR FROM log_date) = EXTRACT(YEAR FROM CURRENT_DATE)
                  AND EXTRACT(MONTH FROM log_date) = EXTRACT(MONTH FROM CURRENT_DATE)
                GROUP BY customer_id
            )
            SELECT COUNT(*),
                   COALESCE(AVG(
                       CASE
                         WHEN tg.goal_distance > 0
                         THEN LEAST(100, COALESCE(monthly.achieved, 0)::numeric / tg.goal_distance * 100)
                         ELSE 0
                       END
                   ), 0)
            FROM training_goals tg
            LEFT JOIN monthly ON monthly.customer_id = tg.customer_id
            WHERE tg.year = EXTRACT(YEAR FROM CURRENT_DATE)::int
              AND tg.month = EXTRACT(MONTH FROM CURRENT_DATE)::int
        """)
        row = cur.fetchone()
        summary["goal_users_this_month"] = _safe_int(row[0])
        summary["goal_achievement_rate"] = round(_safe_float(row[1]))

    if has_custom_plans:
        cur.execute("""
            SELECT COUNT(*), COUNT(DISTINCT username)
            FROM custom_plans
            WHERE created_at >= NOW() - INTERVAL '30 days'
        """)
        row = cur.fetchone()
        summary["custom_plans_30d"] = _safe_int(row[0])
        summary["custom_plan_users_30d"] = _safe_int(row[1])

    if has_plan_completions:
        cur.execute("""
            SELECT COUNT(*), COUNT(DISTINCT customer_id), COUNT(training_log_id)
            FROM plan_completions
            WHERE completed_at >= NOW() - INTERVAL '30 days'
        """)
        row = cur.fetchone()
        summary["plan_completions_30d"] = _safe_int(row[0])
        summary["plan_completion_users_30d"] = _safe_int(row[1])
        summary["plan_completion_logs_30d"] = _safe_int(row[2])

        if has_training_logs:
            cur.execute("""
                SELECT COALESCE(SUM(tl.total_distance), 0)
                FROM plan_completions pc
                JOIN training_logs tl ON tl.id = pc.training_log_id
                WHERE pc.completed_at >= NOW() - INTERVAL '30 days'
            """)
            summary["plan_completion_distance_30d"] = _safe_int(cur.fetchone()[0])

    if has_training_readiness:
        cur.execute("""
            SELECT COUNT(*),
                   COUNT(DISTINCT customer_id),
                   COALESCE(AVG(readiness_score), 0),
                   COUNT(*) FILTER (WHERE readiness_score < 50)
            FROM training_readiness
            WHERE check_date >= CURRENT_DATE - INTERVAL '6 days'
        """)
        row = cur.fetchone()
        checkins = _safe_int(row[0])
        recovery_count = _safe_int(row[3])
        summary.update({
            "readiness_checkins_7d": checkins,
            "readiness_users_7d": _safe_int(row[1]),
            "readiness_avg_score_7d": round(_safe_float(row[2])),
            "readiness_recovery_rate_7d": round(recovery_count / checkins * 100) if checkins else 0,
        })

    cur.close()
    conn.close()
    return {
        "table_status": {
            "training_logs": has_training_logs,
            "training_goals": has_training_goals,
            "custom_plans": has_custom_plans,
            "plan_completions": has_plan_completions,
            "training_readiness": has_training_readiness,
        },
        "summary": summary,
        "pool_distribution": pool_distribution,
        "stroke_distribution": stroke_distribution,
        "recent_logs": recent_logs,
        "watchlist": [
            {
                "label": "훈련 일지 ↔ 월간 리포트",
                "status": "QA 필수",
                "detail": "total/count/avg/goal/plan_performance가 함께 갱신되는지 확인",
            },
            {
                "label": "플랜 완료 세션",
                "status": "운영 확인",
                "detail": "일지 삭제 시 plan_completions가 남지 않는지 확인",
            },
            {
                "label": "25m / 50m 풀 분포",
                "status": "운영 확인",
                "detail": "추천 플랜과 일지 기록의 pool_length가 실제 선택과 일치하는지 확인",
            },
            {
                "label": "당일 준비도 기반 추천",
                "status": "회복 우선 관찰" if summary["readiness_recovery_rate_7d"] >= 40 else "운영 확인",
                "detail": (
                    f"최근 7일 체크인 {summary['readiness_checkins_7d']}건 · "
                    f"평균 {summary['readiness_avg_score_7d']}점 · "
                    f"회복 우선 {summary['readiness_recovery_rate_7d']}%"
                ),
            },
        ],
    }


@router.get("/logs")
def get_logs(swimtech_token: str = Cookie(default=None), event_type: str = None, page: int = 1, page_size: int = 50):
    """운영 로그: 로그인 성공/실패, 가입, 소셜로그인, 일지작성, 플랜공유, 오류 등."""
    _require_admin(swimtech_token)
    _ensure_table()
    conn = _get_db()
    cur = conn.cursor()
    page = max(1, _safe_int(page, 1))
    page_size = _normalize_page_size(page_size, 50)
    offset = max(0, (page - 1) * page_size)

    if event_type:
        cur.execute("""
            SELECT id, username, event_type, page, action, method, path,
                   ip_address, created_at, metadata
            FROM user_activity_logs
            WHERE event_type = %s
            ORDER BY created_at DESC LIMIT %s OFFSET %s
        """, (event_type, page_size, offset))
    else:
        cur.execute("""
            SELECT id, username, event_type, page, action, method, path,
                   ip_address, created_at, metadata
            FROM user_activity_logs
            ORDER BY created_at DESC LIMIT %s OFFSET %s
        """, (page_size, offset))

    logs = [{
        "id": r[0], "username": r[1], "event_type": r[2], "page": r[3],
        "action": r[4], "method": r[5], "path": r[6], "ip_address": r[7],
        "created_at": str(r[8]), "metadata": r[9],
    } for r in cur.fetchall()]

    if event_type:
        cur.execute("SELECT COUNT(*) FROM user_activity_logs WHERE event_type = %s", (event_type,))
    else:
        cur.execute("SELECT COUNT(*) FROM user_activity_logs")
    total = cur.fetchone()[0]

    cur.close()
    conn.close()
    return {"logs": logs, "total": total, "page": page, "page_size": page_size}
