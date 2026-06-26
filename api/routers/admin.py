"""
SwimMate - 관리자(슈퍼계정) API
role='admin' 컬럼 기반 권한 체계.
대시보드 / 사용자 관리 / 메뉴 사용 분석 / 훈련 운영 / 운영 로그.
"""
import os
import psycopg2
from fastapi import APIRouter, Request, HTTPException, Cookie
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
               to_regclass('public.plan_completions')
    """)
    has_training_logs, has_training_goals, has_custom_plans, has_plan_completions = [
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

    cur.close()
    conn.close()
    return {
        "table_status": {
            "training_logs": has_training_logs,
            "training_goals": has_training_goals,
            "custom_plans": has_custom_plans,
            "plan_completions": has_plan_completions,
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
