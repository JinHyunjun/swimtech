# -*- coding: utf-8 -*-
import os
from datetime import date
from typing import Optional

import psycopg2
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from routers.auth import verify_token

router = APIRouter()
DATABASE_URL = os.getenv("DATABASE_URL", "")

_SEED = [
    {
        "title": "5월 100km 챌린지",
        "description": "5월 한 달 동안 총 100km를 달성하세요! 매일 꾸준히 수영하면 충분히 달성할 수 있습니다.",
        "goal_distance": 100_000,
        "challenge_type": "distance",
        "start_date": "2026-05-01",
        "end_date": "2026-05-31",
    },
    {
        "title": "영법 마스터 챌린지",
        "description": "자유형·배영·평영·접영 4가지 영법을 각 10km씩, 총 40km를 완주하세요!",
        "goal_distance": 40_000,
        "challenge_type": "distance",
        "start_date": "2026-05-01",
        "end_date": "2026-06-30",
    },
    {
        "title": "30일 연속 수영 챌린지",
        "description": "30일 동안 하루도 빠지지 않고 수영하세요. 꾸준함이 실력을 만들어 줍니다!",
        "goal_distance": 30,
        "challenge_type": "streak",
        "start_date": "2026-05-01",
        "end_date": "2026-06-30",
    },
]


class ChallengeCreate(BaseModel):
    title: str
    description: str = ""
    challenge_type: str = "distance"   # distance | streak
    goal_distance: int                 # distance=미터, streak=일수
    start_date: str                    # YYYY-MM-DD
    end_date: str


def _get_db():
    return psycopg2.connect(DATABASE_URL)


def _ensure_tables():
    conn = _get_db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS challenges (
            id             SERIAL PRIMARY KEY,
            title          VARCHAR(200) NOT NULL UNIQUE,
            description    TEXT,
            goal_distance  INTEGER NOT NULL DEFAULT 0,
            challenge_type VARCHAR(20) NOT NULL DEFAULT 'distance',
            start_date     DATE NOT NULL,
            end_date       DATE NOT NULL,
            created_at     TIMESTAMP DEFAULT NOW()
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS challenge_participants (
            id               SERIAL PRIMARY KEY,
            challenge_id     INTEGER NOT NULL REFERENCES challenges(id) ON DELETE CASCADE,
            username         VARCHAR(100) NOT NULL,
            current_distance INTEGER NOT NULL DEFAULT 0,
            joined_at        TIMESTAMP DEFAULT NOW(),
            UNIQUE (challenge_id, username)
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_chall_part_cid  ON challenge_participants(challenge_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_chall_part_user ON challenge_participants(username)")
    cur.execute("ALTER TABLE challenges ADD COLUMN IF NOT EXISTS created_by VARCHAR(100)")
    conn.commit()
    for ch in _SEED:
        cur.execute("""
            INSERT INTO challenges (title, description, goal_distance, challenge_type, start_date, end_date)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (title) DO NOTHING
        """, (ch["title"], ch["description"], ch["goal_distance"], ch["challenge_type"],
              ch["start_date"], ch["end_date"]))
    conn.commit()
    cur.close()
    conn.close()


def _get_username(request: Request) -> Optional[str]:
    token = request.cookies.get("swimtech_token")
    if not token:
        return None
    return verify_token(token)


@router.post("")
def create_challenge(payload: ChallengeCreate, request: Request):
    """사용자가 직접 챌린지를 생성. 생성자는 자동 참여 처리."""
    username = _get_username(request)
    if not username:
        raise HTTPException(401, "로그인이 필요합니다")
    title = (payload.title or "").strip()
    desc = (payload.description or "").strip()
    ctype = payload.challenge_type if payload.challenge_type in ("distance", "streak") else "distance"
    if not title:
        raise HTTPException(400, "제목을 입력하세요")
    if len(title) > 200:
        raise HTTPException(400, "제목이 너무 깁니다 (최대 200자)")
    if len(desc) > 1000:
        raise HTTPException(400, "설명이 너무 깁니다 (최대 1000자)")
    if payload.goal_distance is None or payload.goal_distance <= 0:
        raise HTTPException(400, "목표값은 0보다 커야 합니다")
    if ctype == "distance" and payload.goal_distance > 10_000_000:
        raise HTTPException(400, "거리 목표가 너무 큽니다 (최대 10,000km)")
    if ctype == "streak" and payload.goal_distance > 365:
        raise HTTPException(400, "연속 일수가 너무 큽니다 (최대 365일)")
    try:
        sd = date.fromisoformat(payload.start_date)
        ed = date.fromisoformat(payload.end_date)
    except Exception:
        raise HTTPException(400, "날짜 형식이 올바르지 않습니다 (YYYY-MM-DD)")
    if ed < sd:
        raise HTTPException(400, "종료일이 시작일보다 빠릅니다")
    if ed < date.today():
        raise HTTPException(400, "종료일이 이미 지났습니다")
    _ensure_tables()
    conn = _get_db()
    cur = conn.cursor()
    try:
        cur.execute("SELECT 1 FROM challenges WHERE title = %s", (title,))
        if cur.fetchone():
            raise HTTPException(409, "같은 제목의 챌린지가 이미 있어요")
        cur.execute("""
            INSERT INTO challenges (title, description, goal_distance, challenge_type, start_date, end_date, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id
        """, (title, desc, payload.goal_distance, ctype, sd, ed, username))
        new_id = cur.fetchone()[0]
        cur.execute("""
            INSERT INTO challenge_participants (challenge_id, username)
            VALUES (%s, %s) ON CONFLICT (challenge_id, username) DO NOTHING
        """, (new_id, username))
        conn.commit()
        return {"status": "created", "id": new_id}
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(500, f"생성 오류: {e}")
    finally:
        cur.close()
        conn.close()


@router.delete("/{challenge_id}")
def delete_own_challenge(challenge_id: int, request: Request):
    """생성자 본인만 자신이 만든 챌린지를 삭제."""
    username = _get_username(request)
    if not username:
        raise HTTPException(401, "로그인이 필요합니다")
    _ensure_tables()
    conn = _get_db()
    cur = conn.cursor()
    try:
        cur.execute("SELECT created_by FROM challenges WHERE id = %s", (challenge_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "챌린지를 찾을 수 없습니다")
        if not row[0] or row[0] != username:
            raise HTTPException(403, "내가 만든 챌린지만 삭제할 수 있어요")
        cur.execute("DELETE FROM challenges WHERE id = %s", (challenge_id,))
        conn.commit()
        return {"status": "deleted"}
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(500, f"삭제 오류: {e}")
    finally:
        cur.close()
        conn.close()


@router.get("")
def list_challenges(request: Request):
    try:
        _ensure_tables()
        username = _get_username(request) or ""
        today = date.today()
        conn = _get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT c.id, c.title, c.description, c.goal_distance, c.challenge_type,
                   c.start_date, c.end_date,
                   COUNT(p.id) AS participant_count,
                   COALESCE(MAX(CASE WHEN p.username = %s THEN p.current_distance END), -1) AS my_dist
            FROM challenges c
            LEFT JOIN challenge_participants p ON p.challenge_id = c.id
            WHERE c.end_date >= %s
            GROUP BY c.id
            ORDER BY c.start_date DESC
        """, (username, today))
        rows = cur.fetchall()
        cur.close()
        conn.close()

        result = []
        for r in rows:
            ch_id, title, desc, goal, ch_type, start_d, end_d, pcount, my_dist = r
            joined = (my_dist is not None and my_dist >= 0)
            cur_dist = max(0, my_dist) if joined else 0
            achievement = round(cur_dist / goal * 100, 1) if goal > 0 and joined else 0
            result.append({
                "id": ch_id,
                "title": title,
                "description": desc,
                "goal_distance": goal,
                "challenge_type": ch_type,
                "start_date": str(start_d),
                "end_date": str(end_d),
                "days_left": max(0, (end_d - today).days),
                "participant_count": pcount,
                "joined": joined,
                "my_distance": cur_dist,
                "achievement_pct": min(100.0, achievement),
            })
        return {"challenges": result}
    except Exception as e:
        raise HTTPException(500, f"DB 오류: {e}")


@router.get("/my")
def my_challenges(request: Request):
    username = _get_username(request)
    if not username:
        raise HTTPException(401, "로그인이 필요합니다")
    try:
        _ensure_tables()
        today = date.today()
        conn = _get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT c.id, c.title, c.goal_distance, c.challenge_type,
                   c.start_date, c.end_date, p.current_distance, p.joined_at
            FROM challenge_participants p
            JOIN challenges c ON c.id = p.challenge_id
            WHERE p.username = %s
            ORDER BY p.joined_at DESC
        """, (username,))
        rows = cur.fetchall()
        cur.close()
        conn.close()
        result = []
        for r in rows:
            ch_id, title, goal, ch_type, start_d, end_d, my_dist, joined_at = r
            achievement = round(my_dist / goal * 100, 1) if goal > 0 else 0
            result.append({
                "id": ch_id,
                "title": title,
                "goal_distance": goal,
                "challenge_type": ch_type,
                "start_date": str(start_d),
                "end_date": str(end_d),
                "days_left": max(0, (end_d - today).days),
                "my_distance": my_dist,
                "achievement_pct": min(100.0, achievement),
                "joined_at": str(joined_at),
            })
        return {"challenges": result}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"DB 오류: {e}")


@router.post("/{challenge_id}/join")
def join_challenge(challenge_id: int, request: Request):
    username = _get_username(request)
    if not username:
        raise HTTPException(401, "로그인이 필요합니다")
    try:
        _ensure_tables()
        conn = _get_db()
        cur = conn.cursor()
        cur.execute("SELECT id, end_date FROM challenges WHERE id = %s", (challenge_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "챌린지를 찾을 수 없습니다")
        if row[1] < date.today():
            raise HTTPException(400, "종료된 챌린지입니다")
        cur.execute("""
            INSERT INTO challenge_participants (challenge_id, username)
            VALUES (%s, %s)
            ON CONFLICT (challenge_id, username) DO NOTHING
        """, (challenge_id, username))
        inserted = cur.rowcount
        conn.commit()
        cur.close()
        conn.close()
        return {"status": "already_joined" if inserted == 0 else "joined"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"참여 처리 오류: {e}")


@router.get("/{challenge_id}/ranking")
def get_ranking(challenge_id: int):
    try:
        _ensure_tables()
        conn = _get_db()
        cur = conn.cursor()
        cur.execute("SELECT id, goal_distance FROM challenges WHERE id = %s", (challenge_id,))
        ch = cur.fetchone()
        if not ch:
            raise HTTPException(404, "챌린지를 찾을 수 없습니다")
        goal = ch[1]
        cur.execute("""
            SELECT username, current_distance, joined_at
            FROM challenge_participants
            WHERE challenge_id = %s
            ORDER BY current_distance DESC
            LIMIT 50
        """, (challenge_id,))
        rows = cur.fetchall()
        cur.close()
        conn.close()
        ranking = []
        for i, (uname, dist, joined_at) in enumerate(rows, 1):
            achievement = round(dist / goal * 100, 1) if goal > 0 else 0
            ranking.append({
                "rank": i,
                "username": uname,
                "distance": dist,
                "achievement_pct": min(100.0, achievement),
                "joined_at": str(joined_at),
            })
        return {"challenge_id": challenge_id, "goal_distance": goal, "ranking": ranking}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"랭킹 조회 오류: {e}")


@router.delete("/{challenge_id}/leave")
def leave_challenge(challenge_id: int, request: Request):
    username = _get_username(request)
    if not username:
        raise HTTPException(401, "로그인이 필요합니다")
    try:
        _ensure_tables()
        conn = _get_db()
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM challenge_participants WHERE challenge_id = %s AND username = %s",
            (challenge_id, username),
        )
        deleted = cur.rowcount
        conn.commit()
        cur.close()
        conn.close()
        if deleted == 0:
            raise HTTPException(404, "참여 기록을 찾을 수 없습니다")
        return {"status": "left"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"포기 처리 오류: {e}")


def update_challenge_progress(username: str, distance_m: int):
    """훈련 일지 저장 시 참여 중인 distance형 챌린지 거리 자동 반영."""
    if not username or username == "guest" or distance_m <= 0:
        return
    try:
        today = date.today()
        conn = _get_db()
        cur = conn.cursor()
        cur.execute("""
            UPDATE challenge_participants cp
            SET current_distance = current_distance + %s
            FROM challenges c
            WHERE cp.challenge_id = c.id
              AND cp.username = %s
              AND c.challenge_type = 'distance'
              AND c.start_date <= %s
              AND c.end_date >= %s
        """, (distance_m, username, today, today))
        conn.commit()
        cur.close()
        conn.close()
    except Exception:
        pass
