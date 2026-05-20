# -*- coding: utf-8 -*-
import os
from datetime import date, timedelta
from fastapi import APIRouter, HTTPException, Cookie
import psycopg2
from routers.auth import verify_token, decode_token

router = APIRouter()
DATABASE_URL = os.getenv("DATABASE_URL", "")

BADGES = {
    "first_analysis": {
        "id": "first_analysis",
        "name": "첫 발걸음",
        "emoji": "🏊",
        "description": "첫 번째 수영 분석 완료",
        "condition_label": "분석 1회 완료",
    },
    "ten_analyses": {
        "id": "ten_analyses",
        "name": "꾸준한 수영러",
        "emoji": "🔟",
        "description": "10회 분석 달성",
        "condition_label": "분석 10회 완료",
    },
    "score_70": {
        "id": "score_70",
        "name": "실력자",
        "emoji": "⭐",
        "description": "종합점수 70점 이상 달성",
        "condition_label": "종합점수 70점 달성",
    },
    "score_90": {
        "id": "score_90",
        "name": "수영 고수",
        "emoji": "🏆",
        "description": "종합점수 90점 이상 달성",
        "condition_label": "종합점수 90점 달성",
    },
    "score_up_10": {
        "id": "score_up_10",
        "name": "성장하는 중",
        "emoji": "📈",
        "description": "점수 10점 이상 향상",
        "condition_label": "점수 10점 이상 향상",
    },
    "all_strokes": {
        "id": "all_strokes",
        "name": "4영법 마스터",
        "emoji": "🌊",
        "description": "4가지 영법 모두 분석",
        "condition_label": "4영법 모두 분석",
    },
    "streak_7": {
        "id": "streak_7",
        "name": "7일 연속",
        "emoji": "🔥",
        "description": "7일 연속 분석",
        "condition_label": "7일 연속 분석",
    },
    "share": {
        "id": "share",
        "name": "공유왕",
        "emoji": "📤",
        "description": "분석 결과 공유하기",
        "condition_label": "분석 결과 1회 공유",
    },
}


def get_db():
    return psycopg2.connect(DATABASE_URL)


def _require_auth(swimtech_token: str | None):
    if not swimtech_token or not verify_token(swimtech_token):
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")


def _calc_stats(customer_id):
    conn = get_db()
    cur = conn.cursor()
    if customer_id is not None:
        cur.execute("""
            SELECT overall_score, stroke_type, analyzed_at, share_token
            FROM analysis_results
            WHERE customer_id = %s
            ORDER BY analyzed_at ASC
        """, (customer_id,))
    else:
        cur.execute("""
            SELECT overall_score, stroke_type, analyzed_at, share_token
            FROM analysis_results
            ORDER BY analyzed_at ASC
        """)
    rows = cur.fetchall()
    cur.close()
    conn.close()

    if not rows:
        return {"total_analyses": 0, "best_score": 0, "score_improvement": 0,
                "unique_strokes": 0, "streak_days": 0, "has_shared": 0}

    scores = [float(r[0]) for r in rows if r[0] is not None]
    strokes = {r[1] for r in rows if r[1]}
    has_shared = sum(1 for r in rows if r[3])

    raw_dates = []
    for r in rows:
        if r[2]:
            d = r[2].date() if hasattr(r[2], "date") else date.fromisoformat(str(r[2])[:10])
            raw_dates.append(d)
    date_set = set(raw_dates)

    streak = 0
    today = date.today()
    current = today if today in date_set else (today - timedelta(days=1) if (today - timedelta(days=1)) in date_set else None)
    if current:
        while current in date_set:
            streak += 1
            current -= timedelta(days=1)

    best_score = max(scores) if scores else 0
    first_score = scores[0] if scores else 0
    improvement = round(best_score - first_score, 1)

    return {
        "total_analyses": len(rows),
        "best_score": best_score,
        "score_improvement": improvement,
        "unique_strokes": len(strokes),
        "streak_days": streak,
        "has_shared": has_shared,
    }


def _is_earned(badge_id: str, stats: dict) -> bool:
    checks = {
        "first_analysis": stats["total_analyses"] >= 1,
        "ten_analyses":   stats["total_analyses"] >= 10,
        "score_70":       stats["best_score"] >= 70,
        "score_90":       stats["best_score"] >= 90,
        "score_up_10":    stats["score_improvement"] >= 10,
        "all_strokes":    stats["unique_strokes"] >= 4,
        "streak_7":       stats["streak_days"] >= 7,
        "share":          stats["has_shared"] >= 1,
    }
    return checks.get(badge_id, False)


def _progress(badge_id: str, stats: dict) -> dict:
    mapping = {
        "first_analysis": (stats["total_analyses"], 1),
        "ten_analyses":   (stats["total_analyses"], 10),
        "score_70":       (stats["best_score"], 70),
        "score_90":       (stats["best_score"], 90),
        "score_up_10":    (stats["score_improvement"], 10),
        "all_strokes":    (stats["unique_strokes"], 4),
        "streak_7":       (stats["streak_days"], 7),
        "share":          (stats["has_shared"], 1),
    }
    current, target = mapping.get(badge_id, (0, 1))
    pct = min(100, round(current / target * 100)) if target else 0
    return {"current": current, "target": target, "percent": pct}


@router.get("")
def get_badges(swimtech_token: str = Cookie(default=None)):
    _require_auth(swimtech_token)
    payload = decode_token(swimtech_token) if swimtech_token else {}
    customer_id = payload.get("customer_id")
    try:
        stats = _calc_stats(customer_id)
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
