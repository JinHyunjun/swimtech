"""
SwimTech — 인증 모듈
JWT 기반 로컬 로그인 + Google / Kakao 소셜 로그인
"""
import json
import os
from datetime import datetime, timedelta
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException, Response, Cookie
from fastapi.responses import JSONResponse, RedirectResponse
from jose import jwt
from pydantic import BaseModel
import psycopg2
import bcrypt

router = APIRouter()

SECRET_KEY          = os.getenv("SECRET_KEY", "swimtech-secret-key")
ALGORITHM           = "HS256"
TOKEN_EXPIRE_HOURS  = 24

ADMIN_ID = os.getenv("ADMIN_ID", "admin")
ADMIN_PW = os.getenv("ADMIN_PW", "swimtech1234")

DATABASE_URL = os.getenv("DATABASE_URL", "")

GOOGLE_OAUTH_FILE   = "/app/credentials/google_oauth_client.json"
GOOGLE_REDIRECT_URI = "https://localhost/auth/google/callback"

KAKAO_CLIENT_ID     = os.getenv("KAKAO_CLIENT_ID", "")
KAKAO_CLIENT_SECRET = os.getenv("KAKAO_CLIENT_SECRET", "")
KAKAO_REDIRECT_URI  = "https://localhost/auth/kakao/callback"


def get_db():
    return psycopg2.connect(DATABASE_URL)


def _ensure_social_columns():
    """social_provider / social_id 컬럼 마이그레이션 (멱등)"""
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("ALTER TABLE customers ADD COLUMN IF NOT EXISTS social_provider TEXT")
        cur.execute("ALTER TABLE customers ADD COLUMN IF NOT EXISTS social_id TEXT")
        conn.commit()
        cur.close()
        conn.close()
    except Exception:
        pass


_ensure_social_columns()


class LoginRequest(BaseModel):
    username: str
    password: str


class RegisterRequest(BaseModel):
    name: str
    email: str
    username: str
    password: str


def create_token(username: str, customer_id: int | None = None) -> str:
    expire = datetime.utcnow() + timedelta(hours=TOKEN_EXPIRE_HOURS)
    payload = {"sub": username, "exp": expire}
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


def _find_or_create_social_user(
    provider: str,
    social_id: str,
    email: str,
    name: str,
) -> tuple[int, str]:
    """소셜 로그인 사용자 조회/생성 → (customer_id, username)"""
    conn = get_db()
    cur = conn.cursor()

    # 1) social_id + provider 로 먼저 검색
    cur.execute(
        "SELECT id, username FROM customers WHERE social_provider = %s AND social_id = %s",
        (provider, social_id),
    )
    row = cur.fetchone()
    if row:
        cur.close(); conn.close()
        return row[0], row[1]

    # 2) 이메일로 기존 계정 연결
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
            return row[0], row[1]

    # 3) 신규 가입
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
    return customer_id, username


# ── 로컬 인증 ─────────────────────────────────────────────────────────────────

@router.post("/register")
def register(body: RegisterRequest):
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
            (body.name, body.email, body.username, password_hash),
        )
        conn.commit()
        cur.close(); conn.close()
        return {"status": "ok"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"DB 오류: {e}")


@router.post("/login")
def login(body: LoginRequest, response: Response):
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
    except Exception as e:
        raise HTTPException(500, f"DB 오류: {e}")

    if row:
        db_id, password_hash = row
        pw_bytes = body.password.encode("utf-8")[:72]
        if not bcrypt.checkpw(pw_bytes, password_hash.encode("utf-8")):
            raise HTTPException(401, "아이디 또는 비밀번호가 올바르지 않습니다.")
        customer_id = db_id
    else:
        if body.username != ADMIN_ID or body.password != ADMIN_PW:
            raise HTTPException(401, "아이디 또는 비밀번호가 올바르지 않습니다.")

    token = create_token(body.username, customer_id)
    _set_auth_cookie(response, token)
    return {"status": "ok", "message": f"{body.username}님 환영합니다!"}


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie("swimtech_token")
    return {"status": "ok", "message": "로그아웃 완료"}


@router.get("/me")
def me(swimtech_token: str = Cookie(default=None)):
    """현재 로그인 상태 확인"""
    if not swimtech_token:
        raise HTTPException(401, "로그인이 필요합니다.")
    username = verify_token(swimtech_token)
    if not username:
        raise HTTPException(401, "세션이 만료되었습니다. 다시 로그인해주세요.")
    return {"username": username, "status": "authenticated"}


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
        raise HTTPException(400, f"Google 토큰 교환 실패: {token_data.get('error_description', '')}")

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

    customer_id, username = _find_or_create_social_user("google", social_id, email, name)
    token = create_token(username, customer_id)

    resp = RedirectResponse(url="/", status_code=302)
    _set_auth_cookie(resp, token)
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
        raise HTTPException(400, f"카카오 토큰 교환 실패: {token_data.get('error_description', '')}")

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

    customer_id, username = _find_or_create_social_user("kakao", social_id, email, name)
    token = create_token(username, customer_id)

    resp = RedirectResponse(url="/", status_code=302)
    _set_auth_cookie(resp, token)
    return resp
