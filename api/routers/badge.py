# -*- coding: utf-8 -*-
import os
from datetime import date, timedelta
from fastapi import APIRouter, HTTPException, Cookie
import psycopg2
from routers.auth import verify_token, decode_token

router = APIRouter()
DATABASE_URL = os.getenv("DATABASE_URL", "")

BADGES = {
    # ── 훈련 일지 기반 뱃지 ──
    "first_log": {
        "id": "first_log",
        "name": "첫 훈련 기록",
        "emoji": "📝",
        "description": "첫 번째 훈련 일지 작성",
        "condition_label": "훈련 일지 1회 작성",
    },
    "log_dist_1km": {
        "id": "log_dist_1km",
        "name": "1km 달성",
        "emoji": "🎯",
        "description": "훈련 누적 거리 1km 달성",
        "condition_label": "누적 거리 1km",
    },
    "log_dist_10km": {
        "id": "log_dist_10km",
        "name": "10km 돌파",
        "emoji": "🚀",
        "description": "훈련 누적 거리 10km 달성",
        "condition_label": "누적 거리 10km",
    },
    "log_dist_50km": {
        "id": "log_dist_50km",
        "name": "50km 철인",
        "emoji": "💪",
        "description": "훈련 누적 거리 50km 달성",
        "condition_label": "누적 거리 50km",
    },
    "log_dist_100km": {
        "id": "log_dist_100km",
        "name": "100km 레전드",
        "emoji": "🏅",
        "description": "훈련 누적 거리 100km 달성",
        "condition_label": "누적 거리 100km",
    },
    "log_streak_3": {
        "id": "log_streak_3",
        "name": "3일 연속 출석",
        "emoji": "📅",
        "description": "3일 연속 훈련 일지 기록",
        "condition_label": "3일 연속 기록",
    },
    "log_streak_7": {
        "id": "log_streak_7",
        "name": "1주 개근",
        "emoji": "🔥",
        "description": "7일 연속 훈련 일지 기록",
        "condition_label": "7일 연속 기록",
    },
    "log_streak_30": {
        "id": "log_streak_30",
        "name": "한달 개근",
        "emoji": "🌟",
        "description": "30일 연속 훈련 일지 기록",
        "condition_label": "30일 연속 기록",
    },
    "log_stroke_master": {
        "id": "log_stroke_master",
        "name": "4영법 훈련 완료",
        "emoji": "🌊",
        "description": "4가지 영법 모두 훈련 기록",
        "condition_label": "4영법 훈련 기록",
    },
    # ── 플랜 활용 뱃지 ──
    "plan_creator": {
        "id": "plan_creator",
        "name": "플랜 설계자",
        "emoji": "🛠",
        "description": "나만의 훈련 플랜 처음 생성",
        "condition_label": "플랜 1개 생성",
    },
    "plan_collector": {
        "id": "plan_collector",
        "name": "플랜 컬렉터",
        "emoji": "🗂",
        "description": "나만의 훈련 플랜 5개 생성",
        "condition_label": "플랜 5개 생성",
    },
    "fav_collector": {
        "id": "fav_collector",
        "name": "즐겨찾기 마니아",
        "emoji": "💛",
        "description": "플랜 3개 이상 즐겨찾기",
        "condition_label": "즐겨찾기 3개",
    },
    # ── 챌린지 뱃지 ──
    "challenge_joiner": {
        "id": "challenge_joiner",
        "name": "챌린지 입문",
        "emoji": "🚩",
        "description": "챌린지 첫 참여",
        "condition_label": "챌린지 1개 참여",
    },
    "challenge_finisher": {
        "id": "challenge_finisher",
        "name": "챌린지 완주자",
        "emoji": "🏁",
        "description": "참여한 챌린지 목표 거리 달성",
        "condition_label": "챌린지 목표 달성",
    },
    # ── 훈련 습관 뱃지 ──
    "early_bird": {
        "id": "early_bird",
        "name": "얼리버드",
        "emoji": "🌅",
        "description": "오전 7시 이전 훈련 기록 3회",
        "condition_label": "아침 7시 전 기록 3회",
    },
    "long_session": {
        "id": "long_session",
        "name": "장거리 입문",
        "emoji": "🏊‍♂️",
        "description": "한 번에 3,000m 이상 훈련",
        "condition_label": "단일 훈련 3,000m 이상",
    },
}


_STROKE_KEYWORDS = {
    "자유형": ["자유형", "freestyle", "free"],
    "배영": ["배영", "backstroke", "back"],
    "평영": ["평영", "breaststroke", "breast"],
    "접영": ["접영", "butterfly", "fly"],
}


def get_db():
    return psycopg2.connect(DATABASE_URL)


def _require_auth(swimtech_token: str | None):
    if not swimtech_token or not verify_token(swimtech_token):
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")


def _calc_log_stats(username: str) -> dict:
    empty = {"total_logs": 0, "total_dist_m": 0, "log_streak": 0, "unique_strokes": 0,
              "max_single_dist": 0, "early_bird_count": 0}
    if not username:
        return empty
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT id FROM customers WHERE username = %s", (username,))
        crow = cur.fetchone()
        if not crow:
            cur.close(); conn.close()
            return empty
        cid = crow[0]
        cur.execute("""
            SELECT log_date, total_distance, stroke_type, created_at
            FROM training_logs
            WHERE customer_id = %s
            ORDER BY log_date ASC
        """, (cid,))
        rows = cur.fetchall()
        cur.close()
        conn.close()
    except Exception:
        return empty

    if not rows:
        return empty

    total_dist = sum(int(r[1] or 0) for r in rows)
    date_set = set(r[0] for r in rows)
    max_single_dist = max(int(r[1] or 0) for r in rows)
    early_bird_count = 0
    for r in rows:
        ts = r[3]
        if ts is not None:
            try:
                if ts.hour < 7:
                    early_bird_count += 1
            except Exception:
                pass

    streak = 0
    today = date.today()
    current = today if today in date_set else (today - timedelta(days=1) if (today - timedelta(days=1)) in date_set else None)
    if current:
        while current in date_set:
            streak += 1
            current -= timedelta(days=1)

    found_strokes = set((r[2] or "").strip() for r in rows if (r[2] or "").strip())

    return {
        "total_logs": len(rows),
        "total_dist_m": total_dist,
        "log_streak": streak,
        "unique_strokes": len(found_strokes),
        "max_single_dist": max_single_dist,
        "early_bird_count": early_bird_count,
    }


def _calc_plan_challenge_stats(username: str) -> dict:
    """플랜 생성/즐겨찾기/챌린지 참여 현황 (뱃지용). 실패해도 전체 뱃지 조회가 죽지 않도록 항상 dict 반환."""
    empty = {"plan_count": 0, "fav_count": 0, "challenge_joined": 0, "challenge_finished": False}
    if not username:
        return empty
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM custom_plans WHERE username = %s", (username,))
        plan_count = cur.fetchone()[0]

        fav_count = 0
        try:
            cur.execute("SELECT COUNT(*) FROM plan_favorites pf JOIN custom_plans cp ON cp.id = pf.plan_id WHERE pf.username = %s", (username,))
            fav_count += cur.fetchone()[0]
        except Exception:
            pass
        try:
            cur.execute("SELECT COUNT(*) FROM preset_plan_favorites WHERE username = %s", (username,))
            fav_count += cur.fetchone()[0]
        except Exception:
            pass

        challenge_joined = 0
        challenge_finished = False
        try:
            cur.execute("""
                SELECT cp.current_distance, c.goal_distance
                FROM challenge_participants cp
                JOIN challenges c ON c.id = cp.challenge_id
                WHERE cp.username = %s
            """, (username,))
            crows = cur.fetchall()
            challenge_joined = len(crows)
            challenge_finished = any(
                (r[1] or 0) > 0 and (r[0] or 0) >= r[1] for r in crows
            )
        except Exception:
            pass

        cur.close(); conn.close()
        return {
            "plan_count": plan_count,
            "fav_count": fav_count,
            "challenge_joined": challenge_joined,
            "challenge_finished": challenge_finished,
        }
    except Exception:
        return empty

def _is_earned(badge_id: str, stats: dict) -> bool:
    ls = stats.get("log_stats", {})
    pc = stats.get("plan_stats", {})
    checks = {
        "first_log":       ls.get("total_logs", 0) >= 1,
        "log_dist_1km":    ls.get("total_dist_m", 0) >= 1_000,
        "log_dist_10km":   ls.get("total_dist_m", 0) >= 10_000,
        "log_dist_50km":   ls.get("total_dist_m", 0) >= 50_000,
        "log_dist_100km":  ls.get("total_dist_m", 0) >= 100_000,
        "log_streak_3":    ls.get("log_streak", 0) >= 3,
        "log_streak_7":    ls.get("log_streak", 0) >= 7,
        "log_streak_30":   ls.get("log_streak", 0) >= 30,
        "log_stroke_master": ls.get("unique_strokes", 0) >= 4,
        "plan_creator":      pc.get("plan_count", 0) >= 1,
        "plan_collector":    pc.get("plan_count", 0) >= 5,
        "fav_collector":     pc.get("fav_count", 0) >= 3,
        "challenge_joiner":  pc.get("challenge_joined", 0) >= 1,
        "challenge_finisher": pc.get("challenge_finished", False),
        "early_bird":        ls.get("early_bird_count", 0) >= 3,
        "long_session":      ls.get("max_single_dist", 0) >= 3_000,
    }
    return checks.get(badge_id, False)


def _progress(badge_id: str, stats: dict) -> dict:
    ls = stats.get("log_stats", {})
    pc = stats.get("plan_stats", {})
    mapping = {
        "first_log":       (ls.get("total_logs", 0), 1),
        "log_dist_1km":    (ls.get("total_dist_m", 0) // 1000, 1),
        "log_dist_10km":   (ls.get("total_dist_m", 0) // 1000, 10),
        "log_dist_50km":   (ls.get("total_dist_m", 0) // 1000, 50),
        "log_dist_100km":  (ls.get("total_dist_m", 0) // 1000, 100),
        "log_streak_3":    (ls.get("log_streak", 0), 3),
        "log_streak_7":    (ls.get("log_streak", 0), 7),
        "log_streak_30":   (ls.get("log_streak", 0), 30),
        "log_stroke_master": (ls.get("unique_strokes", 0), 4),
        "plan_creator":      (pc.get("plan_count", 0), 1),
        "plan_collector":    (pc.get("plan_count", 0), 5),
        "fav_collector":     (pc.get("fav_count", 0), 3),
        "challenge_joiner":  (pc.get("challenge_joined", 0), 1),
        "challenge_finisher": (1 if pc.get("challenge_finished") else 0, 1),
        "early_bird":        (ls.get("early_bird_count", 0), 3),
        "long_session":      (ls.get("max_single_dist", 0), 3_000),
    }
    current, target = mapping.get(badge_id, (0, 1))
    pct = min(100, round(current / target * 100)) if target else 0
    return {"current": current, "target": target, "percent": pct}


@router.get("")
def get_badges(swimtech_token: str = Cookie(default=None)):
    _require_auth(swimtech_token)
    payload = decode_token(swimtech_token) if swimtech_token else {}
    customer_id = payload.get("customer_id")
    username = payload.get("sub", "")
    try:
        stats = {"log_stats": _calc_log_stats(username)}
        stats["plan_stats"] = _calc_plan_challenge_stats(username)
        badges = []
        for badge_id, meta in BADGES.items():
            earned = _is_earned(badge_id, stats)
            badges.append({
                **meta,
                "earned": earned,
                "progress": _progress(badge_id, stats),
            })
        earned_count = sum(1 for b in badges if b["earned"])
        return {"badges": badges, "earned_count": earned_count, "total_count": len(badges), "stats": stats}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"DB 오류: {e}")


def check_badges_on_log(username: str) -> list:
    """훈련 일지 저장 후 새로 획득한 로그 기반 뱃지 목록을 반환."""
    if not username or username == "guest":
        return []
    try:
        ls = _calc_log_stats(username)
        stats = {"total_analyses": 0, "best_score": 0, "score_improvement": 0,
                 "unique_strokes": 0, "streak_days": 0, "has_shared": 0,
                 "log_stats": ls}
        log_badge_ids = [
            "first_log", "log_dist_1km", "log_dist_10km", "log_dist_50km", "log_dist_100km",
            "log_streak_3", "log_streak_7", "log_streak_30", "log_stroke_master",
        ]
        return [bid for bid in log_badge_ids if _is_earned(bid, stats)]
    except Exception:
        return []
