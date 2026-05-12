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

router = APIRouter()

SECRET_KEY = os.getenv("SECRET_KEY", "swimtech-secret-key")
ALGORITHM  = "HS256"
TOKEN_EXPIRE_HOURS = 24

# .env에서 계정 관리 (여러 계정 가능)
# ADMIN_ID=admin / ADMIN_PW=swimtech1234 형태
ADMIN_ID = os.getenv("ADMIN_ID", "admin")
ADMIN_PW = os.getenv("ADMIN_PW", "swimtech1234")


class LoginRequest(BaseModel):
    username: str
    password: str


def create_token(username: str) -> str:
    expire = datetime.utcnow() + timedelta(hours=TOKEN_EXPIRE_HOURS)
    return jwt.encode(
        {"sub": username, "exp": expire},
        SECRET_KEY, algorithm=ALGORITHM
    )


def verify_token(token: str) -> str:
    """토큰 검증 → 유저명 반환, 실패 시 None"""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload.get("sub")
    except Exception:
        return None


@router.post("/login")
def login(body: LoginRequest, response: Response):
    if body.username != ADMIN_ID or body.password != ADMIN_PW:
        raise HTTPException(401, "아이디 또는 비밀번호가 올바르지 않습니다.")

    token = create_token(body.username)

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
