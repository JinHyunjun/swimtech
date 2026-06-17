"""
SwimTech — 사용자 활동 로깅 공용 모듈
user_activity_logs 테이블에 이벤트를 기록한다.
미들웨어(자동: 페이지/메뉴 접근)와 각 라우터의 명시적 호출(의미 있는 이벤트)에서 함께 사용.
"""
import os
import json
import logging
import psycopg2

DATABASE_URL = os.getenv("DATABASE_URL", "")


def _get_db():
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    cur.execute("SET TIME ZONE 'Asia/Seoul'")
    cur.close()
    return conn


def log_activity(
    customer_id=None,
    username=None,
    event_type="page_view",
    page=None,
    menu_name=None,
    action=None,
    method=None,
    path=None,
    ip_address=None,
    user_agent=None,
    metadata=None,
):
    """
    user_activity_logs 에 한 행을 기록한다.
    실패해도 본 요청 흐름을 막지 않도록 항상 예외를 삼킨다(로깅은 부가 기능).
    """
    if not DATABASE_URL:
        return
    conn = None
    cur = None
    try:
        conn = _get_db()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO user_activity_logs
                (customer_id, username, event_type, page, menu_name,
                 action, method, path, ip_address, user_agent, metadata)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                customer_id,
                username,
                event_type,
                page,
                menu_name,
                action,
                method,
                path,
                ip_address,
                user_agent,
                json.dumps(metadata, ensure_ascii=False) if metadata else None,
            ),
        )
        conn.commit()
    except Exception as e:
        logging.warning("activity log insert failed (ignored): %s", e)
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


# 정적 경로(page) → 메뉴명 매핑. 활동 분석 화면에서 "메뉴별 클릭 수"로 보여줄 때 사용.
PAGE_MENU_MAP = {
    "/landing":       "랜딩",
    "/dashboard":      "대시보드",
    "/plan":           "훈련 플랜",
    "/training-log":   "훈련 일지",
    "/report":         "월간 리포트",
    "/pool":           "수영장 찾기",
    "/community":      "커뮤니티",
    "/challenge":      "수영 챌린지",
    "/badges":         "뱃지",
    "/coach":          "코치 연동",
    "/chat":           "AI 코치",
    "/profile":        "프로필",
}


def resolve_menu_name(path: str):
    return PAGE_MENU_MAP.get(path)
