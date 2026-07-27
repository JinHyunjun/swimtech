"""Privacy-minimized user context for personalized swimming answers."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


PERSONAL_INTENT_TERMS = (
    "내 기록", "내 훈련", "내 플랜", "내 목표", "내 pb", "내 최고", "내 컨디션",
    "나의 기록", "나의 훈련", "최근 기록", "최근 훈련", "맞춤", "개인화",
    "주간 목표", "월간 목표", "내 페이스", "내 사이클", "내 경우",
    "제 기록", "제 훈련", "제 목표", "제 컨디션",
)
PERSONAL_SUBJECT_TERMS = (
    "내", "나의", "나한테", "나에게", "저한테", "저에게", "제", "저의",
    "이번 주", "이번주", "이번 달", "이번달", "최근",
)
PERSONAL_DATA_TERMS = (
    "기록", "훈련", "플랜", "목표", "페이스", "사이클", "컨디션", "준비도",
    "pb", "최고기록", "세션", "달성률", "거리", "수행",
)


@dataclass(frozen=True)
class PersonalizationContext:
    available: bool = False
    applied: bool = False
    text: str = ""
    categories: tuple[str, ...] = ()

    def payload(self) -> dict:
        return {
            "available": self.available,
            "applied": self.applied,
            "categories": list(self.categories),
            "privacy_scope": "authenticated_customer_only",
        }


def should_personalize(query: str) -> bool:
    normalized = " ".join((query or "").lower().split())
    if any(term in normalized for term in PERSONAL_INTENT_TERMS):
        return True
    has_subject = any(term in normalized for term in PERSONAL_SUBJECT_TERMS)
    has_personal_data = any(term in normalized for term in PERSONAL_DATA_TERMS)
    return has_subject and has_personal_data


def _duration_text(duration_ms: int) -> str:
    total_centiseconds = max(0, int(duration_ms or 0) // 10)
    minutes, remainder = divmod(total_centiseconds, 6000)
    seconds, centiseconds = divmod(remainder, 100)
    if minutes:
        return f"{minutes}:{seconds:02d}.{centiseconds:02d}"
    return f"{seconds}.{centiseconds:02d}초"


def load_personalization(
    username: str,
    query: str,
    get_db: Callable,
) -> PersonalizationContext:
    """Load only the authenticated swimmer's non-identifying training context.

    Names, email, username, free-form training memos, and readiness notes are
    deliberately excluded from the model context.
    """
    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, level, goal, COALESCE(weekly_goal, 3),
                   COALESCE(preferred_pool_length, 25)
            FROM customers
            WHERE username = %s
            """,
            (username,),
        )
        profile = cur.fetchone()
        if not profile:
            return PersonalizationContext()

        if not should_personalize(query):
            return PersonalizationContext(available=True)

        customer_id, level, goal, weekly_goal, preferred_pool_length = profile
        categories = ["훈련 설정"]
        lines = [
            "\n\n[인증된 사용자의 개인화 훈련 데이터]",
            "이 데이터는 현재 로그인 사용자의 기록입니다. 아래 값만 활용하고 이름·계정·식별자를 추측하지 마세요.",
            "데이터가 없는 항목은 만들어내지 말고, 일반적인 제안과 개인 기록 기반 해석을 구분하세요.",
            f"- 설정: 수준 {level or '미설정'}, 목표 {goal or '미설정'}, "
            f"주 {int(weekly_goal or 3)}회, 선호 풀 {int(preferred_pool_length or 25)}m",
        ]

        cur.execute(
            """
            SELECT log_date, stroke_type, total_distance, duration_minutes,
                   COALESCE(pool_length, 25), intensity, mood
            FROM training_logs
            WHERE customer_id = %s
            ORDER BY log_date DESC, created_at DESC
            LIMIT 8
            """,
            (customer_id,),
        )
        recent_rows = cur.fetchall()
        if recent_rows:
            categories.append("최근 훈련")
            lines.append("- 최근 훈련(최신순):")
            for row in recent_rows:
                lines.append(
                    f"  · {row[0].isoformat()} {row[1] or '기타'} "
                    f"{int(row[2] or 0)}m/{int(row[3] or 0)}분/{int(row[4] or 25)}m 풀, "
                    f"강도 {row[5] or '미기록'}, 기분 {row[6] or '미기록'}"
                )

        cur.execute(
            """
            SELECT
                COUNT(*) FILTER (
                    WHERE log_date >= date_trunc('week', CURRENT_DATE)
                ),
                COALESCE(SUM(total_distance) FILTER (
                    WHERE log_date >= date_trunc('week', CURRENT_DATE)
                ), 0),
                COUNT(*) FILTER (
                    WHERE log_date >= date_trunc('month', CURRENT_DATE)
                ),
                COALESCE(SUM(total_distance) FILTER (
                    WHERE log_date >= date_trunc('month', CURRENT_DATE)
                ), 0),
                COALESCE(SUM(duration_minutes) FILTER (
                    WHERE log_date >= date_trunc('month', CURRENT_DATE)
                ), 0)
            FROM training_logs
            WHERE customer_id = %s
            """,
            (customer_id,),
        )
        aggregate = cur.fetchone() or (0, 0, 0, 0, 0)
        categories.append("주간·월간 요약")
        lines.append(
            f"- 이번 주: {int(aggregate[0] or 0)}회, {int(aggregate[1] or 0)}m"
        )
        lines.append(
            f"- 이번 달: {int(aggregate[2] or 0)}회, {int(aggregate[3] or 0)}m, "
            f"{int(aggregate[4] or 0)}분"
        )

        cur.execute(
            """
            SELECT
                to_regclass('public.training_goals') IS NOT NULL,
                to_regclass('public.training_readiness') IS NOT NULL,
                to_regclass('public.swim_test_results') IS NOT NULL,
                to_regclass('public.custom_plans') IS NOT NULL,
                to_regclass('public.training_log_sets') IS NOT NULL,
                to_regclass('public.plan_completions') IS NOT NULL
            """
        )
        optional = cur.fetchone() or (False,) * 6
        (
            has_goals,
            has_readiness,
            has_benchmarks,
            has_custom_plans,
            has_sets,
            has_completions,
        ) = [bool(value) for value in optional]

        if has_goals:
            cur.execute(
                """
                SELECT goal_distance
                FROM training_goals
                WHERE customer_id = %s
                  AND year = EXTRACT(YEAR FROM CURRENT_DATE)
                  AND month = EXTRACT(MONTH FROM CURRENT_DATE)
                """,
                (customer_id,),
            )
            goal_row = cur.fetchone()
            if goal_row and int(goal_row[0] or 0) > 0:
                goal_distance = int(goal_row[0])
                achieved = int(aggregate[3] or 0)
                rate = round(achieved / goal_distance * 100)
                categories.append("월간 목표")
                lines.append(
                    f"- 월간 거리 목표: {goal_distance}m 중 {achieved}m, 달성률 {rate}%"
                )

        if has_readiness:
            cur.execute(
                """
                SELECT check_date, readiness_score, available_minutes,
                       sleep_quality, fatigue, muscle_soreness
                FROM training_readiness
                WHERE customer_id = %s
                ORDER BY check_date DESC
                LIMIT 1
                """,
                (customer_id,),
            )
            readiness = cur.fetchone()
            if readiness:
                categories.append("훈련 준비도")
                lines.append(
                    f"- 최근 준비도({readiness[0].isoformat()}): {int(readiness[1])}점, "
                    f"가능 {int(readiness[2])}분, 수면 {int(readiness[3])}/5, "
                    f"피로 {int(readiness[4])}/5, 근육 뻐근함 {int(readiness[5])}/5"
                )

        if has_benchmarks:
            cur.execute(
                """
                SELECT DISTINCT ON (stroke_type, distance_m, pool_length)
                       stroke_type, distance_m, pool_length, duration_ms, test_date
                FROM swim_test_results
                WHERE customer_id = %s
                ORDER BY stroke_type, distance_m, pool_length,
                         duration_ms, test_date, id
                LIMIT 6
                """,
                (customer_id,),
            )
            bests = cur.fetchall()
            if bests:
                categories.append("개인 최고기록")
                lines.append("- 개인 최고기록:")
                for best in bests:
                    lines.append(
                        f"  · {best[0]} {int(best[1])}m/{int(best[2])}m 풀 "
                        f"{_duration_text(best[3])} ({best[4].isoformat()})"
                    )

        if has_custom_plans:
            cur.execute(
                """
                SELECT goal, sessions_per_week, session_duration,
                       focus_stroke, level
                FROM custom_plans
                WHERE username = %s
                ORDER BY created_at DESC
                LIMIT 2
                """,
                (username,),
            )
            plans = cur.fetchall()
            if plans:
                categories.append("저장 플랜")
                lines.append("- 최근 저장 플랜 설정:")
                for plan in plans:
                    lines.append(
                        f"  · 목표 {plan[0] or '-'}, 주 {plan[1] or '-'}회, "
                        f"회당 {plan[2] or '-'}분, 영법 {plan[3] or '-'}, 수준 {plan[4] or '-'}"
                    )

        if has_sets:
            cur.execute(
                """
                SELECT COUNT(*),
                       COUNT(*) FILTER (WHERE status = 'completed'),
                       COUNT(*) FILTER (WHERE actual_cycle_seconds IS NOT NULL),
                       COALESCE(AVG(rpe) FILTER (WHERE rpe IS NOT NULL), 0)
                FROM training_log_sets
                WHERE customer_id = %s
                  AND created_at >= CURRENT_DATE - INTERVAL '30 days'
                """,
                (customer_id,),
            )
            set_stats = cur.fetchone() or (0, 0, 0, 0)
            if int(set_stats[0] or 0) > 0:
                categories.append("세트 수행")
                lines.append(
                    f"- 최근 30일 세트: {int(set_stats[0])}개 중 완료 {int(set_stats[1])}개, "
                    f"실제 사이클 기록 {int(set_stats[2])}개, "
                    f"평균 RPE {round(float(set_stats[3] or 0), 1)}"
                )

        if has_completions:
            cur.execute(
                """
                SELECT COUNT(*)
                FROM plan_completions
                WHERE customer_id = %s
                  AND completed_at >= date_trunc('month', CURRENT_DATE)
                  AND training_log_id IS NOT NULL
                """,
                (customer_id,),
            )
            completion_count = int((cur.fetchone() or (0,))[0] or 0)
            if completion_count:
                categories.append("플랜 수행")
                lines.append(f"- 이번 달 일지로 완료한 플랜 세션: {completion_count}개")

        return PersonalizationContext(
            available=True,
            applied=True,
            text="\n".join(lines),
            categories=tuple(dict.fromkeys(categories)),
        )
    except Exception:
        return PersonalizationContext()
    finally:
        if cur is not None:
            cur.close()
        if conn is not None:
            conn.close()
