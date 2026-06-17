"""
SwimTech ???몄쬆 紐⑤뱢
JWT 湲곕컲 濡쒖뺄 濡쒓렇??+ Google / Kakao ?뚯뀥 濡쒓렇??
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
LOGIN_FAIL_EXPIRE = 900  # 15遺?(珥?

ADMIN_ID = os.getenv("ADMIN_ID", "admin")
ADMIN_PW = os.getenv("ADMIN_PW", "swimtech1234")

DATABASE_URL = os.getenv("DATABASE_URL", "")
REDIS_URL    = os.getenv("REDIS_URL", "redis://redis:6379/0")

GOOGLE_OAUTH_FILE   = "/app/credentials/google_oauth_client.json"

KAKAO_CLIENT_ID     = os.getenv("KAKAO_CLIENT_ID", "")
KAKAO_CLIENT_SECRET = os.getenv("KAKAO_CLIENT_SECRET", "")

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
GOOGLE_AUTH_URI = os.getenv("GOOGLE_AUTH_URI", "https://accounts.google.com/o/oauth2/v2/auth")
GOOGLE_TOKEN_URI = os.getenv("GOOGLE_TOKEN_URI", "https://oauth2.googleapis.com/token")

# BASE_URL: Cloudflare Tunnel ???몃? ?꾨찓???ъ슜 ???섍꼍蹂?섎줈 二쇱엯
# ?? BASE_URL=https://wilderness-xxx.trycloudflare.com
_BASE_URL = os.getenv("BASE_URL", "https://localhost").rstrip("/")
GOOGLE_REDIRECT_URI = f"{_BASE_URL}/auth/google/callback"
KAKAO_REDIRECT_URI  = f"{_BASE_URL}/auth/kakao/callback"

_USERNAME_RE = re.compile(r'^[a-zA-Z0-9]{4,20}$')
_PASSWORD_RE = re.compile(r'^(?=.*[A-Za-z])(?=.*\d).{8,}$')
_HTML_TAG_RE = re.compile(r'<[^>]+>')
_NICKNAME_RE = re.compile(r"^[\uac00-\ud7a3a-zA-Z0-9]{2,20}$")


# ?? DB / Redis helpers ????????????????????????????????????????????????????????

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


# ?? 濡쒓렇???ㅽ뙣 異붿쟻 ??????????????????????????????????????????????????????????

def _check_login_blocked(ip: str):
    r = _get_redis()
    if not r:
        return
    try:
        count = r.get(f"login_fail:{ip}")
        if count and int(count) >= LOGIN_FAIL_MAX:
            raise HTTPException(429, "?덈Т 留롮? 濡쒓렇???쒕룄. 15遺????ㅼ떆 ?쒕룄?섏꽭??")
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


# ?? ?뚯뀥 而щ읆 留덉씠洹몃젅?댁뀡 ????????????????????????????????????????????????????

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


# ?? Pydantic 紐⑤뜽 ?????????????????????????????????????????????????????????????

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


# ?? ?좏겙 ?좏떥 ?????????????????????????????????????????????????????????????????

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
    """?좏겙 寃利????좎?紐?諛섑솚, ?ㅽ뙣 ??None"""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload.get("sub")
    except Exception:
        return None


def decode_token(token: str) -> dict:
    """?좏겙 ?붿퐫????payload dict 諛섑솚, ?ㅽ뙣 ??{}"""
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


# ?? ?뚯뀥 ?ъ슜??議고쉶/?앹꽦 ?????????????????????????????????????????????????????

def _find_or_create_social_user(
    provider: str,
    social_id: str,
    email: str,
    name: str,
) -> tuple[int, str, bool]:
    """湲곗〈 ?ъ슜????(id, username, False), ?좉퇋 媛????(id, username, True)"""
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


# ?? 濡쒖뺄 ?몄쬆 ?????????????????????????????????????????????????????????????????

@router.post("/register")
def register(body: RegisterRequest):
    name = _strip_tags((body.name or "").strip())
    email = (body.email or "").strip()
    username = (body.username or "").strip()
    password = body.password or ""

    if not name:
        raise HTTPException(400, "\uc774\ub984\uc744 \uc785\ub825\ud574\uc8fc\uc138\uc694.")

    if len(name) > 50:
        raise HTTPException(400, "\uc774\ub984\uc740 \ucd5c\ub300 50\uc790\uae4c\uc9c0 \ud5c8\uc6a9\ub429\ub2c8\ub2e4.")

    try:
        validate_email(email, check_deliverability=False)
    except EmailNotValidError:
        raise HTTPException(400, "\uc720\ud6a8\ud558\uc9c0 \uc54a\uc740 \uc774\uba54\uc77c \ud615\uc2dd\uc785\ub2c8\ub2e4.")

    if not _USERNAME_RE.match(username):
        raise HTTPException(400, "\uc544\uc774\ub514\ub294 \uc601\ubb38/\uc22b\uc790 4~20\uc790\uc5ec\uc57c \ud569\ub2c8\ub2e4.")

    if not _PASSWORD_RE.match(password):
        raise HTTPException(400, "\ube44\ubc00\ubc88\ud638\ub294 \ucd5c\uc18c 8\uc790 \uc774\uc0c1, \uc601\ubb38\uacfc \uc22b\uc790\ub97c \ud3ec\ud568\ud574\uc57c \ud569\ub2c8\ub2e4.")

    conn = None
    cur = None

    try:
        conn = get_db()
        cur = conn.cursor()

        cur.execute("SELECT id FROM customers WHERE username = %s", (username,))
        if cur.fetchone():
            raise HTTPException(400, "\uc774\ubbf8 \uc0ac\uc6a9 \uc911\uc778 \uc544\uc774\ub514\uc785\ub2c8\ub2e4.")

        cur.execute("SELECT id FROM customers WHERE email = %s", (email,))
        if cur.fetchone():
            raise HTTPException(400, "\uc774\ubbf8 \uc0ac\uc6a9 \uc911\uc778 \uc774\uba54\uc77c\uc785\ub2c8\ub2e4.")

        password_bytes = password.encode("utf-8")[:72]
        password_hash = bcrypt.hashpw(password_bytes, bcrypt.gensalt()).decode("utf-8")

        cur.execute(
            "INSERT INTO customers (name, email, username, password_hash, social_provider)"
            " VALUES (%s, %s, %s, %s, 'local')",
            (name, email, username, password_hash),
        )

        conn.commit()
        return {"status": "ok"}

    except HTTPException:
        raise

    except Exception:
        logger.error("register: DB error", exc_info=True)
        raise HTTPException(500, "\ub0b4\ubd80 \uc624\ub958\uac00 \ubc1c\uc0dd\ud588\uc2b5\ub2c8\ub2e4.")

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
        raise HTTPException(500, "?대? ?ㅻ쪟媛 諛쒖깮?덉뒿?덈떎.")

    if row:
        db_id, password_hash = row
        pw_bytes = body.password.encode("utf-8")[:72]
        if not bcrypt.checkpw(pw_bytes, password_hash.encode("utf-8")):
            _increment_login_fail(ip)
            raise HTTPException(401, "?꾩씠???먮뒗 鍮꾨?踰덊샇媛 ?щ컮瑜댁? ?딆뒿?덈떎.")
        customer_id = db_id
    else:
        if body.username != ADMIN_ID or body.password != ADMIN_PW:
            _increment_login_fail(ip)
            raise HTTPException(401, "?꾩씠???먮뒗 鍮꾨?踰덊샇媛 ?щ컮瑜댁? ?딆뒿?덈떎.")

    _clear_login_fail(ip)
    token   = create_token(body.username, customer_id)
    refresh = create_refresh_token(body.username, customer_id)
    _set_auth_cookie(response, token)
    _set_refresh_cookie(response, refresh)
    return {"status": "ok", "message": f"{body.username}???섏쁺?⑸땲??"}


@router.post("/refresh")
def refresh_token_endpoint(
    response: Response,
    swimtech_refresh_token: str = Cookie(default=None),
):
    if not swimtech_refresh_token:
        raise HTTPException(401, "由ы봽?덉떆 ?좏겙???놁뒿?덈떎.")
    try:
        payload = jwt.decode(swimtech_refresh_token, SECRET_KEY, algorithms=[ALGORITHM])
    except Exception:
        raise HTTPException(401, "由ы봽?덉떆 ?좏겙??留뚮즺?섏뿀?듬땲??")
    if payload.get("type") != "refresh":
        raise HTTPException(401, "?좏슚?섏? ?딆? ?좏겙 ??낆엯?덈떎.")
    username    = payload.get("sub")
    customer_id = payload.get("customer_id")
    token = create_token(username, customer_id)
    _set_auth_cookie(response, token)
    return {"status": "ok", "message": "?좏겙??媛깆떊?섏뿀?듬땲??"}


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie("swimtech_token")
    response.delete_cookie("swimtech_refresh_token")
    return {"status": "ok", "message": "濡쒓렇?꾩썐 ?꾨즺"}


@router.get("/me")
def me(swimtech_token: str = Cookie(default=None)):
    if not swimtech_token:
        raise HTTPException(401, "濡쒓렇?몄씠 ?꾩슂?⑸땲??")
    payload = decode_token(swimtech_token)
    username = payload.get("sub")
    if not username:
        raise HTTPException(401, "?몄뀡??留뚮즺?섏뿀?듬땲?? ?ㅼ떆 濡쒓렇?명빐二쇱꽭??")

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
        raise HTTPException(401, "濡쒓렇?몄씠 ?꾩슂?⑸땲??")
    payload = decode_token(swimtech_token)
    if not payload.get("sub"):
        raise HTTPException(401, "?몄뀡??留뚮즺?섏뿀?듬땲?? ?ㅼ떆 濡쒓렇?명빐二쇱꽭??")
    customer_id = payload.get("customer_id")
    if not customer_id:
        raise HTTPException(400, "?됰꽕???ㅼ젙? ?뚯뀥 濡쒓렇??怨꾩젙留?媛?ν빀?덈떎.")

    nickname = body.nickname.strip()
    if not _NICKNAME_RE.match(nickname):
        raise HTTPException(400, "?됰꽕?꾩? 2~20?? ?쒓?쨌?곷Ц쨌?レ옄留??ъ슜 媛?ν빀?덈떎.")

    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "SELECT id FROM customers WHERE nickname = %s AND id != %s",
            (nickname, customer_id),
        )
        if cur.fetchone():
            cur.close(); conn.close()
            raise HTTPException(400, "?대? ?ъ슜 以묒씤 ?됰꽕?꾩엯?덈떎.")
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
        raise HTTPException(500, "?대? ?ㅻ쪟媛 諛쒖깮?덉뒿?덈떎.")


# ?? Google OAuth ??????????????????????????????????????????????????????????????

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
        raise HTTPException(400, "Google ?좏겙 援먰솚 ?ㅽ뙣")

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
        raise HTTPException(400, "Google ?ъ슜???뺣낫瑜?媛?몄삱 ???놁뒿?덈떎.")

    customer_id, username, is_new = _find_or_create_social_user("google", social_id, email, name)
    token   = create_token(username, customer_id)
    refresh = create_refresh_token(username, customer_id)

    redirect_url = "/nickname" if is_new else "/"
    resp = RedirectResponse(url=redirect_url, status_code=302)
    _set_auth_cookie(resp, token)
    _set_refresh_cookie(resp, refresh)
    return resp


# ?? Kakao OAuth ???????????????????????????????????????????????????????????????

@router.get("/kakao")
def kakao_login():
    if not KAKAO_CLIENT_ID:
        raise HTTPException(503, "移댁뭅??濡쒓렇?몄씠 ?ㅼ젙?섏? ?딆븯?듬땲??")
    params = {
        "client_id":     KAKAO_CLIENT_ID,
        "redirect_uri":  KAKAO_REDIRECT_URI,
        "response_type": "code",
    }
    return RedirectResponse(f"https://kauth.kakao.com/oauth/authorize?{urlencode(params)}")


@router.get("/kakao/callback")
def kakao_callback(code: str):
    if not KAKAO_CLIENT_SECRET:
        raise HTTPException(503, "KAKAO_CLIENT_SECRET ?섍꼍蹂?섍? ?ㅼ젙?섏? ?딆븯?듬땲??")

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
        raise HTTPException(400, "移댁뭅???좏겙 援먰솚 ?ㅽ뙣")

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
        raise HTTPException(400, "移댁뭅???ъ슜???뺣낫瑜?媛?몄삱 ???놁뒿?덈떎.")

    customer_id, username, is_new = _find_or_create_social_user("kakao", social_id, email, name)
    token   = create_token(username, customer_id)
    refresh = create_refresh_token(username, customer_id)

    redirect_url = "/nickname" if is_new else "/"
    resp = RedirectResponse(url=redirect_url, status_code=302)
    _set_auth_cookie(resp, token)
    _set_refresh_cookie(resp, refresh)
    return resp
