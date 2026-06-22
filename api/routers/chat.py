# -*- coding: utf-8 -*-
import os
from typing import Optional

import psycopg2
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from google import genai
from google.genai import types

from routers.auth import verify_token
from rate_limit import limiter

router = APIRouter()
DATABASE_URL = os.getenv("DATABASE_URL", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

SYSTEM_PROMPT = (
    "당신은 SwimTech의 수영 전문 AI 코치입니다. 수영 영법, 훈련 방법, 호흡법, 체력 관리, "
    "수영 장비, 부상 예방 등 수영과 관련된 질문에만 친절하고 구체적으로 답변하세요. "
    "수영과 무관한 질문(코딩, 정치, 일반 잡담, 다른 운동 등)을 받으면, 정중히 수영 관련 "
    "질문으로 유도하며 답변을 거절하세요. 답변은 2~4문장으로 간결하게 합니다."
)

_client = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        if not GEMINI_API_KEY:
            raise HTTPException(500, "GEMINI_API_KEY가 설정되지 않았습니다")
        _client = genai.Client(api_key=GEMINI_API_KEY)
    return _client


def _get_db():
    return psycopg2.connect(DATABASE_URL)


def _get_username(request: Request) -> Optional[str]:
    token = request.cookies.get("swimtech_token")
    if not token:
        return None
    return verify_token(token)


def _ensure_table():
    conn = _get_db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS chat_histories (
            id         SERIAL PRIMARY KEY,
            username   VARCHAR(100) NOT NULL,
            role       VARCHAR(10) NOT NULL CHECK (role IN ('user','bot')),
            content    TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_chat_hist_user ON chat_histories(username, created_at DESC)"
    )
    conn.commit()
    cur.close()
    conn.close()


class ChatMessage(BaseModel):
    role: str
    content: str


class SendMessageRequest(BaseModel):
    content: str


@router.post("/send")
@limiter.limit("10/minute")
def send_message(body: SendMessageRequest, request: Request):
    username = _get_username(request)
    if not username:
        raise HTTPException(401, "로그인이 필요합니다")

    user_text = body.content.strip()
    if not user_text:
        raise HTTPException(400, "메시지를 입력해주세요")
    if len(user_text) > 1000:
        raise HTTPException(400, "메시지가 너무 길어요 (1000자 이하로 입력해주세요)")

    try:
        _ensure_table()
        conn = _get_db()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO chat_histories (username, role, content) VALUES (%s,'user',%s)",
            (username, user_text),
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        raise HTTPException(500, f"DB 오류: {e}")

    try:
        client = _get_client()
        response = client.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=user_text,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                max_output_tokens=400,
                temperature=0.7,
            ),
        )
        reply = (getattr(response, "text", "") or "").strip()
        if not reply:
            reply = "죄송해요, 답변을 생성하지 못했어요. 다시 한 번 질문해주시겠어요?"
    except Exception:
        reply = "지금 AI 코치 응답이 지연되고 있어요. 잠시 후 다시 시도해주세요."

    try:
        conn = _get_db()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO chat_histories (username, role, content) VALUES (%s,'bot',%s) RETURNING id, created_at",
            (username, reply),
        )
        row = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        raise HTTPException(500, f"DB 오류: {e}")

    return {"reply": reply, "id": row[0], "created_at": str(row[1])}


@router.get("/history")
def get_history(request: Request):
    username = _get_username(request)
    if not username:
        raise HTTPException(401, "로그인이 필요합니다")
    try:
        _ensure_table()
        conn = _get_db()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, role, content, created_at
            FROM chat_histories
            WHERE username = %s
            ORDER BY created_at ASC
            LIMIT 50
            """,
            (username,),
        )
        rows = cur.fetchall()
        cur.close(); conn.close()
        return {
            "history": [
                {"id": r[0], "role": r[1], "content": r[2], "created_at": str(r[3])}
                for r in rows
            ]
        }
    except Exception as e:
        raise HTTPException(500, f"DB 오류: {e}")


@router.post("/history")
def save_message(body: ChatMessage, request: Request):
    username = _get_username(request)
    if not username:
        raise HTTPException(401, "로그인이 필요합니다")
    if body.role not in ("user", "bot"):
        raise HTTPException(400, "role은 'user' 또는 'bot'이어야 합니다")
    try:
        _ensure_table()
        conn = _get_db()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO chat_histories (username, role, content) VALUES (%s,%s,%s) RETURNING id, created_at",
            (username, body.role, body.content),
        )
        row = cur.fetchone()
        conn.commit()
        cur.close(); conn.close()
        return {"id": row[0], "created_at": str(row[1])}
    except Exception as e:
        raise HTTPException(500, f"DB 오류: {e}")


@router.delete("/history")
def clear_history(request: Request):
    username = _get_username(request)
    if not username:
        raise HTTPException(401, "로그인이 필요합니다")
    try:
        _ensure_table()
        conn = _get_db()
        cur = conn.cursor()
        cur.execute("DELETE FROM chat_histories WHERE username = %s", (username,))
        count = cur.rowcount
        conn.commit()
        cur.close(); conn.close()
        return {"deleted": count}
    except Exception as e:
        raise HTTPException(500, f"DB 오류: {e}")
