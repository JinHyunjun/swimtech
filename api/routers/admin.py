"""
SwimMate - 관리자(슈퍼계정) API
role='admin' 컬럼 기반 권한 체계.
대시보드 / 사용자 관리 / 메뉴 사용 분석 / 훈련 운영 / 운영 로그.
"""
import os
import re
from fastapi import APIRouter, Request, HTTPException, Cookie
from pydantic import BaseModel, Field
from routers.auth import decode_token
from activity_log import log_activity, resolve_menu_name
from db import get_db

router = APIRouter()


def _get_db():
    """관리자 전용: 서울 타임존으로 커넥션 초기화."""
    conn = get_db()
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


def _clean_search(value):
    """관리자 검색어를 공백 제거 후 과도한 쿼리를 막는 길이로 제한한다."""
    return str(value or "").strip()[:100]


def _build_search_filter(q, search_by, field_map):
    """화이트리스트 컬럼만 사용하는 ILIKE 검색 조건을 만든다.

    컬럼 표현식은 서버 코드에 선언된 field_map에서만 가져오므로 search_by 값이
    SQL 식별자로 직접 들어가지 않는다.
    """
    term = _clean_search(q)
    category = search_by if search_by in field_map else "all"
    if not term:
        return "", [], category, term
    expressions = field_map[category]
    clause = "(" + " OR ".join(f"{expr} ILIKE %s" for expr in expressions) + ")"
    return clause, [f"%{term}%"] * len(expressions), category, term


def _where_clause(conditions):
    return "WHERE " + " AND ".join(conditions) if conditions else ""


def _ensure_coach_verification(cur):
    cur.execute("SELECT to_regclass('public.coaches')")
    if not cur.fetchone()[0]:
        return False
    cur.execute("ALTER TABLE coaches ADD COLUMN IF NOT EXISTS credential_type VARCHAR(60)")
    cur.execute("ALTER TABLE coaches ADD COLUMN IF NOT EXISTS credential_number VARCHAR(120)")
    cur.execute("ALTER TABLE coaches ADD COLUMN IF NOT EXISTS credential_organization VARCHAR(120)")
    cur.execute("ALTER TABLE coaches ADD COLUMN IF NOT EXISTS verification_status VARCHAR(12) NOT NULL DEFAULT 'unverified'")
    cur.execute("ALTER TABLE coaches ALTER COLUMN verification_status SET DEFAULT 'unverified'")
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


class QAAccountFlagBody(BaseModel):
    usernames: list[str] = Field(..., min_length=1, max_length=100)
    is_qa_account: bool = True


QA_AUTOMATION_HEADER = "x-swimmate-qa-run"
_QA_IDENTIFIER_RE = re.compile(
    r"(?:^|[_-])(?:qa(?:bot|test|user|student|coach|runner|\d*)?|e2e|playwright|selenium|autotest|test(?:user|student|coach|runner|\d*)?)(?:$|[_-])",
    re.IGNORECASE,
)
_QA_SQL_IDENTIFIER_PATTERN = (
    r"(^|[_-])(qa(bot|test|user|student|coach|runner|[0-9]*)?|e2e|playwright|selenium|autotest|"
    r"test(user|student|coach|runner|[0-9]*)?)($|[_-])"
)


def _normalize_account_scope(value):
    return value if value in ("regular", "qa", "all") else "regular"


def _normalize_user_account_scope(value):
    return value if value in ("all", "regular", "qa", "candidate") else "all"


def _qa_candidate_filter(alias="c"):
    """Return a review-only heuristic; it never changes an account automatically."""
    return f"""(
        LOWER(COALESCE({alias}.username, '')) ~ '{_QA_SQL_IDENTIFIER_PATTERN}'
        OR (
            LOWER(SPLIT_PART(COALESCE({alias}.email, ''), '@', 1)) ~ '{_QA_SQL_IDENTIFIER_PATTERN}'
            AND (
                LOWER(COALESCE({alias}.name, '')) IN ('qa', 'qa bot', 'test', 'test user', '테스트', '자동 검증')
                OR LOWER(COALESCE({alias}.nickname, '')) IN ('qa', 'qa bot', 'test', 'test user', '테스트', '자동 검증')
            )
        )
    )"""


def _qa_candidate_evidence(user):
    """Explain why an account should be reviewed without silently classifying it."""
    if bool(user.get("is_qa_account")):
        return {"is_candidate": False, "confidence": "confirmed", "score": 100, "reasons": ["관리자 확정 QA 계정"]}

    reasons = []
    score = 0
    username = str(user.get("username") or "").strip()
    email_local = str(user.get("email") or "").partition("@")[0].strip()
    display_values = [str(user.get("name") or "").strip().lower(), str(user.get("nickname") or "").strip().lower()]
    if _QA_IDENTIFIER_RE.search(username):
        score += 60
        reasons.append("아이디가 자동 검증 명명 규칙과 일치")
    if _QA_IDENTIFIER_RE.search(email_local):
        score += 30
        reasons.append("이메일 식별자가 자동 검증 명명 규칙과 일치")
    if any(value in {"qa", "qa bot", "test", "test user", "테스트", "자동 검증"} for value in display_values):
        score += 25
        reasons.append("표시 이름이 QA·테스트 용도를 나타냄")
    if _safe_int(user.get("activity_count")) >= 20 and _safe_int(user.get("training_log_count")) == 0:
        score += 10
        reasons.append("반복 접속 이력은 있으나 훈련 기록이 없음")

    confidence = "high" if score >= 75 else "medium" if score >= 50 else "low"
    return {"is_candidate": score >= 50, "confidence": confidence, "score": score, "reasons": reasons}


def _log_scope_filter(account_scope, alias="l"):
    """Return a server-owned SQL fragment that separates QA and regular activity.

    Successful authenticated activity is matched by customer_id. Registration and
    failed-login events do not yet have a customer_id, so the immutable log username
    is used as a fallback only for those rows.
    """
    scope = _normalize_account_scope(account_scope)
    if scope == "all":
        return ""
    qa_match = f"""(
        EXISTS (
            SELECT 1 FROM customers qa
            WHERE COALESCE(qa.is_qa_account, FALSE) = TRUE
              AND (
                  qa.id = {alias}.customer_id
                  OR (
                      {alias}.customer_id IS NULL
                      AND {alias}.username IS NOT NULL
                      AND LOWER(qa.username) = LOWER({alias}.username)
                  )
              )
        )
        OR COALESCE({alias}.metadata ->> 'qa_automation', 'false') = 'true'
        OR (
            {alias}.customer_id IS NULL
            AND {alias}.username IS NULL
            AND NULLIF({alias}.ip_address, '') IS NOT NULL
            AND NULLIF({alias}.user_agent, '') IS NOT NULL
            AND EXISTS (
                SELECT 1
                FROM user_activity_logs qa_anchor
                JOIN customers qa ON qa.id = qa_anchor.customer_id
                WHERE COALESCE(qa.is_qa_account, FALSE) = TRUE
                  AND qa_anchor.ip_address = {alias}.ip_address
                  AND qa_anchor.user_agent = {alias}.user_agent
                  AND qa_anchor.created_at BETWEEN
                      {alias}.created_at - INTERVAL '15 minutes'
                      AND {alias}.created_at + INTERVAL '15 minutes'
            )
        )
    )"""
    return qa_match if scope == "qa" else f"NOT {qa_match}"


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
def track_page_view(
    request: Request,
    swimtech_token: str = Cookie(default=None),
    swimmate_qa_run: str = Cookie(default=None),
):
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

        qa_automation = (
            swimmate_qa_run == "1"
            or request.headers.get(QA_AUTOMATION_HEADER, "").strip() == "1"
        )
        log_activity(
            customer_id=customer_id, username=username,
            event_type="page_view", page=page, menu_name=menu,
            method="GET", path=page,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
            metadata={"qa_automation": True} if qa_automation else None,
        )
        return {"status": "ok"}
    except Exception:
        return {"status": "error"}


@router.get("/dashboard")
def get_dashboard(days: int = 30, swimtech_token: str = Cookie(default=None)):
    _require_admin(swimtech_token)
    _ensure_table()
    days = min(90, max(7, _safe_int(days, 30)))
    conn = _get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT COUNT(*) FROM customers
        WHERE COALESCE(status,'active') <> 'deleted'
          AND COALESCE(is_qa_account, FALSE) = FALSE
    """)
    total_users = cur.fetchone()[0]

    cur.execute("""
        SELECT COUNT(*) FROM customers
        WHERE created_at >= CURRENT_DATE AND COALESCE(status,'active') <> 'deleted'
          AND COALESCE(is_qa_account, FALSE) = FALSE
    """)
    today_signups = cur.fetchone()[0]

    cur.execute("""
        SELECT COUNT(*) FROM customers
        WHERE created_at >= NOW() - INTERVAL '7 days' AND COALESCE(status,'active') <> 'deleted'
          AND COALESCE(is_qa_account, FALSE) = FALSE
    """)
    week_signups = cur.fetchone()[0]

    cur.execute("""
        SELECT COALESCE(social_provider, 'local') AS provider, COUNT(*)
        FROM customers
        WHERE COALESCE(status,'active') <> 'deleted'
          AND COALESCE(is_qa_account, FALSE) = FALSE
        GROUP BY provider
    """)
    by_provider = {row[0]: row[1] for row in cur.fetchall()}

    cur.execute("""
        SELECT id, name, username, COALESCE(social_provider,'local'),
               created_at AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Seoul' AS created_at
        FROM customers
        WHERE COALESCE(status,'active') <> 'deleted'
          AND COALESCE(is_qa_account, FALSE) = FALSE
        ORDER BY created_at DESC
        LIMIT 10
    """)
    recent = [
        {"id": r[0], "name": r[1], "username": r[2], "provider": r[3], "created_at": str(r[4])}
        for r in cur.fetchall()
    ]

    cur.execute(f"""
        WITH dates AS (
            SELECT generate_series(
                CURRENT_DATE - ((%s - 1) * INTERVAL '1 day'),
                CURRENT_DATE,
                INTERVAL '1 day'
            )::date AS day
        ), daily_activity AS (
            SELECT created_at::date AS day,
                   COUNT(*) FILTER (WHERE event_type = 'page_view') AS page_views,
                   COUNT(DISTINCT CASE WHEN event_type = 'page_view' THEN
                       CASE
                           WHEN customer_id IS NOT NULL THEN 'customer:' || customer_id::text
                           WHEN NULLIF(username, '') IS NOT NULL THEN 'username:' || username
                           WHEN NULLIF(ip_address, '') IS NOT NULL THEN 'ip:' || ip_address
                           ELSE 'anonymous:' || id::text
                       END
                   END) AS visitors,
                   COUNT(DISTINCT customer_id) FILTER (
                       WHERE event_type = 'page_view' AND customer_id IS NOT NULL
                   ) AS active_users
            FROM user_activity_logs l
            WHERE l.created_at >= CURRENT_DATE - ((%s - 1) * INTERVAL '1 day')
              AND {_log_scope_filter("regular", "l")}
            GROUP BY l.created_at::date
        ), daily_signups AS (
            SELECT created_at::date AS day, COUNT(*) AS signups
            FROM customers
            WHERE created_at >= CURRENT_DATE - ((%s - 1) * INTERVAL '1 day')
              AND COALESCE(status, 'active') <> 'deleted'
              AND COALESCE(is_qa_account, FALSE) = FALSE
            GROUP BY created_at::date
        )
        SELECT dates.day,
               COALESCE(daily_activity.page_views, 0),
               COALESCE(daily_activity.visitors, 0),
               COALESCE(daily_activity.active_users, 0),
               COALESCE(daily_signups.signups, 0)
        FROM dates
        LEFT JOIN daily_activity ON daily_activity.day = dates.day
        LEFT JOIN daily_signups ON daily_signups.day = dates.day
        ORDER BY dates.day
    """, (days, days, days))
    traffic_trend = [{
        "date": str(r[0]),
        "page_views": _safe_int(r[1]),
        "visitors": _safe_int(r[2]),
        "active_users": _safe_int(r[3]),
        "signups": _safe_int(r[4]),
    } for r in cur.fetchall()]

    cur.execute(f"""
        SELECT COUNT(*) FILTER (WHERE event_type = 'page_view'),
               COUNT(DISTINCT CASE WHEN event_type = 'page_view' THEN
                   CASE
                       WHEN customer_id IS NOT NULL THEN 'customer:' || customer_id::text
                       WHEN NULLIF(username, '') IS NOT NULL THEN 'username:' || username
                       WHEN NULLIF(ip_address, '') IS NOT NULL THEN 'ip:' || ip_address
                       ELSE 'anonymous:' || id::text
                   END
               END),
               COUNT(DISTINCT customer_id) FILTER (
                   WHERE event_type = 'page_view' AND customer_id IS NOT NULL
               )
        FROM user_activity_logs l
        WHERE l.created_at >= CURRENT_DATE - ((%s - 1) * INTERVAL '1 day')
          AND {_log_scope_filter("regular", "l")}
    """, (days,))
    traffic_row = cur.fetchone()
    traffic_summary = {
        "page_views": _safe_int(traffic_row[0]),
        "visitors": _safe_int(traffic_row[1]),
        "active_users": _safe_int(traffic_row[2]),
        "signups": sum(item["signups"] for item in traffic_trend),
    }

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
        "chart_days": days,
        "traffic_summary": traffic_summary,
        "traffic_trend": traffic_trend,
    }


@router.get("/users")
def list_users(
    swimtech_token: str = Cookie(default=None),
    q: str = None,
    search_by: str = "all",
    account_scope: str = "all",
    page: int = 1,
    page_size: int = 20,
):
    _require_admin(swimtech_token)
    conn = _get_db()
    cur = conn.cursor()
    page = max(1, _safe_int(page, 1))
    page_size = _normalize_page_size(page_size, 20)
    offset = max(0, (page - 1) * page_size)

    account_scope = _normalize_user_account_scope(account_scope)
    field_map = {
        "all": (
            "c.id::text", "COALESCE(c.name, '')", "COALESCE(c.email, '')", "COALESCE(c.username, '')",
            "COALESCE(c.nickname, '')", "COALESCE(c.social_provider, 'local')", "COALESCE(c.status, 'active')",
        ),
        "id": ("c.id::text",),
        "name": ("COALESCE(c.name, '')",),
        "email": ("COALESCE(c.email, '')",),
        "username": ("COALESCE(c.username, '')",),
        "nickname": ("COALESCE(c.nickname, '')",),
        "provider": ("COALESCE(c.social_provider, 'local')",),
        "status": ("COALESCE(c.status, 'active')",),
    }
    raw_q = _clean_search(q)
    localized_values = {
        "provider": {"일반": "local", "카카오": "kakao", "구글": "google"},
        "status": {"활성": "active", "탈퇴": "deleted"},
    }
    search_q = localized_values.get(search_by, {}).get(raw_q, raw_q)
    search_clause, search_params, search_by, _ = _build_search_filter(search_q, search_by, field_map)
    conditions = []
    if account_scope == "regular":
        conditions.append("COALESCE(c.is_qa_account, FALSE) = FALSE")
    elif account_scope == "qa":
        conditions.append("COALESCE(c.is_qa_account, FALSE) = TRUE")
    elif account_scope == "candidate":
        conditions.extend(["COALESCE(c.is_qa_account, FALSE) = FALSE", _qa_candidate_filter("c")])
    if search_clause:
        conditions.append(search_clause)
    where = _where_clause(conditions)
    cur.execute(f"""
        SELECT c.id, c.name, c.email, c.username, c.nickname,
               COALESCE(c.social_provider,'local'),
               c.created_at AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Seoul' AS created_at,
               c.last_login_at AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Seoul' AS last_login_at,
               COALESCE(c.status,'active'), COALESCE(c.is_qa_account, FALSE),
               COALESCE(activity.activity_count, 0), activity.last_activity_at,
               COALESCE(training.training_log_count, 0)
        FROM customers c
        LEFT JOIN LATERAL (
            SELECT COUNT(*) AS activity_count, MAX(al.created_at) AS last_activity_at
            FROM user_activity_logs al
            WHERE al.customer_id = c.id
               OR (
                   al.customer_id IS NULL
                   AND al.username IS NOT NULL
                   AND LOWER(al.username) = LOWER(c.username)
               )
        ) activity ON TRUE
        LEFT JOIN LATERAL (
            SELECT COUNT(*) AS training_log_count
            FROM training_logs tl
            WHERE tl.customer_id = c.id
        ) training ON TRUE
        {where}
        ORDER BY c.created_at DESC
        LIMIT %s OFFSET %s
    """, (*search_params, page_size, offset))

    users = []
    for row in cur.fetchall():
        user = {
            "id": row[0], "name": row[1], "email": row[2], "username": row[3], "nickname": row[4],
            "provider": row[5], "created_at": str(row[6]),
            "last_login_at": str(row[7]) if row[7] else None, "status": row[8],
            "is_qa_account": bool(row[9]), "activity_count": _safe_int(row[10]),
            "last_activity_at": str(row[11]) if row[11] else None,
            "training_log_count": _safe_int(row[12]),
        }
        user["qa_evidence"] = _qa_candidate_evidence(user)
        users.append(user)

    cur.execute(f"SELECT COUNT(*) FROM customers c {where}", tuple(search_params))
    total = cur.fetchone()[0]
    cur.close()
    conn.close()
    return {
        "users": users, "total": total, "page": page, "page_size": page_size,
        "q": raw_q, "search_by": search_by, "account_scope": account_scope,
    }


@router.get("/activity")
def get_activity(swimtech_token: str = Cookie(default=None)):
    """메뉴 사용 분석: 오늘 인기 메뉴, 최근 7일 메뉴별 클릭, 사용자별 자주 쓰는 메뉴."""
    _require_admin(swimtech_token)
    _ensure_table()
    conn = _get_db()
    cur = conn.cursor()

    cur.execute(f"""
        SELECT menu_name, COUNT(*) AS cnt
        FROM user_activity_logs l
        WHERE l.event_type = 'page_view' AND l.menu_name IS NOT NULL
              AND l.created_at >= CURRENT_DATE
              AND {_log_scope_filter("regular", "l")}
        GROUP BY menu_name ORDER BY cnt DESC LIMIT 10
    """)
    today_top_menus = [{"menu": r[0], "count": r[1]} for r in cur.fetchall()]

    cur.execute(f"""
        SELECT menu_name, COUNT(*) AS cnt
        FROM user_activity_logs l
        WHERE l.event_type = 'page_view' AND l.menu_name IS NOT NULL
              AND l.created_at >= NOW() - INTERVAL '7 days'
              AND {_log_scope_filter("regular", "l")}
        GROUP BY menu_name ORDER BY cnt DESC LIMIT 20
    """)
    week_menu_clicks = [{"menu": r[0], "count": r[1]} for r in cur.fetchall()]

    cur.execute(f"""
        SELECT event_type, COUNT(*) AS cnt
        FROM user_activity_logs l
        WHERE l.created_at >= NOW() - INTERVAL '7 days'
              AND l.event_type IN ('training_log_create','plan_share')
              AND {_log_scope_filter("regular", "l")}
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
    status: str = "all",
    q: str = None,
    search_by: str = "all",
    page: int = 1,
    page_size: int = 20,
):
    """코치 자격 검토 목록. 자격 번호는 관리자에게만 노출한다."""
    _require_admin(swimtech_token)
    page = max(1, _safe_int(page, 1))
    page_size = _normalize_page_size(page_size, 20)
    offset = (page - 1) * page_size
    status = status if status in ("unverified", "pending", "verified", "rejected", "all") else "all"
    q = _clean_search(q)
    search_by = search_by if search_by in ("all", "name", "username", "email", "specialty", "credential") else "all"
    conn = _get_db()
    cur = conn.cursor()
    try:
        if not _ensure_coach_verification(cur):
            conn.commit()
            return {"coaches": [], "total": 0, "page": page, "page_size": page_size, "status": status,
                    "q": q, "search_by": search_by,
                    "summary": {"registered": 0, "unverified": 0, "pending": 0, "verified": 0, "rejected": 0, "documents_30d": 0, "published_30d": 0}}
        cur.execute("""
            SELECT COUNT(*),
                   COUNT(*) FILTER (WHERE COALESCE(verification_status, 'unverified') = 'unverified'),
                   COUNT(*) FILTER (WHERE verification_status = 'pending'),
                   COUNT(*) FILTER (WHERE verification_status = 'verified'),
                   COUNT(*) FILTER (WHERE verification_status = 'rejected')
            FROM coaches
        """)
        counts = cur.fetchone()
        summary = {
            "registered": _safe_int(counts[0]), "unverified": _safe_int(counts[1]),
            "pending": _safe_int(counts[2]), "verified": _safe_int(counts[3]),
            "rejected": _safe_int(counts[4]), "documents_30d": 0, "published_30d": 0,
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
        conditions = []
        params = []
        if status != "all":
            conditions.append("COALESCE(co.verification_status, 'unverified') = %s")
            params.append(status)
        field_map = {
            "all": (
                "COALESCE(c.name, '')", "COALESCE(c.username, '')", "COALESCE(c.email, '')",
                "COALESCE(co.specialty, '')", "COALESCE(co.career, '')",
                "COALESCE(co.credential_type, '')", "COALESCE(co.credential_number, '')",
                "COALESCE(co.credential_organization, '')",
            ),
            "name": ("COALESCE(c.name, '')",),
            "username": ("COALESCE(c.username, '')",),
            "email": ("COALESCE(c.email, '')",),
            "specialty": ("COALESCE(co.specialty, '')", "COALESCE(co.career, '')"),
            "credential": (
                "COALESCE(co.credential_type, '')", "COALESCE(co.credential_number, '')",
                "COALESCE(co.credential_organization, '')",
            ),
        }
        search_clause, search_params, search_by, q = _build_search_filter(q, search_by, field_map)
        if search_clause:
            conditions.append(search_clause)
            params.extend(search_params)
        where = _where_clause(conditions)
        cur.execute(
            f"""
            SELECT co.id, c.name, c.username, c.email, co.specialty, co.career,
                   co.credential_type, co.credential_number, co.credential_organization,
                   COALESCE(co.verification_status, 'unverified'), co.verification_note,
                   co.created_at, co.verified_at, co.verified_by
            FROM coaches co JOIN customers c ON c.id = co.customer_id
            {where}
            ORDER BY CASE COALESCE(co.verification_status, 'unverified') WHEN 'pending' THEN 0 WHEN 'unverified' THEN 1 ELSE 2 END,
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
            f"SELECT COUNT(*) FROM coaches co JOIN customers c ON c.id = co.customer_id {where}",
            tuple(params),
        )
        total = _safe_int(cur.fetchone()[0])
        conn.commit()
        return {"coaches": coaches, "total": total, "page": page, "page_size": page_size,
                "status": status, "q": q, "search_by": search_by, "summary": summary}
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
               to_regclass('public.training_readiness'),
               to_regclass('public.swim_clubs'),
               to_regclass('public.swim_classes'),
               to_regclass('public.swim_class_sessions'),
               to_regclass('public.swim_class_attendance'),
               to_regclass('public.swim_class_notices'),
               to_regclass('public.swim_test_results'),
               to_regclass('public.wearable_workouts'),
               to_regclass('public.promotion_result_shares'),
               to_regclass('public.club_promotion_campaigns')
    """)
    (
        has_training_logs,
        has_training_goals,
        has_custom_plans,
        has_plan_completions,
        has_training_readiness,
        has_swim_clubs,
        has_swim_classes,
        has_class_sessions,
        has_class_attendance,
        has_class_notices,
        has_test_results,
        has_wearable_workouts,
        has_result_shares,
        has_club_campaigns,
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
        "active_clubs": 0,
        "active_classes": 0,
        "class_sessions_30d": 0,
        "attendance_rate_30d": 0,
        "active_notices": 0,
        "test_results_30d": 0,
        "test_users_30d": 0,
        "personal_bests_30d": 0,
        "screenshot_imports_30d": 0,
        "screenshot_import_users_30d": 0,
        "result_shares_30d": 0,
        "result_share_views_30d": 0,
        "public_club_campaigns": 0,
        "club_campaign_views": 0,
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

    if has_wearable_workouts:
        cur.execute("""
            SELECT COUNT(*), COUNT(DISTINCT customer_id)
            FROM wearable_workouts
            WHERE RIGHT(provider, 11) = '_screenshot'
              AND created_at >= NOW() - INTERVAL '30 days'
        """)
        row = cur.fetchone()
        summary["screenshot_imports_30d"] = _safe_int(row[0])
        summary["screenshot_import_users_30d"] = _safe_int(row[1])

    if has_result_shares:
        cur.execute("""
            SELECT COUNT(*), COALESCE(SUM(view_count), 0)
            FROM promotion_result_shares
            WHERE created_at >= NOW() - INTERVAL '30 days'
        """)
        row = cur.fetchone()
        summary["result_shares_30d"] = _safe_int(row[0])
        summary["result_share_views_30d"] = _safe_int(row[1])

    if has_club_campaigns:
        cur.execute("""
            SELECT COUNT(*) FILTER (WHERE is_public IS TRUE), COALESCE(SUM(view_count), 0)
            FROM club_promotion_campaigns
        """)
        row = cur.fetchone()
        summary["public_club_campaigns"] = _safe_int(row[0])
        summary["club_campaign_views"] = _safe_int(row[1])

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

    if has_swim_clubs:
        cur.execute("SELECT COUNT(*) FROM swim_clubs WHERE status = 'active'")
        summary["active_clubs"] = _safe_int(cur.fetchone()[0])

    if has_swim_classes:
        cur.execute("SELECT COUNT(*) FROM swim_classes WHERE status = 'active'")
        summary["active_classes"] = _safe_int(cur.fetchone()[0])

    if has_class_sessions:
        cur.execute("""
            SELECT COUNT(*) FROM swim_class_sessions
            WHERE session_date >= CURRENT_DATE - INTERVAL '30 days'
              AND session_date <= CURRENT_DATE
              AND status <> 'cancelled'
        """)
        summary["class_sessions_30d"] = _safe_int(cur.fetchone()[0])

    if has_class_attendance:
        cur.execute("""
            SELECT COUNT(*) FILTER (WHERE attendance.status IN ('present', 'late')),
                   COUNT(*)
            FROM swim_class_attendance attendance
            JOIN swim_class_sessions session ON session.id = attendance.session_id
            WHERE session.session_date >= CURRENT_DATE - INTERVAL '30 days'
              AND session.session_date <= CURRENT_DATE
              AND session.status <> 'cancelled'
        """)
        row = cur.fetchone()
        checked = _safe_int(row[1])
        summary["attendance_rate_30d"] = round(_safe_int(row[0]) / checked * 100) if checked else 0

    if has_class_notices:
        cur.execute("SELECT COUNT(*) FROM swim_class_notices WHERE status = 'active'")
        summary["active_notices"] = _safe_int(cur.fetchone()[0])

    if has_test_results:
        cur.execute(
            """
            WITH history AS (
                SELECT customer_id, test_date, duration_ms,
                       MIN(duration_ms) OVER (
                           PARTITION BY customer_id, stroke_type, distance_m, pool_length
                           ORDER BY test_date, id ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
                       ) AS previous_best_ms
                FROM swim_test_results
            )
            SELECT COUNT(*), COUNT(DISTINCT customer_id),
                   COUNT(*) FILTER (WHERE previous_best_ms IS NULL OR duration_ms < previous_best_ms)
            FROM history
            WHERE test_date >= CURRENT_DATE - INTERVAL '30 days'
            """
        )
        row = cur.fetchone()
        summary["test_results_30d"] = _safe_int(row[0])
        summary["test_users_30d"] = _safe_int(row[1])
        summary["personal_bests_30d"] = _safe_int(row[2])

    cur.close()
    conn.close()
    return {
        "table_status": {
            "training_logs": has_training_logs,
            "training_goals": has_training_goals,
            "custom_plans": has_custom_plans,
            "plan_completions": has_plan_completions,
            "training_readiness": has_training_readiness,
            "swim_clubs": has_swim_clubs,
            "swim_classes": has_swim_classes,
            "swim_class_sessions": has_class_sessions,
            "swim_class_attendance": has_class_attendance,
            "swim_class_notices": has_class_notices,
            "swim_test_results": has_test_results,
            "promotion_result_shares": has_result_shares,
            "club_promotion_campaigns": has_club_campaigns,
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
            {
                "label": "클럽·반 운영",
                "status": "운영 확인",
                "detail": (
                    f"활성 클럽 {summary['active_clubs']}개 · 반 {summary['active_classes']}개 · "
                    f"30일 일정 {summary['class_sessions_30d']}회 · 출석률 {summary['attendance_rate_30d']}% · "
                    f"활성 공지 {summary['active_notices']}건"
                ),
            },
            {
                "label": "테스트 세트·개인 최고기록",
                "status": "운영 확인",
                "detail": (
                    f"최근 30일 시도 {summary['test_results_30d']}건 · "
                    f"사용자 {summary['test_users_30d']}명 · 새 PB {summary['personal_bests_30d']}건"
                ),
            },
        ],
    }


@router.get("/logs")
def get_logs(
    swimtech_token: str = Cookie(default=None),
    event_type: str = None,
    account_scope: str = "regular",
    q: str = None,
    search_by: str = "all",
    page: int = 1,
    page_size: int = 50,
):
    """운영 로그: 로그인 성공/실패, 가입, 소셜로그인, 일지작성, 플랜공유, 오류 등."""
    _require_admin(swimtech_token)
    _ensure_table()
    conn = _get_db()
    cur = conn.cursor()
    page = max(1, _safe_int(page, 1))
    page_size = _normalize_page_size(page_size, 50)
    offset = max(0, (page - 1) * page_size)

    account_scope = _normalize_account_scope(account_scope)
    conditions = []
    params = []
    scope_filter = _log_scope_filter(account_scope)
    if scope_filter:
        conditions.append(scope_filter)
    if event_type:
        conditions.append("l.event_type = %s")
        params.append(event_type)
    field_map = {
        "all": (
            "COALESCE(l.username, '')", "COALESCE(l.page, '')", "COALESCE(l.path, '')",
            "COALESCE(l.action, '')", "COALESCE(l.method, '')", "COALESCE(l.ip_address, '')",
        ),
        "username": ("COALESCE(l.username, '')",),
        "path": ("COALESCE(l.page, '')", "COALESCE(l.path, '')"),
        "action": ("COALESCE(l.action, '')",),
        "method": ("COALESCE(l.method, '')",),
        "ip": ("COALESCE(l.ip_address, '')",),
    }
    search_clause, search_params, search_by, q = _build_search_filter(q, search_by, field_map)
    if search_clause:
        conditions.append(search_clause)
        params.extend(search_params)
    where = _where_clause(conditions)
    cur.execute(f"""
        SELECT l.id, l.username, l.event_type, l.page, l.action, l.method, l.path,
               l.ip_address, l.created_at, l.metadata,
               {_log_scope_filter("qa")} AS is_qa_account
        FROM user_activity_logs l
        {where}
        ORDER BY l.created_at DESC LIMIT %s OFFSET %s
    """, (*params, page_size, offset))

    logs = [{
        "id": r[0], "username": r[1], "event_type": r[2], "page": r[3],
        "action": r[4], "method": r[5], "path": r[6], "ip_address": r[7],
        "created_at": str(r[8]), "metadata": r[9], "is_qa_account": bool(r[10]),
    } for r in cur.fetchall()]

    cur.execute(f"SELECT COUNT(*) FROM user_activity_logs l {where}", tuple(params))
    total = cur.fetchone()[0]

    summary_scope_filter = _log_scope_filter(account_scope)
    summary_where = _where_clause([summary_scope_filter] if summary_scope_filter else [])
    cur.execute(f"""
        SELECT COUNT(*) FILTER (WHERE l.created_at >= NOW() - INTERVAL '30 days'),
               COUNT(*) FILTER (
                   WHERE l.created_at >= NOW() - INTERVAL '30 days'
                     AND l.event_type = 'page_view'
               ),
               COUNT(DISTINCT COALESCE(l.customer_id::text, 'username:' || LOWER(l.username)))
                   FILTER (WHERE l.created_at >= NOW() - INTERVAL '30 days'),
               MAX(l.created_at)
        FROM user_activity_logs l
        {summary_where}
    """)
    summary_row = cur.fetchone()
    cur.execute("""
        SELECT username FROM customers
        WHERE COALESCE(is_qa_account, FALSE) = TRUE
        ORDER BY username
    """)
    qa_account_usernames = [r[0] for r in cur.fetchall()]

    cur.close()
    conn.close()
    return {
        "logs": logs, "total": total, "page": page, "page_size": page_size,
        "event_type": event_type or "", "account_scope": account_scope,
        "q": q, "search_by": search_by,
        "scope_summary": {
            "events_30d": _safe_int(summary_row[0]),
            "page_views_30d": _safe_int(summary_row[1]),
            "active_accounts_30d": _safe_int(summary_row[2]),
            "last_activity_at": str(summary_row[3]) if summary_row[3] else None,
            "qa_account_count": len(qa_account_usernames),
            "qa_account_usernames": qa_account_usernames,
        },
    }


@router.put("/qa-accounts")
def set_qa_accounts(
    body: QAAccountFlagBody,
    swimtech_token: str = Cookie(default=None),
):
    """Mark permanent automation accounts so their historic and future logs separate."""
    reviewer = _require_admin(swimtech_token)
    usernames = list(dict.fromkeys(
        str(username or "").strip()[:100]
        for username in body.usernames
        if str(username or "").strip()
    ))
    if not usernames:
        raise HTTPException(400, "QA 계정 아이디를 입력해주세요.")

    conn = _get_db()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            UPDATE customers
            SET is_qa_account = %s
            WHERE username = ANY(%s)
            RETURNING id, username
            """,
            (body.is_qa_account, usernames),
        )
        updated = [{"id": row[0], "username": row[1]} for row in cur.fetchall()]
        updated_names = {item["username"] for item in updated}
        missing = [username for username in usernames if username not in updated_names]
        conn.commit()
    finally:
        cur.close()
        conn.close()

    log_activity(
        username=reviewer,
        event_type="admin_qa_account_update",
        action="qa_account_flag_update",
        method="PUT",
        path="/api/admin/qa-accounts",
        metadata={
            "updated_count": len(updated),
            "missing_count": len(missing),
            "is_qa_account": body.is_qa_account,
        },
    )
    return {
        "updated": updated,
        "missing": missing,
        "is_qa_account": body.is_qa_account,
    }
