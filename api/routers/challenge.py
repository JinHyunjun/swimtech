# -*- coding: utf-8 -*-
import os
from datetime import date
from typing import Optional

import psycopg2
from fastapi import APIRouter, HTTPException, Request

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
