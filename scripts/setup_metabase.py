"""
Metabase 대시보드 자동 생성 스크립트
- 개인 분석 현황 대시보드
- 서비스 운영 대시보드
- frame_metrics 기반 프레임 상세 대시보드
"""

import time
import sys
import requests

METABASE_URL = "http://localhost:43001"
MB_USER = "admin@swimtech.local"
MB_PASS = "swimtech1234!"

DB_NAME = "swim-postgres"
DB_HOST = "swim-postgres"
DB_PORT = 5432
DB_DBNAME = "swimtech"
DB_USER = "swimtech"
DB_PASS = "swimtech1234"


# ─────────────────────────────────────────────
# Metabase API 헬퍼
# ─────────────────────────────────────────────

class MetabaseClient:
    def __init__(self, base_url: str):
        self.base = base_url.rstrip("/")
        self.session = requests.Session()
        self.token: str | None = None

    def _h(self) -> dict:
        return {"X-Metabase-Session": self.token, "Content-Type": "application/json"}

    # ── 인증 ──────────────────────────────────

    def setup_admin(self, email: str, password: str) -> bool:
        """최초 Setup이 필요한 경우 관리자 계정을 생성한다."""
        r = self.session.get(f"{self.base}/api/session/properties")
        props = r.json()
        if props.get("setup-token"):
            token = props["setup-token"]
            print(f"  [setup] 초기 셋업 토큰 발견: {token[:8]}...")
            payload = {
                "token": token,
                "user": {
                    "first_name": "Admin",
                    "last_name": "SwimMate",
                    "email": email,
                    "password": password,
                    "site_name": "SwimMate",
                },
                "prefs": {"site_name": "SwimMate", "allow_tracking": False},
            }
            r2 = self.session.post(f"{self.base}/api/setup", json=payload)
            if r2.status_code == 200:
                print("  [setup] 관리자 계정 생성 완료")
                return True
            else:
                print(f"  [setup] 셋업 실패: {r2.status_code} {r2.text[:200]}")
                return False
        return True  # 이미 셋업됨

    def login(self, email: str, password: str) -> bool:
        r = self.session.post(
            f"{self.base}/api/session",
            json={"username": email, "password": password},
        )
        if r.status_code == 200:
            self.token = r.json()["id"]
            print(f"  [login] 로그인 성공 (token: {self.token[:8]}...)")
            return True
        print(f"  [login] 실패: {r.status_code} {r.text[:200]}")
        return False

    # ── DB 연결 ───────────────────────────────

    def find_or_create_db(self) -> int:
        r = self.session.get(f"{self.base}/api/database", headers=self._h())
        dbs = r.json().get("data", r.json() if isinstance(r.json(), list) else [])
        for db in dbs:
            if db.get("name") == DB_NAME:
                db_id = db["id"]
                print(f"  [db] 기존 DB 연결 사용 (id={db_id})")
                return db_id

        payload = {
            "name": DB_NAME,
            "engine": "postgres",
            "details": {
                "host": DB_HOST,
                "port": DB_PORT,
                "dbname": DB_DBNAME,
                "user": DB_USER,
                "password": DB_PASS,
                "ssl": False,
            },
        }
        r2 = self.session.post(f"{self.base}/api/database", json=payload, headers=self._h())
        if r2.status_code not in (200, 202):
            raise RuntimeError(f"DB 생성 실패: {r2.status_code} {r2.text[:300]}")
        db_id = r2.json()["id"]
        print(f"  [db] 새 DB 연결 생성 (id={db_id})")

        # 스키마 동기화 대기
        print("  [db] 메타데이터 동기화 대기 (15초)...")
        self.session.post(f"{self.base}/api/database/{db_id}/sync", headers=self._h())
        time.sleep(15)
        return db_id

    # ── 카드(질문) 생성 ───────────────────────

    def create_card(self, name: str, db_id: int, sql: str, display: str,
                    viz_settings: dict, collection_id: int | None = None) -> int:
        payload = {
            "name": name,
            "dataset_query": {
                "type": "native",
                "native": {"query": sql},
                "database": db_id,
            },
            "display": display,
            "visualization_settings": viz_settings,
            "collection_id": collection_id,
        }
        r = self.session.post(f"{self.base}/api/card", json=payload, headers=self._h())
        if r.status_code not in (200, 202):
            raise RuntimeError(f"카드 생성 실패 [{name}]: {r.status_code} {r.text[:300]}")
        card_id = r.json()["id"]
        print(f"    카드 생성: '{name}' (id={card_id})")
        return card_id

    # ── 대시보드 생성 + 카드 배치 ─────────────

    def create_dashboard(self, name: str, collection_id: int | None = None) -> int:
        payload = {"name": name, "collection_id": collection_id}
        r = self.session.post(f"{self.base}/api/dashboard", json=payload, headers=self._h())
        if r.status_code not in (200, 202):
            raise RuntimeError(f"대시보드 생성 실패 [{name}]: {r.status_code} {r.text[:300]}")
        dash_id = r.json()["id"]
        print(f"  [dashboard] '{name}' 생성 (id={dash_id})")
        return dash_id

    def add_cards_to_dashboard(self, dash_id: int, card_layouts: list[dict]):
        """card_layouts: [{"card_id": int, "row": int, "col": int, "size_x": int, "size_y": int}]"""
        dashcards = []
        for item in card_layouts:
            dc = {
                "id": -(item["card_id"]),  # 임시 음수 ID
                "card_id": item["card_id"],
                "row": item["row"],
                "col": item["col"],
                "size_x": item["size_x"],
                "size_y": item["size_y"],
                "parameter_mappings": [],
                "visualization_settings": {},
            }
            dashcards.append(dc)

        r = self.session.put(
            f"{self.base}/api/dashboard/{dash_id}",
            json={"dashcards": dashcards},
            headers=self._h(),
        )
        if r.status_code not in (200, 202):
            raise RuntimeError(f"카드 배치 실패: {r.status_code} {r.text[:300]}")
        print(f"    {len(dashcards)}개 카드 배치 완료")


# ─────────────────────────────────────────────
# SQL 및 시각화 정의
# ─────────────────────────────────────────────

def build_dashboard_1(mb: MetabaseClient, db_id: int) -> int:
    """개인 분석 현황 대시보드"""
    print("\n[1] 개인 분석 현황 대시보드 구성 중...")

    c1 = mb.create_card(
        name="종합 점수 추이",
        db_id=db_id,
        sql="""
SELECT
    DATE_TRUNC('day', analyzed_at) AS analyzed_at,
    AVG(overall_score) AS avg_overall_score
FROM analysis_results
GROUP BY 1
ORDER BY 1
""",
        display="line",
        viz_settings={
            "graph.dimensions": ["analyzed_at"],
            "graph.metrics": ["avg_overall_score"],
            "graph.x_axis.title_text": "날짜",
            "graph.y_axis.title_text": "종합 점수",
        },
    )

    c2 = mb.create_card(
        name="팔꿈치 각도 변화 (좌/우)",
        db_id=db_id,
        sql="""
SELECT
    DATE_TRUNC('day', analyzed_at) AS analyzed_at,
    AVG(l_elbow_avg) AS l_elbow_avg,
    AVG(r_elbow_avg) AS r_elbow_avg
FROM analysis_results
GROUP BY 1
ORDER BY 1
""",
        display="line",
        viz_settings={
            "graph.dimensions": ["analyzed_at"],
            "graph.metrics": ["l_elbow_avg", "r_elbow_avg"],
            "graph.x_axis.title_text": "날짜",
            "graph.y_axis.title_text": "팔꿈치 각도 (°)",
            "series_settings": {
                "l_elbow_avg": {"title": "왼팔", "color": "#4C72B0"},
                "r_elbow_avg": {"title": "오른팔", "color": "#DD8452"},
            },
        },
    )

    c3 = mb.create_card(
        name="발차기 횟수 증감",
        db_id=db_id,
        sql="""
SELECT
    DATE_TRUNC('day', analyzed_at) AS analyzed_at,
    SUM(kick_count) AS total_kick_count
FROM analysis_results
GROUP BY 1
ORDER BY 1
""",
        display="bar",
        viz_settings={
            "graph.dimensions": ["analyzed_at"],
            "graph.metrics": ["total_kick_count"],
            "graph.x_axis.title_text": "날짜",
            "graph.y_axis.title_text": "발차기 횟수",
        },
    )

    c4 = mb.create_card(
        name="좌우 대칭 점수 추이",
        db_id=db_id,
        sql="""
SELECT
    DATE_TRUNC('day', analyzed_at) AS analyzed_at,
    AVG(arm_symmetry) AS avg_arm_symmetry
FROM analysis_results
GROUP BY 1
ORDER BY 1
""",
        display="line",
        viz_settings={
            "graph.dimensions": ["analyzed_at"],
            "graph.metrics": ["avg_arm_symmetry"],
            "graph.x_axis.title_text": "날짜",
            "graph.y_axis.title_text": "대칭 점수 (0~100)",
        },
    )

    c5 = mb.create_card(
        name="영법별 분석 횟수",
        db_id=db_id,
        sql="""
SELECT
    COALESCE(stroke_type, '미분류') AS stroke_type,
    COUNT(*) AS count
FROM analysis_results
GROUP BY 1
ORDER BY 2 DESC
""",
        display="pie",
        viz_settings={
            "pie.dimension": "stroke_type",
            "pie.metric": "count",
        },
    )

    dash_id = mb.create_dashboard("개인 분석 현황 대시보드")
    mb.add_cards_to_dashboard(dash_id, [
        {"card_id": c1, "row": 0, "col": 0,  "size_x": 12, "size_y": 6},
        {"card_id": c2, "row": 0, "col": 12, "size_x": 12, "size_y": 6},
        {"card_id": c3, "row": 6, "col": 0,  "size_x": 8,  "size_y": 6},
        {"card_id": c4, "row": 6, "col": 8,  "size_x": 10, "size_y": 6},
        {"card_id": c5, "row": 6, "col": 18, "size_x": 6,  "size_y": 6},
    ])
    return dash_id


def build_dashboard_2(mb: MetabaseClient, db_id: int) -> int:
    """서비스 운영 대시보드"""
    print("\n[2] 서비스 운영 대시보드 구성 중...")

    c1 = mb.create_card(
        name="일별 분석 건수",
        db_id=db_id,
        sql="""
SELECT
    DATE_TRUNC('day', analyzed_at) AS analyzed_at,
    COUNT(*) AS analysis_count
FROM analysis_results
GROUP BY 1
ORDER BY 1
""",
        display="bar",
        viz_settings={
            "graph.dimensions": ["analyzed_at"],
            "graph.metrics": ["analysis_count"],
            "graph.x_axis.title_text": "날짜",
            "graph.y_axis.title_text": "분석 건수",
        },
    )

    c2 = mb.create_card(
        name="영법별 평균 점수",
        db_id=db_id,
        sql="""
SELECT
    COALESCE(stroke_type, '미분류') AS stroke_type,
    ROUND(AVG(overall_score), 1) AS avg_score
FROM analysis_results
GROUP BY 1
ORDER BY 2 DESC
""",
        display="bar",
        viz_settings={
            "graph.dimensions": ["stroke_type"],
            "graph.metrics": ["avg_score"],
            "graph.x_axis.title_text": "영법",
            "graph.y_axis.title_text": "평균 점수",
        },
    )

    c3 = mb.create_card(
        name="총 사용자 수",
        db_id=db_id,
        sql="SELECT COUNT(*) AS total_users FROM customers",
        display="scalar",
        viz_settings={"scalar.field": "total_users"},
    )

    c4 = mb.create_card(
        name="총 분석 건수",
        db_id=db_id,
        sql="SELECT COUNT(*) AS total_analyses FROM analysis_results",
        display="scalar",
        viz_settings={"scalar.field": "total_analyses"},
    )

    dash_id = mb.create_dashboard("서비스 운영 대시보드")
    mb.add_cards_to_dashboard(dash_id, [
        {"card_id": c3, "row": 0, "col": 0,  "size_x": 6,  "size_y": 4},
        {"card_id": c4, "row": 0, "col": 6,  "size_x": 6,  "size_y": 4},
        {"card_id": c1, "row": 4, "col": 0,  "size_x": 12, "size_y": 6},
        {"card_id": c2, "row": 4, "col": 12, "size_x": 12, "size_y": 6},
    ])
    return dash_id


def build_dashboard_3(mb: MetabaseClient, db_id: int) -> int:
    """frame_metrics 기반 프레임 상세 대시보드"""
    print("\n[3] 프레임 상세 대시보드 구성 중...")

    c1 = mb.create_card(
        name="프레임별 팔꿈치 각도 (좌/우)",
        db_id=db_id,
        sql="""
SELECT
    timestamp_sec,
    l_elbow_angle,
    r_elbow_angle
FROM frame_metrics
WHERE video_id = (SELECT MAX(id) FROM videos)
ORDER BY timestamp_sec
""",
        display="line",
        viz_settings={
            "graph.dimensions": ["timestamp_sec"],
            "graph.metrics": ["l_elbow_angle", "r_elbow_angle"],
            "graph.x_axis.title_text": "시간 (초)",
            "graph.y_axis.title_text": "팔꿈치 각도 (°)",
            "series_settings": {
                "l_elbow_angle": {"title": "왼팔", "color": "#4C72B0"},
                "r_elbow_angle": {"title": "오른팔", "color": "#DD8452"},
            },
        },
    )

    c2 = mb.create_card(
        name="프레임별 발차기 감지 여부",
        db_id=db_id,
        sql="""
SELECT
    timestamp_sec,
    CASE WHEN kick_detected THEN 1 ELSE 0 END AS kick_detected
FROM frame_metrics
WHERE video_id = (SELECT MAX(id) FROM videos)
ORDER BY timestamp_sec
""",
        display="bar",
        viz_settings={
            "graph.dimensions": ["timestamp_sec"],
            "graph.metrics": ["kick_detected"],
            "graph.x_axis.title_text": "시간 (초)",
            "graph.y_axis.title_text": "발차기 감지 (1=감지)",
        },
    )

    dash_id = mb.create_dashboard("프레임 상세 대시보드 (frame_metrics)")
    mb.add_cards_to_dashboard(dash_id, [
        {"card_id": c1, "row": 0, "col": 0,  "size_x": 16, "size_y": 8},
        {"card_id": c2, "row": 0, "col": 16, "size_x": 8,  "size_y": 8},
    ])
    return dash_id


# ─────────────────────────────────────────────
# 메인
# ─────────────────────────────────────────────

def wait_for_metabase(base_url: str, timeout: int = 120):
    print(f"Metabase 기동 대기 중 ({base_url})...")
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = requests.get(f"{base_url}/api/health", timeout=5)
            if r.status_code == 200 and r.json().get("status") == "ok":
                print("  Metabase 준비 완료!")
                return
        except Exception:
            pass
        time.sleep(3)
    raise TimeoutError("Metabase가 제한 시간 내에 응답하지 않습니다.")


def main():
    wait_for_metabase(METABASE_URL)

    mb = MetabaseClient(METABASE_URL)

    print("\n관리자 계정 설정 중...")
    if not mb.setup_admin(MB_USER, MB_PASS):
        print("  (이미 셋업된 인스턴스)")

    print("\n로그인 중...")
    if not mb.login(MB_USER, MB_PASS):
        print("기본 계정으로 재시도...")
        # 혹시 다른 비밀번호로 이미 생성된 경우 안내
        sys.exit(1)

    print("\nDB 연결 확인 중...")
    db_id = mb.find_or_create_db()

    d1 = build_dashboard_1(mb, db_id)
    d2 = build_dashboard_2(mb, db_id)
    d3 = build_dashboard_3(mb, db_id)

    print(f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 Metabase 대시보드 생성 완료!
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  1. 개인 분석 현황 대시보드  → {METABASE_URL}/dashboard/{d1}
  2. 서비스 운영 대시보드      → {METABASE_URL}/dashboard/{d2}
  3. 프레임 상세 대시보드      → {METABASE_URL}/dashboard/{d3}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
""")


if __name__ == "__main__":
    main()
