# -*- coding: utf-8 -*-
"""SwimMate — 공통 FastAPI 인증 Dependency.

라우터에서 반복되던 쿠키 토큰 검사 로직을 한 곳으로 모은다.

사용 예:
    from deps import get_current_user, get_current_user_optional, CurrentUser

    @router.get("/me")
    def me(user: CurrentUser):
        return {"username": user["username"]}

    @router.get("/feed")
    def feed(user = Depends(get_current_user_optional)):
        username = user["username"] if user else "guest"
"""
from __future__ import annotations

from typing import Annotated, Optional

from fastapi import Cookie, Depends, HTTPException

from routers.auth import decode_token, verify_token


def get_current_user(
    swimtech_token: Annotated[Optional[str], Cookie()] = None,
) -> dict:
    """로그인 필수 엔드포인트용 — 미인증 시 401."""
    if not swimtech_token:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    payload = decode_token(swimtech_token)
    username = payload.get("sub")
    if not username:
        raise HTTPException(status_code=401, detail="유효하지 않은 토큰입니다.")
    return {
        "username": username,
        "customer_id": payload.get("customer_id"),
        "is_demo": payload.get("is_demo", False),
    }


def get_current_user_optional(
    swimtech_token: Annotated[Optional[str], Cookie()] = None,
) -> Optional[dict]:
    """로그인 선택 엔드포인트용 — 미인증 시 None 반환."""
    if not swimtech_token:
        return None
    payload = decode_token(swimtech_token)
    username = payload.get("sub")
    if not username:
        return None
    return {
        "username": username,
        "customer_id": payload.get("customer_id"),
        "is_demo": payload.get("is_demo", False),
    }


def get_username_optional(
    swimtech_token: Annotated[Optional[str], Cookie()] = None,
) -> str:
    """username 문자열만 필요할 때 — 미인증 시 'guest'."""
    if not swimtech_token:
        return "guest"
    return verify_token(swimtech_token) or "guest"


# 타입 별칭 — Annotated[dict, Depends(...)] 반복을 줄이기 위함
CurrentUser = Annotated[dict, Depends(get_current_user)]
OptionalUser = Annotated[Optional[dict], Depends(get_current_user_optional)]
