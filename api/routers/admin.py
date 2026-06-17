"""
SwimTech - 관리자(슈퍼계정) API
role='admin' 컬럼 기반 권한 체계.
대시보드 / 사용자 관리 / 메뉴 사용 분석 / 운영 로그.
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


@router.get("/logs")
def get_logs(swimtech_token: str = Cookie(default=None), event_type: str = None, page: int = 1, page_size: int = 50):
    """운영 로그: 로그인 성공/실패, 가입, 소셜로그인, 일지작성, 플랜공유, 오류 등."""
    _require_admin(swimtech_token)
    _ensure_table()
    conn = _get_db()
    cur = conn.cursor()
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

    cur.close()
    conn.close()
    return {"logs": logs, "page": page, "page_size": page_size}
