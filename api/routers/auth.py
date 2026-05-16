"""
SwimTech — 로그인 인증 모듈
JWT 토큰 기반 / 사용자 계정은 .env에서 관리
"""
import os
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException, Response, Cookie
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from jose import jwt
import psycopg2
import bcrypt

router = APIRouter()

SECRET_KEY = os.getenv("SECRET_KEY", "swimtech-secret-key")
ALGORITHM  = "HS256"
TOKEN_EXPIRE_HOURS = 24

ADMIN_ID = os.getenv("ADMIN_ID", "admin")
ADMIN_PW = os.getenv("ADMIN_PW", "swimtech1234")

DATABASE_URL = os.getenv("DATABASE_URL", "")

def get_db():
    return psycopg2.connect(DATABASE_URL)


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

        password_bytes = body.password.encode('utf-8')[:72]
        password_hash = bcrypt.hashpw(password_bytes, bcrypt.gensalt()).decode('utf-8')
        cur.execute(
            "INSERT INTO customers (name, email, username, password_hash) VALUES (%s, %s, %s, %s)",
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

    # 1) customers 테이블에서 username 조회
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
        # 2) DB에 없으면 admin 계정 fallback
        if body.username != ADMIN_ID or body.password != ADMIN_PW:
            raise HTTPException(401, "아이디 또는 비밀번호가 올바르지 않습니다.")

    token = create_token(body.username, customer_id)

    # HttpOnly 쿠키로 저장 (JS에서 접근 불가 → XSS 방어)
    response.set_cookie(
        key="swimtech_token",
        value=token,
        httponly=True,
        max_age=60 * 60 * TOKEN_EXPIRE_HOURS,
        samesite="lax",
    )
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
