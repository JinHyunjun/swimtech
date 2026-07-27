# -*- coding: utf-8 -*-
import os
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from google import genai
from google.genai import types

from routers.auth import verify_token
from rate_limit import limiter
from db import get_db as _get_db
from services.chat_personalization import load_personalization
from services.swimming_knowledge import (
    build_knowledge_context,
    grounding_payload,
    retrieve_knowledge,
)

router = APIRouter()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
MODEL_FALLBACKS = [
    "gemini-3.1-flash-lite",
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash",
    "gemini-3-flash-preview",
]

SYSTEM_PROMPT_BASE = (
    "당신은 SwimMate의 수영 전문 AI 어시스턴트입니다. 서비스 사용법에 한정하지 않고 수영 영법, "
    "훈련 설계, 사이클, 대회 규정, 장비, 안전, 회복, 오픈워터 등 수영 전반의 질문에 친절하고 "
    "구체적으로 답변하세요. "
    "수영과 무관한 질문(코딩, 정치, 일반 잡담, 다른 운동 등)을 받으면, 정중히 수영 관련 "
    "질문으로 유도하며 답변을 거절하세요. "
    "검수된 지식베이스가 제공되면 우선 근거로 사용하고, 제공되지 않은 출처·통계·최신 확인 결과를 "
    "지어내지 마세요. 규정은 변경될 수 있으므로 적용 기준과 공식 원문 확인 필요성을 분명히 하세요. "
    "개인화 데이터가 제공되면 일반 원칙과 사용자 기록에 근거한 해석을 구분하고, 데이터에 없는 기록은 "
    "추측하지 마세요. 의료 진단이나 치료를 하지 말고 위험 신호나 지속되는 통증에는 훈련 중단과 "
    "적절한 전문가 확인을 안내하세요. 영상 영법 분석이나 워치 자동 연동이 가능한 것처럼 말하지 마세요. "
    "답변은 충분히 상세하게, 필요하면 단계별 목록 형태로 구체적으로 설명하세요. "
    "절대로 '어떤 영법/방법이 궁금하신가요?' 같은 되묻기로 답변을 피하지 마세요 — 직전 대화에 "
    "이미 주제가 나와 있다면 그 주제를 그대로 더 깊게 설명하세요."
)


_client = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        if not GEMINI_API_KEY:
            raise HTTPException(500, "GEMINI_API_KEY가 설정되지 않았습니다")
        _client = genai.Client(api_key=GEMINI_API_KEY)
    return _client


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


def _validated_text(content: str) -> str:
    user_text = (content or "").strip()
    if not user_text:
        raise HTTPException(400, "메시지를 입력해주세요")
    if len(user_text) > 1000:
        raise HTTPException(400, "메시지가 너무 길어요 (1000자 이하로 입력해주세요)")
    return user_text


def _context_query(recent: list[tuple[str, str]], current_text: str) -> str:
    """Keep follow-up questions grounded in the latest user topic."""
    recent_user_messages = [
        content for role, content in recent if role == "user"
    ][-3:]
    if not recent_user_messages or recent_user_messages[-1] != current_text:
        recent_user_messages.append(current_text)
    return "\n".join(recent_user_messages)[-3000:]


def _prepare_context(
    username: str,
    knowledge_query: str,
    personalization_query: Optional[str] = None,
):
    knowledge_items = retrieve_knowledge(knowledge_query, limit=3)
    personalization = load_personalization(
        username,
        personalization_query if personalization_query is not None else knowledge_query,
        _get_db,
    )
    grounding = grounding_payload(knowledge_items)
    grounding["personalization"] = personalization.payload()
    return (
        build_knowledge_context(knowledge_items),
        personalization,
        grounding,
    )


@router.post("/context-preview")
@limiter.limit("30/minute")
def context_preview(body: SendMessageRequest, request: Request):
    """Expose safe grounding metadata for QA without invoking Gemini."""
    username = _get_username(request)
    if not username:
        raise HTTPException(401, "로그인이 필요합니다")
    user_text = _validated_text(body.content)
    _, _, grounding = _prepare_context(username, user_text)
    return {"grounding": grounding}


@router.post("/send")
@limiter.limit("10/minute")
def send_message(body: SendMessageRequest, request: Request):
    username = _get_username(request)
    if not username:
        raise HTTPException(401, "로그인이 필요합니다")

    user_text = _validated_text(body.content)

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

    reply = None
    generation_succeeded = False
    grounding = {
        "knowledge_version": None,
        "topics": [],
        "sources": [],
        "related_links": [],
        "personalization": {
            "available": False,
            "applied": False,
            "categories": [],
            "privacy_scope": "authenticated_customer_only",
        },
    }
    try:
        client = _get_client()
        conn = _get_db()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT role, content FROM chat_histories
            WHERE username = %s
            ORDER BY created_at DESC
            LIMIT 12
            """,
            (username,),
        )
        recent = list(reversed(cur.fetchall()))
        cur.close()
        conn.close()

        contents = [
            {"role": "model" if r == "bot" else "user", "parts": [{"text": c}]}
            for r, c in recent
        ]

        query = _context_query(recent, user_text)
        knowledge_context, personalization, grounding = _prepare_context(
            username,
            query,
            personalization_query=user_text,
        )
        system_instruction = (
            SYSTEM_PROMPT_BASE
            + knowledge_context
            + personalization.text
        )

        last_error = None
        for model_name in MODEL_FALLBACKS:
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        system_instruction=system_instruction,
                        max_output_tokens=2048,
                        temperature=0.7,
                    ),
                )
                reply = (getattr(response, "text", "") or "").strip()
                if reply:
                    generation_succeeded = True
                    break
            except genai.errors.APIError as e:
                last_error = e
                if getattr(e, "code", None) == 429:
                    continue  # 이 모델의 오늘 무료 한도 소진 → 다음 모델로 전환
                raise

        if not reply:
            if last_error is not None and getattr(last_error, "code", None) == 429:
                detail_text = str(getattr(last_error, "message", "") or str(last_error)).lower()
                if "minute" in detail_text or "perminute" in detail_text:
                    reply = "지금 AI 코치에 질문이 몰려서 잠시 혼잡합니다. 1분 정도 후 다시 시도해주세요."
                else:
                    reply = "오늘 AI 코치 무료 사용량이 가득 찼어요. 내일 다시 이용해주시거나, 잠시 후 다시 시도해주세요."
            else:
                reply = "죄송해요, 답변을 생성하지 못했어요. 다시 한 번 질문해주시겠어요?"
    except Exception:
        reply = "지금 AI 코치 응답이 지연되고 있어요. 잠시 후 다시 시도해주세요."

    grounding["answer_generated"] = generation_succeeded

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

    return {
        "reply": reply,
        "id": row[0],
        "created_at": str(row[1]),
        "grounding": grounding,
    }


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
