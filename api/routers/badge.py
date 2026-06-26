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
    "log_dist_250km": {
        "id": "log_dist_250km",
        "name": "250km 원정대",
        "emoji": "🧭",
        "description": "훈련 누적 거리 250km 달성",
        "condition_label": "누적 거리 250km",
    },
    "log_dist_500km": {
        "id": "log_dist_500km",
        "name": "500km 항해자",
        "emoji": "🚢",
        "description": "훈련 누적 거리 500km 달성",
        "condition_label": "누적 거리 500km",
    },
    "log_count_5": {
        "id": "log_count_5",
        "name": "루틴 시작",
        "emoji": "✅",
        "description": "훈련 일지 5회 작성",
        "condition_label": "훈련 일지 5회",
    },
    "log_count_20": {
        "id": "log_count_20",
        "name": "습관 빌더",
        "emoji": "🧱",
        "description": "훈련 일지 20회 작성",
        "condition_label": "훈련 일지 20회",
    },
    "log_count_50": {
        "id": "log_count_50",
        "name": "훈련 생활자",
        "emoji": "📘",
        "description": "훈련 일지 50회 작성",
        "condition_label": "훈련 일지 50회",
    },
    "log_count_100": {
        "id": "log_count_100",
        "name": "기록 장인",
        "emoji": "🏛️",
        "description": "훈련 일지 100회 작성",
        "condition_label": "훈련 일지 100회",
    },
    "log_streak_14": {
        "id": "log_streak_14",
        "name": "2주 루틴",
        "emoji": "🗓️",
        "description": "14일 연속 훈련 일지 기록",
        "condition_label": "14일 연속 기록",
    },
    "log_streak_60": {
        "id": "log_streak_60",
        "name": "두 달 개근",
        "emoji": "💎",
        "description": "60일 연속 훈련 일지 기록",
        "condition_label": "60일 연속 기록",
    },
    "stroke_free": {
        "id": "stroke_free",
        "name": "자유형 스타터",
        "emoji": "🏊",
        "description": "자유형 훈련 기록",
        "condition_label": "자유형 1회 기록",
    },
    "stroke_back": {
        "id": "stroke_back",
        "name": "배영 스타터",
        "emoji": "↩️",
        "description": "배영 훈련 기록",
        "condition_label": "배영 1회 기록",
    },
    "stroke_breast": {
        "id": "stroke_breast",
        "name": "평영 스타터",
        "emoji": "🐸",
        "description": "평영 훈련 기록",
        "condition_label": "평영 1회 기록",
    },
    "stroke_fly": {
        "id": "stroke_fly",
        "name": "접영 스타터",
        "emoji": "🦋",
        "description": "접영 훈련 기록",
        "condition_label": "접영 1회 기록",
    },
    "pool_25": {
        "id": "pool_25",
        "name": "25m 적응",
        "emoji": "📏",
        "description": "25m 수영장에서 훈련 기록",
        "condition_label": "25m 풀 1회 기록",
    },
    "pool_50": {
        "id": "pool_50",
        "name": "50m 적응",
        "emoji": "🏟️",
        "description": "50m 수영장에서 훈련 기록",
        "condition_label": "50m 풀 1회 기록",
    },
    "pool_dual": {
        "id": "pool_dual",
        "name": "풀 전환러",
        "emoji": "🔁",
        "description": "25m와 50m 수영장 모두에서 훈련 기록",
        "condition_label": "25m/50m 풀 모두 기록",
    },
    "plan_runner_1": {
        "id": "plan_runner_1",
        "name": "플랜 실천 첫걸음",
        "emoji": "📌",
        "description": "훈련 플랜 세션 1회 완료 기록",
        "condition_label": "플랜 완료 세션 1회",
    },
    "plan_runner_5": {
        "id": "plan_runner_5",
        "name": "플랜 루틴러",
        "emoji": "🧩",
        "description": "훈련 플랜 세션 5회 완료 기록",
        "condition_label": "플랜 완료 세션 5회",
    },
    "plan_runner_12": {
        "id": "plan_runner_12",
        "name": "플랜 완주자",
        "emoji": "🏁",
        "description": "훈련 플랜 세션 12회 완료 기록",
        "condition_label": "플랜 완료 세션 12회",
    },
    "monthly_goal_set": {
        "id": "monthly_goal_set",
        "name": "목표 선언",
        "emoji": "🎯",
        "description": "이번 달 목표 거리 설정",
        "condition_label": "월간 목표 설정",
    },
    "monthly_goal_achiever": {
        "id": "monthly_goal_achiever",
        "name": "목표 달성자",
        "emoji": "🎉",
        "description": "이번 달 목표 거리 달성",
        "condition_label": "월간 목표 100% 달성",
    },
    "goal_achiever_3": {
        "id": "goal_achiever_3",
        "name": "목표 삼연속",
        "emoji": "🥉",
        "description": "월간 목표 달성 3회",
        "condition_label": "월간 목표 달성 3회",
    },
    "hard_worker": {
        "id": "hard_worker",
        "name": "하드 세션 러버",
        "emoji": "⚡",
        "description": "강도 '힘듦' 훈련 3회 기록",
        "condition_label": "힘듦 강도 3회",
    },
    "recovery_mindset": {
        "id": "recovery_mindset",
        "name": "회복도 실력",
        "emoji": "🌿",
        "description": "강도 '쉬움' 훈련 3회 기록",
        "condition_label": "쉬움 강도 3회",
    },
    "fins_try": {
        "id": "fins_try",
        "name": "오리발 적응",
        "emoji": "🦶",
        "description": "오리발 사용 훈련 기록",
        "condition_label": "오리발 훈련 1회",
    },
    "mega_session": {
        "id": "mega_session",
        "name": "5km 세션",
        "emoji": "🐋",
        "description": "한 번에 5,000m 이상 훈련",
        "condition_label": "단일 훈련 5,000m 이상",
    },
}

BADGE_SERIES = {
    "distance": {
        "label": "누적 거리 로드",
        "description": "1km부터 장거리 항해까지, 꾸준히 쌓는 거리 여정",
        "badge_ids": ["first_log", "log_dist_1km", "log_dist_10km", "log_dist_50km", "log_dist_100km", "log_dist_250km", "log_dist_500km"],
    },
    "log_count": {
        "label": "기록 습관 로드",
        "description": "훈련을 남기는 습관 자체를 키우는 단계",
        "badge_ids": ["log_count_5", "log_count_20", "log_count_50", "log_count_100"],
    },
    "streak": {
        "label": "연속 출석 로드",
        "description": "연속 기록으로 루틴을 만드는 단계",
        "badge_ids": ["log_streak_3", "log_streak_7", "log_streak_14", "log_streak_30", "log_streak_60"],
    },
    "stroke": {
        "label": "영법 탐험 로드",
        "description": "자유형부터 4영법 마스터까지 확장",
        "badge_ids": ["stroke_free", "stroke_back", "stroke_breast", "stroke_fly", "log_stroke_master"],
    },
    "plan": {
        "label": "훈련 플랜 로드",
        "description": "플랜을 만들고 실제 세션으로 이어가는 단계",
        "badge_ids": ["plan_creator", "plan_collector", "fav_collector", "plan_runner_1", "plan_runner_5", "plan_runner_12"],
    },
    "goal": {
        "label": "월간 목표 로드",
        "description": "목표 설정에서 반복 달성까지 이어지는 단계",
        "badge_ids": ["monthly_goal_set", "monthly_goal_achiever", "goal_achiever_3"],
    },
    "pool": {
        "label": "수영장 적응 로드",
        "description": "25m와 50m 환경 차이를 경험하는 단계",
        "badge_ids": ["pool_25", "pool_50", "pool_dual"],
    },
    "session": {
        "label": "세션 캐릭터 로드",
        "description": "강도, 회복, 장거리, 장비 사용 경험을 넓히는 단계",
        "badge_ids": ["early_bird", "recovery_mindset", "hard_worker", "fins_try", "long_session", "mega_session"],
    },
    "challenge": {
        "label": "챌린지 로드",
        "description": "혼자 하는 기록을 함께 하는 목표로 확장",
        "badge_ids": ["challenge_joiner", "challenge_finisher"],
    },
}

_SERIES_BY_BADGE = {}
for series_key, series in BADGE_SERIES.items():
    total_steps = len(series["badge_ids"])
    for idx, badge_id in enumerate(series["badge_ids"], start=1):
        if badge_id in BADGES:
            BADGES[badge_id].update({
                "series": series_key,
                "series_label": series["label"],
                "step": idx,
                "total_steps": total_steps,
            })
            _SERIES_BY_BADGE[badge_id] = series_key


_STROKE_KEYWORDS = {
    "자유형": ["자유형", "freestyle", "free"],
    "배영": ["배영", "backstroke", "back"],
    "평영": ["평영", "breaststroke", "breast"],
    "접영": ["접영", "butterfly", "fly"],
}


def get_db():
    return psycopg2.connect(DATABASE_URL)


def _table_exists(cur, table_name: str) -> bool:
    try:
        cur.execute("SELECT to_regclass(%s)", (f"public.{table_name}",))
        return bool(cur.fetchone()[0])
    except Exception:
        return False


def _require_auth(swimtech_token: str | None):
    if not swimtech_token or not verify_token(swimtech_token):
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")


def _calc_log_stats(username: str) -> dict:
    empty = {"total_logs": 0, "total_dist_m": 0, "log_streak": 0, "unique_strokes": 0,
              "max_single_dist": 0, "early_bird_count": 0, "stroke_flags": {},
              "pool_lengths": [], "hard_count": 0, "easy_count": 0, "used_fins_count": 0}
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
            SELECT log_date, total_distance, stroke_type, created_at,
                   COALESCE(pool_length, 25), COALESCE(intensity, ''), COALESCE(used_fins, FALSE)
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
    hard_count = 0
    easy_count = 0
    used_fins_count = 0
    pool_lengths = set()
    for r in rows:
        ts = r[3]
        if ts is not None:
            try:
                if ts.hour < 7:
                    early_bird_count += 1
            except Exception:
                pass
        try:
            pool_lengths.add(int(r[4] or 25))
        except Exception:
            pass
        intensity = (r[5] or "").strip()
        if intensity == "힘듦":
            hard_count += 1
        if intensity == "쉬움":
            easy_count += 1
        if bool(r[6]):
            used_fins_count += 1

    streak = 0
    today = date.today()
    current = today if today in date_set else (today - timedelta(days=1) if (today - timedelta(days=1)) in date_set else None)
    if current:
        while current in date_set:
            streak += 1
            current -= timedelta(days=1)

    found_strokes = set((r[2] or "").strip() for r in rows if (r[2] or "").strip())
    stroke_flags = {}
    for stroke, keywords in _STROKE_KEYWORDS.items():
        stroke_flags[stroke] = any(
            any(k.lower() in (raw or "").lower() for k in keywords)
            for raw in found_strokes
        )

    return {
        "total_logs": len(rows),
        "total_dist_m": total_dist,
        "log_streak": streak,
        "unique_strokes": sum(1 for ok in stroke_flags.values() if ok),
        "max_single_dist": max_single_dist,
        "early_bird_count": early_bird_count,
        "stroke_flags": stroke_flags,
        "pool_lengths": sorted(pool_lengths),
        "hard_count": hard_count,
        "easy_count": easy_count,
        "used_fins_count": used_fins_count,
    }


def _calc_plan_challenge_stats(username: str, customer_id: int | None = None) -> dict:
    """플랜 생성/즐겨찾기/챌린지 참여 현황 (뱃지용). 실패해도 전체 뱃지 조회가 죽지 않도록 항상 dict 반환."""
    empty = {"plan_count": 0, "fav_count": 0, "challenge_joined": 0, "challenge_finished": False,
             "plan_completed_sessions": 0}
    if not username:
        return empty
    try:
        conn = get_db()
        cur = conn.cursor()
        plan_count = 0
        if _table_exists(cur, "custom_plans"):
            cur.execute("SELECT COUNT(*) FROM custom_plans WHERE username = %s", (username,))
            plan_count = cur.fetchone()[0]

        fav_count = 0
        if _table_exists(cur, "plan_favorites") and _table_exists(cur, "custom_plans"):
            cur.execute("SELECT COUNT(*) FROM plan_favorites pf JOIN custom_plans cp ON cp.id = pf.plan_id WHERE pf.username = %s", (username,))
            fav_count += cur.fetchone()[0]
        if _table_exists(cur, "preset_plan_favorites"):
            cur.execute("SELECT COUNT(*) FROM preset_plan_favorites WHERE username = %s", (username,))
            fav_count += cur.fetchone()[0]

        plan_completed_sessions = 0
        if customer_id and _table_exists(cur, "plan_completions"):
            cur.execute("SELECT COUNT(*) FROM plan_completions WHERE customer_id = %s", (customer_id,))
            plan_completed_sessions = cur.fetchone()[0]

        challenge_joined = 0
        challenge_finished = False
        if _table_exists(cur, "challenge_participants") and _table_exists(cur, "challenges"):
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

        cur.close(); conn.close()
        return {
            "plan_count": plan_count,
            "fav_count": fav_count,
            "challenge_joined": challenge_joined,
            "challenge_finished": challenge_finished,
            "plan_completed_sessions": plan_completed_sessions,
        }
    except Exception:
        return empty


def _calc_goal_stats(customer_id: int | None) -> dict:
    empty = {"goal_set_this_month": False, "goal_distance": 0, "achieved_distance": 0,
             "goal_achieved_this_month": False, "achieved_goal_months": 0}
    if not customer_id:
        return empty
    try:
        conn = get_db()
        cur = conn.cursor()
        if not (_table_exists(cur, "training_goals") and _table_exists(cur, "training_logs")):
            cur.close(); conn.close()
            return empty
        today = date.today()
        cur.execute("""
            SELECT goal_distance
            FROM training_goals
            WHERE customer_id = %s AND year = %s AND month = %s
        """, (customer_id, today.year, today.month))
        row = cur.fetchone()
        goal = int(row[0] or 0) if row else 0
        cur.execute("""
            SELECT COALESCE(SUM(total_distance), 0)
            FROM training_logs
            WHERE customer_id = %s
              AND EXTRACT(YEAR FROM log_date) = %s
              AND EXTRACT(MONTH FROM log_date) = %s
        """, (customer_id, today.year, today.month))
        achieved = int(cur.fetchone()[0] or 0)
        cur.execute("""
            WITH monthly AS (
                SELECT EXTRACT(YEAR FROM log_date)::int AS y,
                       EXTRACT(MONTH FROM log_date)::int AS m,
                       COALESCE(SUM(total_distance), 0) AS achieved
                FROM training_logs
                WHERE customer_id = %s
                GROUP BY y, m
            )
            SELECT COUNT(*)
            FROM training_goals tg
            JOIN monthly m ON m.y = tg.year AND m.m = tg.month
            WHERE tg.customer_id = %s
              AND tg.goal_distance > 0
              AND m.achieved >= tg.goal_distance
        """, (customer_id, customer_id))
        achieved_goal_months = int(cur.fetchone()[0] or 0)
        cur.close(); conn.close()
        return {
            "goal_set_this_month": goal > 0,
            "goal_distance": goal,
            "achieved_distance": achieved,
            "goal_achieved_this_month": goal > 0 and achieved >= goal,
            "achieved_goal_months": achieved_goal_months,
        }
    except Exception:
        return empty

def _is_earned(badge_id: str, stats: dict) -> bool:
    return _progress(badge_id, stats).get("percent", 0) >= 100


def _progress(badge_id: str, stats: dict) -> dict:
    ls = stats.get("log_stats", {})
    pc = stats.get("plan_stats", {})
    gs = stats.get("goal_stats", {})
    stroke_flags = ls.get("stroke_flags") or {}
    pool_lengths = set(ls.get("pool_lengths") or [])
    total_km = round((ls.get("total_dist_m", 0) or 0) / 1000, 1)
    mapping = {
        "first_log":       (ls.get("total_logs", 0), 1, "회"),
        "log_count_5":     (ls.get("total_logs", 0), 5, "회"),
        "log_count_20":    (ls.get("total_logs", 0), 20, "회"),
        "log_count_50":    (ls.get("total_logs", 0), 50, "회"),
        "log_count_100":   (ls.get("total_logs", 0), 100, "회"),
        "log_dist_1km":    (total_km, 1, "km"),
        "log_dist_10km":   (total_km, 10, "km"),
        "log_dist_50km":   (total_km, 50, "km"),
        "log_dist_100km":  (total_km, 100, "km"),
        "log_dist_250km":  (total_km, 250, "km"),
        "log_dist_500km":  (total_km, 500, "km"),
        "log_streak_3":    (ls.get("log_streak", 0), 3, "일"),
        "log_streak_7":    (ls.get("log_streak", 0), 7, "일"),
        "log_streak_14":   (ls.get("log_streak", 0), 14, "일"),
        "log_streak_30":   (ls.get("log_streak", 0), 30, "일"),
        "log_streak_60":   (ls.get("log_streak", 0), 60, "일"),
        "stroke_free":     (1 if stroke_flags.get("자유형") else 0, 1, "회"),
        "stroke_back":     (1 if stroke_flags.get("배영") else 0, 1, "회"),
        "stroke_breast":   (1 if stroke_flags.get("평영") else 0, 1, "회"),
        "stroke_fly":      (1 if stroke_flags.get("접영") else 0, 1, "회"),
        "log_stroke_master": (ls.get("unique_strokes", 0), 4, "영법"),
        "pool_25":         (1 if 25 in pool_lengths else 0, 1, "회"),
        "pool_50":         (1 if 50 in pool_lengths else 0, 1, "회"),
        "pool_dual":       (len({25, 50}.intersection(pool_lengths)), 2, "종"),
        "plan_creator":      (pc.get("plan_count", 0), 1, "개"),
        "plan_collector":    (pc.get("plan_count", 0), 5, "개"),
        "fav_collector":     (pc.get("fav_count", 0), 3, "개"),
        "plan_runner_1":     (pc.get("plan_completed_sessions", 0), 1, "회"),
        "plan_runner_5":     (pc.get("plan_completed_sessions", 0), 5, "회"),
        "plan_runner_12":    (pc.get("plan_completed_sessions", 0), 12, "회"),
        "challenge_joiner":  (pc.get("challenge_joined", 0), 1, "개"),
        "challenge_finisher": (1 if pc.get("challenge_finished") else 0, 1, "회"),
        "monthly_goal_set":      (1 if gs.get("goal_set_this_month") else 0, 1, "회"),
        "monthly_goal_achiever": (min(gs.get("achieved_distance", 0), gs.get("goal_distance", 0)), gs.get("goal_distance", 1) or 1, "m"),
        "goal_achiever_3":       (gs.get("achieved_goal_months", 0), 3, "회"),
        "early_bird":        (ls.get("early_bird_count", 0), 3, "회"),
        "recovery_mindset":  (ls.get("easy_count", 0), 3, "회"),
        "hard_worker":       (ls.get("hard_count", 0), 3, "회"),
        "fins_try":          (ls.get("used_fins_count", 0), 1, "회"),
        "long_session":      (ls.get("max_single_dist", 0), 3_000, "m"),
        "mega_session":      (ls.get("max_single_dist", 0), 5_000, "m"),
    }
    current, target, unit = mapping.get(badge_id, (0, 1, ""))
    pct = min(100, round(current / target * 100)) if target else 0
    return {"current": current, "target": target, "unit": unit, "percent": pct}


def _badge_public_payload(badge_id: str, meta: dict, earned: bool, progress: dict) -> dict:
    return {
        **meta,
        "earned": earned,
        "progress": progress,
    }


def _build_series_groups(badges: list[dict]) -> list[dict]:
    by_id = {b["id"]: b for b in badges}
    groups = []
    for key, series in BADGE_SERIES.items():
        series_badges = [by_id[bid] for bid in series["badge_ids"] if bid in by_id]
        if not series_badges:
            continue
        completed = sum(1 for b in series_badges if b.get("earned"))
        next_badge = next((b for b in series_badges if not b.get("earned")), None)
        groups.append({
            "key": key,
            "label": series["label"],
            "description": series["description"],
            "completed_steps": completed,
            "total_steps": len(series_badges),
            "percent": round(completed / len(series_badges) * 100) if series_badges else 0,
            "next_badge": next_badge,
            "badges": series_badges,
        })
    return groups


@router.get("")
def get_badges(swimtech_token: str = Cookie(default=None)):
    _require_auth(swimtech_token)
    payload = decode_token(swimtech_token) if swimtech_token else {}
    customer_id = payload.get("customer_id")
    username = payload.get("sub", "")
    try:
        stats = {"log_stats": _calc_log_stats(username)}
        stats["plan_stats"] = _calc_plan_challenge_stats(username, customer_id)
        stats["goal_stats"] = _calc_goal_stats(customer_id)
        badges = []
        for badge_id, meta in BADGES.items():
            progress = _progress(badge_id, stats)
            earned = progress.get("percent", 0) >= 100
            badges.append(_badge_public_payload(badge_id, meta, earned, progress))
        earned_count = sum(1 for b in badges if b["earned"])
        series_groups = _build_series_groups(badges)
        next_badges = [
            g["next_badge"] for g in series_groups
            if g.get("next_badge")
        ][:4]
        return {
            "badges": badges,
            "earned_count": earned_count,
            "total_count": len(badges),
            "series_groups": series_groups,
            "next_badges": next_badges,
            "stats": stats,
        }
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
        customer_id = None
        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute("SELECT id FROM customers WHERE username = %s", (username,))
            row = cur.fetchone()
            customer_id = row[0] if row else None
            cur.close(); conn.close()
        except Exception:
            pass
        stats = {
            "log_stats": ls,
            "plan_stats": _calc_plan_challenge_stats(username, customer_id),
            "goal_stats": _calc_goal_stats(customer_id),
        }
        log_badge_ids = [
            "first_log", "log_dist_1km", "log_dist_10km", "log_dist_50km", "log_dist_100km",
            "log_dist_250km", "log_dist_500km", "log_count_5", "log_count_20", "log_count_50", "log_count_100",
            "log_streak_3", "log_streak_7", "log_streak_14", "log_streak_30", "log_streak_60",
            "stroke_free", "stroke_back", "stroke_breast", "stroke_fly", "log_stroke_master",
            "pool_25", "pool_50", "pool_dual", "monthly_goal_set", "monthly_goal_achiever",
            "hard_worker", "recovery_mindset", "fins_try", "long_session", "mega_session",
        ]
        return [bid for bid in log_badge_ids if _is_earned(bid, stats)]
    except Exception:
        return []
