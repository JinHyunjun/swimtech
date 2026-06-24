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

SYSTEM_PROMPT_BASE = (
    "당신은 SwimTech의 수영 전문 AI 코치입니다. 수영 영법, 훈련 방법, 호흡법, 체력 관리, "
    "수영 장비, 부상 예방 등 수영과 관련된 질문에만 친절하고 구체적으로 답변하세요. "
    "수영과 무관한 질문(코딩, 정치, 일반 잡담, 다른 운동 등)을 받으면, 정중히 수영 관련 "
    "질문으로 유도하며 답변을 거절하세요. "
    "답변은 항상 충분히 상세하게, 필요하면 단계별 목록 형태로 구체적으로 설명하세요. "
    "절대로 '어떤 영법/방법이 궁금하신가요?' 같은 되묻기로 답변을 피하지 마세요 — 직전 대화에 "
    "이미 주제가 나와 있다면 그 주제를 그대로 더 깊게 설명하세요."
)


def _get_training_summary(username: str) -> str:
    """사용자의 최근 훈련 일지를 요약해서, AI 코치가 맞춤 답변을 줄 수 있도록 컨텍스트로 제공.
    실패해도 챗봇 자체가 죽으면 안 되므로 빈 문자열 반환으로 안전하게 처리."""
    try:
        conn = _get_db()
        cur = conn.cursor()
        cur.execute("SELECT id FROM customers WHERE username = %s", (username,))
        row = cur.fetchone()
        if not row:
            cur.close(); conn.close()
            return ""
        cid = row[0]

        cur.execute("""
            SELECT log_date, stroke_type, total_distance, duration_minutes, intensity
            FROM training_logs
            WHERE customer_id = %s
            ORDER BY log_date DESC
            LIMIT 8
        """, (cid,))
        recent_rows = cur.fetchall()

        cur.execute("""
            SELECT COUNT(*), COALESCE(SUM(total_distance),0)
            FROM training_logs
            WHERE customer_id = %s
              AND log_date >= date_trunc('month', CURRENT_DATE)
        """, (cid,))
        month_count, month_distance = cur.fetchone()
        cur.close(); conn.close()

        if not recent_rows:
            return ""

        lines = [
            f"- {d.isoformat()} {stroke} {dist}m {dur}분 (강도:{intensity or '-'})"
            for d, stroke, dist, dur, intensity in recent_rows
        ]
        stroke_counts: dict = {}
        for _, stroke, *_ in recent_rows:
            stroke_counts[stroke] = stroke_counts.get(stroke, 0) + 1
        main_stroke = max(stroke_counts, key=stroke_counts.get) if stroke_counts else "정보 없음"

        return (
            "\n\n[참고: 이 사용자의 최근 훈련 일지 데이터입니다 — 사용자가 본인의 기록, 페이스, "
            "진행 상황, 맞춤 추천을 물으면 이 데이터를 적극 활용해 구체적으로 답변하세요. "
            "이 데이터와 무관한 일반적인 질문에는 굳이 언급하지 마세요.]\n"
            f"이번 달 누적: {month_count}회, {month_distance}m\n"
            f"최근 주력 영법: {main_stroke}\n"
            "최근 훈련 기록(최신순):\n" + "\n".join(lines)
        )
    except Exception:
        return ""

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

    MODEL_FALLBACKS = ["gemini-3.1-flash-lite", "gemini-2.5-flash-lite", "gemini-2.5-flash", "gemini-3-flash-preview"]
    reply = None
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

        training_summary = _get_training_summary(username)
        system_instruction = SYSTEM_PROMPT_BASE + training_summary

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
