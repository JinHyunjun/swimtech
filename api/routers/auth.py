"""
SwimMate — 인증 모듈
JWT 기반 로컬 로그인 + Google / Kakao 소셜 로그인
"""
import logging
import os
import re
from datetime import date, datetime, timedelta
from urllib.parse import urlencode

import httpx
import redis as _redis_module
from email_validator import validate_email, EmailNotValidError
from fastapi import APIRouter, HTTPException, Request, Response, Cookie
from fastapi.responses import JSONResponse, RedirectResponse
from jose import jwt
from pydantic import BaseModel
import psycopg2
import bcrypt
from activity_log import log_activity

from rate_limit import limiter

router = APIRouter()
logger = logging.getLogger(__name__)

SECRET_KEY                = os.getenv("SECRET_KEY", "swimtech-secret-key")
ALGORITHM                 = "HS256"
TOKEN_EXPIRE_HOURS        = 8
REFRESH_TOKEN_EXPIRE_DAYS = 7

LOGIN_FAIL_MAX    = 5
LOGIN_FAIL_EXPIRE = 900  # 15분 (초)

ADMIN_ID = os.getenv("ADMIN_ID", "admin")
ADMIN_PW = os.getenv("ADMIN_PW", "swimtech1234")
DEMO_USERNAME = os.getenv("DEMO_USERNAME", "portfolio_demo")
DEMO_EMAIL = os.getenv("DEMO_EMAIL", "portfolio-demo@swimmate.local")
DEMO_NAME = os.getenv("DEMO_NAME", "비회원 체험 사용자")
DEMO_NICKNAME = os.getenv("DEMO_NICKNAME", "체험 사용자")

DATABASE_URL = os.getenv("DATABASE_URL", "")
REDIS_URL    = os.getenv("REDIS_URL", "redis://redis:6379/0")

GOOGLE_OAUTH_FILE   = "/app/credentials/google_oauth_client.json"

KAKAO_CLIENT_ID     = os.getenv("KAKAO_CLIENT_ID", "")
KAKAO_CLIENT_SECRET = os.getenv("KAKAO_CLIENT_SECRET", "")

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
GOOGLE_AUTH_URI = os.getenv("GOOGLE_AUTH_URI", "https://accounts.google.com/o/oauth2/v2/auth")
GOOGLE_TOKEN_URI = os.getenv("GOOGLE_TOKEN_URI", "https://oauth2.googleapis.com/token")

# BASE_URL: Cloudflare Tunnel 등 외부 도메인 사용 시 환경변수로 주입
# 예) BASE_URL=https://wilderness-xxx.trycloudflare.com
_BASE_URL = os.getenv("BASE_URL", "https://localhost").rstrip("/")
GOOGLE_REDIRECT_URI = f"{_BASE_URL}/auth/google/callback"
KAKAO_REDIRECT_URI  = f"{_BASE_URL}/auth/kakao/callback"

_USERNAME_RE = re.compile(r'^[a-zA-Z0-9]{4,20}$')
_PASSWORD_RE = re.compile(r'^(?=.*[A-Za-z])(?=.*\d).{8,}$')
_HTML_TAG_RE = re.compile(r'<[^>]+>')
_NICKNAME_RE = re.compile(r'^[가-힣a-zA-Z0-9]{2,20}$')


# ── DB / Redis helpers ────────────────────────────────────────────────────────

def get_db():
    return psycopg2.connect(DATABASE_URL)


def _get_redis():
    try:
        return _redis_module.from_url(
            REDIS_URL, decode_responses=True, socket_connect_timeout=1
        )
    except Exception:
        return None


def _get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _strip_tags(text: str) -> str:
    return _HTML_TAG_RE.sub("", text) if text else ""


# ── 로그인 실패 추적 ──────────────────────────────────────────────────────────

def _check_login_blocked(ip: str):
    r = _get_redis()
    if not r:
        return
    try:
        count = r.get(f"login_fail:{ip}")
        if count and int(count) >= LOGIN_FAIL_MAX:
            raise HTTPException(429, "너무 많은 로그인 시도. 15분 후 다시 시도하세요.")
    except HTTPException:
        raise
    except Exception:
        pass


def _increment_login_fail(ip: str):
    r = _get_redis()
    if not r:
        return
    try:
        key = f"login_fail:{ip}"
        pipe = r.pipeline()
        pipe.incr(key)
        pipe.expire(key, LOGIN_FAIL_EXPIRE)
        pipe.execute()
    except Exception:
        pass


def _clear_login_fail(ip: str):
    r = _get_redis()
    if not r:
        return
    try:
        r.delete(f"login_fail:{ip}")
    except Exception:
        pass


# ── 소셜 컬럼 마이그레이션 ────────────────────────────────────────────────────

def _ensure_social_columns():
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("ALTER TABLE customers ADD COLUMN IF NOT EXISTS social_provider TEXT")
        cur.execute("ALTER TABLE customers ADD COLUMN IF NOT EXISTS social_id TEXT")
        cur.execute("ALTER TABLE customers ADD COLUMN IF NOT EXISTS nickname TEXT")
        conn.commit()
        cur.close()
        conn.close()
    except Exception:
        pass


_ensure_social_columns()


# ── Pydantic 모델 ─────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str
    password: str


class RegisterRequest(BaseModel):
    name: str
    email: str
    username: str
    password: str


class NicknameRequest(BaseModel):
    nickname: str


# ── 토큰 유틸 ─────────────────────────────────────────────────────────────────

def create_token(username: str, customer_id: int | None = None, is_demo: bool = False) -> str:
    expire = datetime.utcnow() + timedelta(hours=TOKEN_EXPIRE_HOURS)
    payload = {"sub": username, "exp": expire}
    if customer_id is not None:
        payload["customer_id"] = customer_id
    if is_demo:
        payload["is_demo"] = True
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def create_refresh_token(username: str, customer_id: int | None = None, is_demo: bool = False) -> str:
    expire = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    payload = {"sub": username, "exp": expire, "type": "refresh"}
    if customer_id is not None:
        payload["customer_id"] = customer_id
    if is_demo:
        payload["is_demo"] = True
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def verify_token(token: str) -> str:
    """토큰 검증 → 유저명 반환, 실패 시 None"""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload.get("sub")
    except Exception:
        return None


def decode_token(token: str) -> dict:
    """토큰 디코딩 → payload dict 반환, 실패 시 {}"""
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except Exception:
        return {}


def _set_auth_cookie(response: Response, token: str):
    response.set_cookie(
        key="swimtech_token",
        value=token,
        httponly=True,
        secure=True,
        max_age=60 * 60 * TOKEN_EXPIRE_HOURS,
        samesite="lax",
    )


def _set_refresh_cookie(response: Response, token: str):
    response.set_cookie(
        key="swimtech_refresh_token",
        value=token,
        httponly=True,
        secure=True,
        max_age=60 * 60 * 24 * REFRESH_TOKEN_EXPIRE_DAYS,
        samesite="lax",
    )


# ── 소셜 사용자 조회/생성 ─────────────────────────────────────────────────────

def _find_or_create_social_user(
    provider: str,
    social_id: str,
    email: str,
    name: str,
) -> tuple[int, str, bool]:
    """기존 사용자 → (id, username, False), 신규 가입 → (id, username, True)"""
    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "SELECT id, username FROM customers WHERE social_provider = %s AND social_id = %s",
        (provider, social_id),
    )
    row = cur.fetchone()
    if row:
        cur.close(); conn.close()
        return row[0], row[1], False

    if email:
        cur.execute("SELECT id, username FROM customers WHERE email = %s", (email,))
        row = cur.fetchone()
        if row:
            cur.execute(
                "UPDATE customers SET social_provider = %s, social_id = %s WHERE id = %s",
                (provider, social_id, row[0]),
            )
            conn.commit()
            cur.close(); conn.close()
            return row[0], row[1], False

    base_username = (email.split("@")[0] if email else f"{provider}_{social_id}")
    username = base_username
    suffix = 1
    while True:
        cur.execute("SELECT id FROM customers WHERE username = %s", (username,))
        if not cur.fetchone():
            break
        username = f"{base_username}{suffix}"
        suffix += 1

    effective_email = email if email else f"{provider}_{social_id}@noemail.local"
    cur.execute(
        """INSERT INTO customers (name, email, username, social_provider, social_id)
           VALUES (%s, %s, %s, %s, %s) RETURNING id""",
        (name, effective_email, username, provider, social_id),
    )
    customer_id = cur.fetchone()[0]
    conn.commit()
    cur.close(); conn.close()
    return customer_id, username, True


# ── 로컬 인증 ─────────────────────────────────────────────────────────────────

def _ensure_demo_user_and_seed() -> int:
    if not DATABASE_URL:
        raise HTTPException(503, "체험 모드는 데이터베이스 연결이 필요합니다.")

    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("ALTER TABLE customers ADD COLUMN IF NOT EXISTS social_provider TEXT")
        cur.execute("ALTER TABLE customers ADD COLUMN IF NOT EXISTS social_id TEXT")
        cur.execute("ALTER TABLE customers ADD COLUMN IF NOT EXISTS nickname TEXT")
        cur.execute("ALTER TABLE customers ADD COLUMN IF NOT EXISTS role TEXT")
        cur.execute("ALTER TABLE customers ADD COLUMN IF NOT EXISTS status TEXT")
        cur.execute("ALTER TABLE customers ADD COLUMN IF NOT EXISTS weekly_goal INTEGER NOT NULL DEFAULT 3")
        cur.execute("ALTER TABLE training_logs ADD COLUMN IF NOT EXISTS used_fins BOOLEAN NOT NULL DEFAULT FALSE")
        cur.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name='training_goals' AND column_name='username'
        """)
        if cur.fetchone():
            cur.execute("DROP TABLE IF EXISTS training_goals")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS training_goals (
                id            SERIAL PRIMARY KEY,
                customer_id   INTEGER NOT NULL,
                year          INTEGER NOT NULL,
                month         INTEGER NOT NULL,
                goal_distance INTEGER NOT NULL DEFAULT 0,
                created_at    TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE (customer_id, year, month)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS plan_completions (
                id           SERIAL PRIMARY KEY,
                customer_id  INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
                plan_key     VARCHAR(50) NOT NULL,
                week_index   INTEGER NOT NULL,
                day_label    VARCHAR(20) NOT NULL,
                training_log_id INTEGER REFERENCES training_logs(id) ON DELETE SET NULL,
                completed_at TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE (customer_id, plan_key, week_index, day_label)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS user_badges (
                id        SERIAL PRIMARY KEY,
                username  VARCHAR(100) NOT NULL,
                badge_id  VARCHAR(100) NOT NULL,
                earned_at TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE (username, badge_id)
            )
        """)
        cur.execute("SELECT pg_advisory_xact_lock(81420260628)")
        cur.execute("""
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
        """)

        disabled_hash = bcrypt.hashpw(os.urandom(24), bcrypt.gensalt()).decode("utf-8")
        cur.execute(
            """
            INSERT INTO customers
                (name, email, username, password_hash, social_provider, social_id, nickname, weekly_goal, role, status)
            VALUES (%s, %s, %s, %s, 'demo', 'portfolio', %s, 3, NULL, 'active')
            ON CONFLICT (username) DO UPDATE SET
                name = EXCLUDED.name,
                password_hash = EXCLUDED.password_hash,
                social_provider = 'demo',
                social_id = 'portfolio',
                nickname = EXCLUDED.nickname,
                weekly_goal = 3,
                role = NULL,
                status = 'active'
            RETURNING id
            """,
            (DEMO_NAME, DEMO_EMAIL, DEMO_USERNAME, disabled_hash, DEMO_NICKNAME),
        )
        customer_id = cur.fetchone()[0]

        cur.execute("DELETE FROM plan_completions WHERE customer_id = %s", (customer_id,))
        cur.execute("DELETE FROM training_goals WHERE customer_id = %s", (customer_id,))
        cur.execute("DELETE FROM training_logs WHERE customer_id = %s", (customer_id,))
        cur.execute("DELETE FROM training_readiness WHERE customer_id = %s", (customer_id,))
        cur.execute("DELETE FROM user_badges WHERE username = %s", (DEMO_USERNAME,))

        today = date.today()
        sample_logs = [
            (today, "자유형", 1700, 42, 25, "보통", "좋음", "체험 데이터: 자유형 지구력 + 킥 정리", False),
            (today - timedelta(days=2), "배영", 1400, 36, 25, "쉬움", "좋음", "체험 데이터: 배영 롤링 감각", False),
            (today - timedelta(days=4), "자유형", 2200, 55, 50, "힘듦", "최고", "체험 데이터: 50m 풀 페이스 훈련", True),
            (today - timedelta(days=7), "평영", 1200, 34, 25, "보통", "보통", "체험 데이터: 호흡 타이밍 교정", False),
            (today - timedelta(days=10), "접영", 900, 28, 25, "힘듦", "좋음", "체험 데이터: 짧은 대시와 회복", False),
            (today - timedelta(days=13), "자유형", 1600, 40, 50, "보통", "좋음", "체험 데이터: 25m/50m 차이 비교", False),
        ]
        log_ids = []
        for row in sample_logs:
            cur.execute(
                """
                INSERT INTO training_logs
                    (customer_id, log_date, stroke_type, total_distance, duration_minutes,
                     pool_length, intensity, mood, memo, used_fins)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (customer_id, *row),
            )
            log_ids.append(cur.fetchone()[0])

        cur.execute(
            """
            INSERT INTO training_goals (customer_id, year, month, goal_distance)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (customer_id, year, month)
            DO UPDATE SET goal_distance = EXCLUDED.goal_distance, created_at = NOW()
            """,
            (customer_id, today.year, today.month, 12000),
        )

        for idx, log_id in enumerate(log_ids[:2]):
            cur.execute(
                """
                INSERT INTO plan_completions
                    (customer_id, plan_key, week_index, day_label, training_log_id)
                VALUES (%s, 'demo_foundation_4w', 0, %s, %s)
                ON CONFLICT (customer_id, plan_key, week_index, day_label)
                DO UPDATE SET training_log_id = EXCLUDED.training_log_id,
                              completed_at = NOW()
                """,
                (customer_id, f"Day {idx + 1}", log_id),
            )

        cur.execute(
            """
            INSERT INTO training_readiness
                (customer_id, check_date, sleep_quality, fatigue, muscle_soreness,
                 available_minutes, note, readiness_score)
            VALUES (%s, %s, 4, 2, 2, 60, %s, 75)
            ON CONFLICT (customer_id, check_date) DO UPDATE SET
                sleep_quality = EXCLUDED.sleep_quality,
                fatigue = EXCLUDED.fatigue,
                muscle_soreness = EXCLUDED.muscle_soreness,
                available_minutes = EXCLUDED.available_minutes,
                note = EXCLUDED.note,
                readiness_score = EXCLUDED.readiness_score,
                updated_at = NOW()
            """,
            (customer_id, today, "체험 데이터: 컨디션이 좋아 핵심 세트 수행 가능"),
        )

        conn.commit()
        return int(customer_id)
    except Exception:
        conn.rollback()
        logger.exception("demo login seed failed")
        raise HTTPException(500, "체험 모드 준비 중 오류가 발생했습니다.")
    finally:
        cur.close()
        conn.close()


@router.post("/register")
def register(body: RegisterRequest):
    name = _strip_tags((body.name or "").strip())
    email = (body.email or "").strip()
    username = (body.username or "").strip()
    password = body.password or ""

    if not name:
        raise HTTPException(400, '\uc774\ub984\uc744 \uc785\ub825\ud574\uc8fc\uc138\uc694.')

    if len(name) > 50:
        raise HTTPException(400, '\uc774\ub984\uc740 \ucd5c\ub300 50\uc790\uae4c\uc9c0 \ud5c8\uc6a9\ub429\ub2c8\ub2e4.')

    try:
        validate_email(email, check_deliverability=False)
    except EmailNotValidError:
        raise HTTPException(400, '\uc720\ud6a8\ud558\uc9c0 \uc54a\uc740 \uc774\uba54\uc77c \ud615\uc2dd\uc785\ub2c8\ub2e4.')

    if not _USERNAME_RE.match(username):
        raise HTTPException(400, '\uc544\uc774\ub514\ub294 \uc601\ubb38/\uc22b\uc790 4~20\uc790\uc5ec\uc57c \ud569\ub2c8\ub2e4.')

    if not _PASSWORD_RE.match(password):
        raise HTTPException(400, '\ube44\ubc00\ubc88\ud638\ub294 \ucd5c\uc18c 8\uc790 \uc774\uc0c1, \uc601\ubb38\uacfc \uc22b\uc790\ub97c \ud3ec\ud568\ud574\uc57c \ud569\ub2c8\ub2e4.')

    conn = None
    cur = None

    try:
        conn = get_db()
        cur = conn.cursor()

        cur.execute("SELECT id FROM customers WHERE username = %s", (username,))
        if cur.fetchone():
            raise HTTPException(400, '\uc774\ubbf8 \uc0ac\uc6a9 \uc911\uc778 \uc544\uc774\ub514\uc785\ub2c8\ub2e4.')

        cur.execute("SELECT id FROM customers WHERE email = %s", (email,))
        if cur.fetchone():
            raise HTTPException(400, '\uc774\ubbf8 \uc0ac\uc6a9 \uc911\uc778 \uc774\uba54\uc77c\uc785\ub2c8\ub2e4.')

        password_bytes = password.encode("utf-8")[:72]
        password_hash = bcrypt.hashpw(password_bytes, bcrypt.gensalt()).decode("utf-8")

        cur.execute(
            "INSERT INTO customers (name, email, username, password_hash, social_provider)"
            " VALUES (%s, %s, %s, %s, 'local')",
            (name, email, username, password_hash),
        )

        conn.commit()
        log_activity(username=body.username, event_type="register",
                     action="register_success", metadata={"provider": "local"})
        return {"status": "ok"}

    except HTTPException:
        raise

    except Exception:
        logger.error("register: DB error", exc_info=True)
        raise HTTPException(500, '\ub0b4\ubd80 \uc624\ub958\uac00 \ubc1c\uc0dd\ud588\uc2b5\ub2c8\ub2e4.')

    finally:
        if cur is not None:
            try:
                cur.close()
            except Exception:
                pass

        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

@router.post("/login")
@limiter.limit("30/minute")
def login(request: Request, body: LoginRequest, response: Response):
    ip = _get_client_ip(request)
    _check_login_blocked(ip)

    customer_id = None

    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "SELECT id, password_hash FROM customers WHERE username = %s",
            (body.username,),
        )
        row = cur.fetchone()
        cur.close()
        conn.close()
    except Exception:
        logger.error("login: DB error", exc_info=True)
        raise HTTPException(500, "내부 오류가 발생했습니다.")

    if row:
        db_id, password_hash = row
        pw_bytes = body.password.encode("utf-8")[:72]
        if not bcrypt.checkpw(pw_bytes, password_hash.encode("utf-8")):
            _increment_login_fail(ip)
            log_activity(username=body.username, event_type="login_fail",
                         action="login", ip_address=ip)
            raise HTTPException(401, "아이디 또는 비밀번호가 올바르지 않습니다.")
        customer_id = db_id
    else:
        if body.username != ADMIN_ID or body.password != ADMIN_PW:
            _increment_login_fail(ip)
            raise HTTPException(401, "아이디 또는 비밀번호가 올바르지 않습니다.")

    _clear_login_fail(ip)
    log_activity(customer_id=customer_id, username=body.username,
                 event_type="login_success", action="login",
                 ip_address=ip)
    token   = create_token(body.username, customer_id)
    refresh = create_refresh_token(body.username, customer_id)
    _set_auth_cookie(response, token)
    _set_refresh_cookie(response, refresh)

    is_admin = (body.username == ADMIN_ID)
    if not is_admin and customer_id:
        try:
            conn2 = get_db()
            cur2 = conn2.cursor()
            cur2.execute("SELECT role FROM customers WHERE id = %s", (customer_id,))
            row2 = cur2.fetchone()
            cur2.close(); conn2.close()
            if row2 and row2[0] == "admin":
                is_admin = True
        except Exception:
            pass

    return {"status": "ok", "message": f"{body.username}님 환영합니다!", "is_admin": is_admin}


@router.post("/demo")
@limiter.limit("20/minute")
def demo_login(request: Request, response: Response):
    customer_id = _ensure_demo_user_and_seed()
    token = create_token(DEMO_USERNAME, customer_id, is_demo=True)
    refresh = create_refresh_token(DEMO_USERNAME, customer_id, is_demo=True)
    _set_auth_cookie(response, token)
    _set_refresh_cookie(response, refresh)
    log_activity(
        customer_id=customer_id,
        username=DEMO_USERNAME,
        event_type="login_success",
        action="demo_login",
        ip_address=_get_client_ip(request),
        metadata={"mode": "portfolio_demo"},
    )
    return {
        "status": "ok",
        "message": "체험 모드로 시작합니다.",
        "is_admin": False,
        "is_demo": True,
        "redirect": "/dashboard",
    }


@router.post("/refresh")
def refresh_token_endpoint(
    response: Response,
    swimtech_refresh_token: str = Cookie(default=None),
):
    if not swimtech_refresh_token:
        raise HTTPException(401, "리프레시 토큰이 없습니다.")
    try:
        payload = jwt.decode(swimtech_refresh_token, SECRET_KEY, algorithms=[ALGORITHM])
    except Exception:
        raise HTTPException(401, "리프레시 토큰이 만료되었습니다.")
    if payload.get("type") != "refresh":
        raise HTTPException(401, "?좏슚?섏? ?딆? ?좏겙 ??낆엯?덈떎.")
    username    = payload.get("sub")
    customer_id = payload.get("customer_id")
    is_demo = bool(payload.get("is_demo"))
    token = create_token(username, customer_id, is_demo=is_demo)
    new_refresh = create_refresh_token(username, customer_id, is_demo=is_demo)
    _set_auth_cookie(response, token)
    _set_refresh_cookie(response, new_refresh)
    return {"status": "ok", "message": "토큰이 갱신되었습니다."}


@router.post("/logout")
def logout(response: Response, swimtech_token: str = Cookie(default=None)):
    if swimtech_token:
        try:
            payload = decode_token(swimtech_token)
            log_activity(customer_id=payload.get("customer_id"), username=payload.get("sub"),
                         event_type="logout", action="logout")
        except Exception:
            pass
    response.delete_cookie("swimtech_token")
    response.delete_cookie("swimtech_refresh_token")
    return {"status": "ok", "message": "로그아웃 완료"}



@router.delete("/me")
def delete_me(response: Response, swimtech_token: str = Cookie(default=None)):
    if not swimtech_token:
        raise HTTPException(401, "로그인이 필요합니다.")

    payload = decode_token(swimtech_token)
    username = payload.get("sub")
    customer_id = payload.get("customer_id")
    if payload.get("is_demo"):
        raise HTTPException(400, "체험 모드 계정은 탈퇴할 수 없습니다.")

    if not username:
        raise HTTPException(401, "세션이 만료되었습니다. 다시 로그인해주세요.")

    if username == ADMIN_ID:
        raise HTTPException(400, "관리자 계정은 회원 탈퇴할 수 없습니다.")

    conn = None
    cur = None

    try:
        conn = get_db()
        cur = conn.cursor()

        cur.execute("ALTER TABLE customers ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ")

        # 소셜 로그인은 토큰에 customer_id가 있고, 일반(local) 로그인은 없음.
        # local 계정도 username으로 자기 customers row를 찾아 동일하게 처리.
        if not customer_id:
            cur.execute(
                "SELECT id FROM customers WHERE username = %s AND COALESCE(status, 'active') <> 'deleted'",
                (username,),
            )
            row0 = cur.fetchone()
            if not row0:
                raise HTTPException(404, "이미 탈퇴했거나 존재하지 않는 계정입니다.")
            customer_id = row0[0]
        else:
            cur.execute(
                "SELECT id FROM customers WHERE id = %s AND COALESCE(status, 'active') <> 'deleted'",
                (customer_id,),
            )
            if not cur.fetchone():
                raise HTTPException(404, "이미 탈퇴했거나 존재하지 않는 계정입니다.")

        cur.execute(
            """
            UPDATE customers
               SET status = 'deleted',
                   deleted_at = NOW(),
                   last_login_at = NULL,
                   name = 'withdrawn_user',
                   email = 'deleted_' || id || '_' || EXTRACT(EPOCH FROM NOW())::bigint || '@deleted.local',
                   username = 'deleted_' || id || '_' || EXTRACT(EPOCH FROM NOW())::bigint,
                   nickname = NULL,
                   password_hash = NULL,
                   social_provider = NULL,
                   social_id = NULL
             WHERE id = %s
            """,
            (customer_id,),
        )

        conn.commit()

        response.delete_cookie("swimtech_token")
        response.delete_cookie("swimtech_refresh_token")

        return {"status": "ok", "message": "회원 탈퇴가 완료되었습니다."}

    except HTTPException:
        if conn is not None:
            conn.rollback()
        raise

    except Exception:
        if conn is not None:
            conn.rollback()
        logger.error("delete_me: DB error", exc_info=True)
        raise HTTPException(500, "회원 탈퇴 처리 중 오류가 발생했습니다.")

    finally:
        if cur is not None:
            try:
                cur.close()
            except Exception:
                pass

        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


@router.get("/me")
def me(swimtech_token: str = Cookie(default=None)):
    if not swimtech_token:
        raise HTTPException(401, "로그인이 필요합니다.")
    payload = decode_token(swimtech_token)
    username = payload.get("sub")
    is_demo = bool(payload.get("is_demo"))
    if not username:
        raise HTTPException(401, "세션이 만료되었습니다. 다시 로그인해주세요.")

    customer_id     = payload.get("customer_id")
    nickname        = None
    social_provider = None

    try:
        conn = get_db()
        cur = conn.cursor()
        if customer_id:
            cur.execute(
                "SELECT nickname, social_provider FROM customers WHERE id = %s",
                (customer_id,),
            )
        else:
            # local 로그인은 토큰에 customer_id가 없으므로 username으로 조회
            cur.execute(
                "SELECT nickname, social_provider FROM customers WHERE username = %s",
                (username,),
            )
        row = cur.fetchone()
        cur.close(); conn.close()
        if row:
            nickname, social_provider = row
    except Exception:
        logger.warning("me: DB lookup failed", exc_info=True)

    return {
        "username":        username,
        "customer_id":     customer_id,
        "status":          "authenticated",
        "nickname":        nickname,
        "social_provider": social_provider,
        "needs_nickname":  False if is_demo else nickname is None,
        "is_demo":         is_demo,
    }


@router.post("/nickname")
def set_nickname(body: NicknameRequest, swimtech_token: str = Cookie(default=None)):
    if not swimtech_token:
        raise HTTPException(401, "로그인이 필요합니다.")
    payload = decode_token(swimtech_token)
    if payload.get("is_demo"):
        raise HTTPException(400, "체험 모드에서는 닉네임을 변경할 수 없습니다.")
    username_in_token = payload.get("sub")
    if not username_in_token:
        raise HTTPException(401, "세션이 만료되었습니다. 다시 로그인해주세요.")
    customer_id = payload.get("customer_id")

    nickname = body.nickname.strip()
    if not _NICKNAME_RE.match(nickname):
        raise HTTPException(400, "닉네임은 2~20자, 한글·영문·숫자만 사용 가능합니다.")

    try:
        conn = get_db()
        cur = conn.cursor()

        # 소셜 로그인은 토큰에 customer_id가 있고, 일반(local) 로그인은 없음.
        # local 계정도 username으로 자기 customers row를 찾아 동일하게 처리.
        if not customer_id:
            cur.execute(
                "SELECT id FROM customers WHERE username = %s",
                (username_in_token,),
            )
            row0 = cur.fetchone()
            if not row0:
                cur.close(); conn.close()
                raise HTTPException(404, "계정 정보를 찾을 수 없습니다.")
            customer_id = row0[0]

        cur.execute(
            "SELECT id FROM customers WHERE nickname = %s AND id != %s",
            (nickname, customer_id),
        )
        if cur.fetchone():
            cur.close(); conn.close()
            raise HTTPException(400, "이미 사용 중인 닉네임입니다.")
        cur.execute(
            "UPDATE customers SET nickname = %s WHERE id = %s",
            (nickname, customer_id),
        )
        conn.commit()
        cur.close(); conn.close()
        return {"status": "ok", "nickname": nickname}
    except HTTPException:
        raise
    except Exception:
        logger.error("set_nickname: DB error", exc_info=True)
        raise HTTPException(500, "이미 오류가 발생했습니다.")


# ── Google OAuth ─────────────────────────────────────────────────────────────

def _load_google_client() -> dict:
    if GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET:
        return {
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "auth_uri": GOOGLE_AUTH_URI,
            "token_uri": GOOGLE_TOKEN_URI,
        }

    raise HTTPException(
        status_code=503,
        detail="Google OAuth environment variables GOOGLE_CLIENT_ID or GOOGLE_CLIENT_SECRET are not set on Render."
    )


@router.get("/google")
def google_login():
    client = _load_google_client()
    params = {
        "client_id":     client["client_id"],
        "redirect_uri":  GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope":         "openid email profile",
        "access_type":   "offline",
        "prompt":        "select_account",
    }
    return RedirectResponse(f"{client['auth_uri']}?{urlencode(params)}")


@router.get("/google/callback")
def google_callback(code: str):
    client = _load_google_client()

    token_resp = httpx.post(
        client["token_uri"],
        data={
            "code":          code,
            "client_id":     client["client_id"],
            "client_secret": client["client_secret"],
            "redirect_uri":  GOOGLE_REDIRECT_URI,
            "grant_type":    "authorization_code",
        },
        timeout=10,
    )
    token_data   = token_resp.json()
    access_token = token_data.get("access_token")
    if not access_token:
        raise HTTPException(400, "Google 토큰 교환 실패")

    userinfo_resp = httpx.get(
        "https://www.googleapis.com/oauth2/v3/userinfo",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=10,
    )
    userinfo  = userinfo_resp.json()
    email     = userinfo.get("email", "")
    name      = userinfo.get("name") or email
    social_id = userinfo.get("sub", "")

    if not social_id:
        raise HTTPException(400, "Google 사용자 정보를 가져올 수 없습니다.")

    customer_id, username, is_new = _find_or_create_social_user("google", social_id, email, name)
    token   = create_token(username, customer_id)
    refresh = create_refresh_token(username, customer_id)

    redirect_url = "/nickname" if is_new else "/"
    resp = RedirectResponse(url=redirect_url, status_code=302)
    _set_auth_cookie(resp, token)
    _set_refresh_cookie(resp, refresh)
    return resp


# ── Kakao OAuth ──────────────────────────────────────────────────────────────

@router.get("/kakao")
def kakao_login():
    if not KAKAO_CLIENT_ID:
        raise HTTPException(503, "카카오 로그인이 설정되지 않았습니다.")
    params = {
        "client_id":     KAKAO_CLIENT_ID,
        "redirect_uri":  KAKAO_REDIRECT_URI,
        "response_type": "code",
    }
    return RedirectResponse(f"https://kauth.kakao.com/oauth/authorize?{urlencode(params)}")


@router.get("/kakao/callback")
def kakao_callback(code: str):
    if not KAKAO_CLIENT_SECRET:
        raise HTTPException(503, "KAKAO_CLIENT_SECRET 환경변수가 설정되지 않았습니다.")

    token_resp = httpx.post(
        "https://kauth.kakao.com/oauth/token",
        data={
            "grant_type":    "authorization_code",
            "client_id":     KAKAO_CLIENT_ID,
            "client_secret": KAKAO_CLIENT_SECRET,
            "redirect_uri":  KAKAO_REDIRECT_URI,
            "code":          code,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=10,
    )
    token_data   = token_resp.json()
    access_token = token_data.get("access_token")
    if not access_token:
        raise HTTPException(400, "카카오 토큰 교환 실패")

    userinfo_resp = httpx.get(
        "https://kapi.kakao.com/v2/user/me",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=10,
    )
    userinfo      = userinfo_resp.json()
    social_id     = str(userinfo.get("id", ""))
    kakao_account = userinfo.get("kakao_account", {})
    email         = kakao_account.get("email", "")
    profile       = kakao_account.get("profile", {})
    name          = profile.get("nickname") or email or f"kakao_{social_id}"

    if not social_id:
        raise HTTPException(400, "카카오 사용자 정보를 가져올 수 없습니다.")

    customer_id, username, is_new = _find_or_create_social_user("kakao", social_id, email, name)
    token   = create_token(username, customer_id)
    refresh = create_refresh_token(username, customer_id)

    redirect_url = "/nickname" if is_new else "/"
    resp = RedirectResponse(url=redirect_url, status_code=302)
    _set_auth_cookie(resp, token)
    _set_refresh_cookie(resp, refresh)
    return resp
