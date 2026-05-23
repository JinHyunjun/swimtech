"""
SwimTech — 인증 모듈
JWT 기반 로컬 로그인 + Google / Kakao 소셜 로그인
"""
import json
import logging
import os
import re
from datetime import datetime, timedelta
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

DATABASE_URL = os.getenv("DATABASE_URL", "")
REDIS_URL    = os.getenv("REDIS_URL", "redis://redis:6379/0")

GOOGLE_OAUTH_FILE   = "/app/credentials/google_oauth_client.json"
GOOGLE_REDIRECT_URI = "https://localhost/auth/google/callback"

KAKAO_CLIENT_ID     = os.getenv("KAKAO_CLIENT_ID", "")
KAKAO_CLIENT_SECRET = os.getenv("KAKAO_CLIENT_SECRET", "")
KAKAO_REDIRECT_URI  = "https://localhost/auth/kakao/callback"

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

def create_token(username: str, customer_id: int | None = None) -> str:
    expire = datetime.utcnow() + timedelta(hours=TOKEN_EXPIRE_HOURS)
    payload = {"sub": username, "exp": expire}
    if customer_id is not None:
        payload["customer_id"] = customer_id
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def create_refresh_token(username: str, customer_id: int | None = None) -> str:
    expire = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    payload = {"sub": username, "exp": expire, "type": "refresh"}
    if customer_id is not None:
        payload["customer_id"] = customer_id
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

@router.post("/register")
def register(body: RegisterRequest):
    name = _strip_tags(body.name.strip())
    if not name:
        raise HTTPException(400, "이름을 입력해주세요.")
    if len(name) > 50:
        raise HTTPException(400, "이름은 최대 50자까지 허용됩니다.")

    try:
        validate_email(body.email, check_deliverability=False)
    except EmailNotValidError:
        raise HTTPException(400, "유효하지 않은 이메일 형식입니다.")

    if not _USERNAME_RE.match(body.username):
        raise HTTPException(400, "아이디는 영문/숫자 4~20자여야 합니다.")

    if not _PASSWORD_RE.match(body.password):
        raise HTTPException(400, "비밀번호는 최소 8자 이상, 영문과 숫자를 포함해야 합니다.")

    try:
        conn = get_db()
        cur = conn.cursor()

        cur.execute("SELECT id FROM customers WHERE username = %s", (body.username,))
        if cur.fetchone():
            cur.close(); conn.close()
            raise HTTPException(400, "이미 사용 중인 아이디입니다.")

        cur.execute("SELECT id FROM customers WHERE email = %s", (body.email,))
        if cur.fetchone():
            cur.close(); conn.close()
            raise HTTPException(400, "이미 사용 중인 이메일입니다.")

        password_bytes = body.password.encode("utf-8")[:72]
        password_hash  = bcrypt.hashpw(password_bytes, bcrypt.gensalt()).decode("utf-8")
        cur.execute(
            "INSERT INTO customers (name, email, username, password_hash, social_provider)"
            " VALUES (%s, %s, %s, %s, 'local')",
            (name, body.email, body.username, password_hash),
        )
        conn.commit()
        cur.close(); conn.close()
        return {"status": "ok"}
    except HTTPException:
        raise
    except Exception:
        logger.error("register: DB error", exc_info=True)
        raise HTTPException(500, "내부 오류가 발생했습니다.")


@router.post("/login")
@limiter.limit("5/minute")
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
            raise HTTPException(401, "아이디 또는 비밀번호가 올바르지 않습니다.")
        customer_id = db_id
    else:
        if body.username != ADMIN_ID or body.password != ADMIN_PW:
            _increment_login_fail(ip)
            raise HTTPException(401, "아이디 또는 비밀번호가 올바르지 않습니다.")

    _clear_login_fail(ip)
    token   = create_token(body.username, customer_id)
    refresh = create_refresh_token(body.username, customer_id)
    _set_auth_cookie(response, token)
    _set_refresh_cookie(response, refresh)
    return {"status": "ok", "message": f"{body.username}님 환영합니다!"}


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
        raise HTTPException(401, "유효하지 않은 토큰 타입입니다.")
    username    = payload.get("sub")
    customer_id = payload.get("customer_id")
    token = create_token(username, customer_id)
    _set_auth_cookie(response, token)
    return {"status": "ok", "message": "토큰이 갱신되었습니다."}


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie("swimtech_token")
    response.delete_cookie("swimtech_refresh_token")
    return {"status": "ok", "message": "로그아웃 완료"}


@router.get("/me")
def me(swimtech_token: str = Cookie(default=None)):
    if not swimtech_token:
        raise HTTPException(401, "로그인이 필요합니다.")
    payload = decode_token(swimtech_token)
    username = payload.get("sub")
    if not username:
        raise HTTPException(401, "세션이 만료되었습니다. 다시 로그인해주세요.")

    customer_id     = payload.get("customer_id")
    nickname        = None
    social_provider = None

    if customer_id:
        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute(
                "SELECT nickname, social_provider FROM customers WHERE id = %s",
                (customer_id,),
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
        "needs_nickname":  nickname is None and social_provider not in (None, "local"),
    }


@router.post("/nickname")
def set_nickname(body: NicknameRequest, swimtech_token: str = Cookie(default=None)):
    if not swimtech_token:
        raise HTTPException(401, "로그인이 필요합니다.")
    payload = decode_token(swimtech_token)
    if not payload.get("sub"):
        raise HTTPException(401, "세션이 만료되었습니다. 다시 로그인해주세요.")
    customer_id = payload.get("customer_id")
    if not customer_id:
        raise HTTPException(400, "닉네임 설정은 소셜 로그인 계정만 가능합니다.")

    nickname = body.nickname.strip()
    if not _NICKNAME_RE.match(nickname):
        raise HTTPException(400, "닉네임은 2~20자, 한글·영문·숫자만 사용 가능합니다.")

    try:
        conn = get_db()
        cur = conn.cursor()
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
        raise HTTPException(500, "내부 오류가 발생했습니다.")


# ── Google OAuth ──────────────────────────────────────────────────────────────

def _load_google_client() -> dict:
    with open(GOOGLE_OAUTH_FILE) as f:
        return json.load(f)["web"]


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


# ── Kakao OAuth ───────────────────────────────────────────────────────────────

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
