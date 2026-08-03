#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SwimMate 자동 QA 검증 스크립트 (UI 레벨 — 실제 브라우저 클릭)
─────────────────────────────────────────────────────────
qa_runner.py(API 레벨 체크)와는 별개로, 로그인한 사용자가 보는 모든 메뉴 페이지에
실제로 들어가서 버튼·탭·칩·아코디언·모달 등 클릭 가능한 요소를 전부 눌러보고,
그 과정에서 발생하는 브라우저 콘솔 에러 / 처리되지 않은 예외 / 실패한 API 응답을
"개발자도구" 관점에서 수집해 어떤 동작에서 무엇이 깨졌는지 리포트로 남긴다.

회원 탈퇴·로그아웃 등 되돌릴 수 없는 동작은 클릭하지 않고 건너뛴다(존재 여부만 기록).

사용법:
    pip install playwright
    playwright install --with-deps chromium
    python scripts/qa_ui_crawler.py
    python scripts/qa_ui_crawler.py --base https://swimtech.vercel.app --headed

환경변수:
    QA_USERNAME, QA_PASSWORD, QA_EMAIL   — qa_runner.py와 동일한 고정 QA 계정
    QA_STUDENT_USERNAME, QA_STUDENT_PASSWORD
                                          — /coach 검증용 고정 학생 계정
    ADMIN_ID, ADMIN_PW                   — /admin 읽기 전용 검사용 관리자 계정

출력:
    qa_ui_report.json           — 페이지별/액션별 상세 결과
    qa_ui_screenshots/*.png     — 에러 발생 시점 + 각 페이지 최초 진입 스크린샷
"""
import os
import re
import sys
import json
import time
import atexit
import argparse
from pathlib import Path
from datetime import datetime

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass  # Python<3.7 또는 콘솔이 reconfigure를 지원하지 않는 환경

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
except ImportError:
    print("playwright 필요: pip install playwright && playwright install --with-deps chromium")
    sys.exit(1)

try:
    import requests
except ImportError:
    requests = None  # 코치 사전 연동 단계만 건너뛰고 나머지는 정상 동작

BASE = os.getenv("QA_BASE_URL", "https://swimtech.vercel.app")
USERNAME = os.getenv("QA_USERNAME", "")
PASSWORD = os.getenv("QA_PASSWORD", "")
EMAIL = os.getenv("QA_EMAIL", "")

# /coach 검증용 — 일반 QA 계정을 코치로, 보조 계정을 수강생으로 등록한다.
STUDENT_USERNAME = os.getenv("QA_STUDENT_USERNAME", "")
STUDENT_PASSWORD = os.getenv("QA_STUDENT_PASSWORD", "")
STUDENT_EMAIL = os.getenv("QA_STUDENT_EMAIL", "")

# /admin — 전용 관리자 계정으로 항상 검증
ADMIN_ID = os.getenv("ADMIN_ID", "")
ADMIN_PW = os.getenv("ADMIN_PW", "")

SHOT_DIR = Path("qa_ui_screenshots")
REPORT_PATH = Path("qa_ui_report.json")
MAX_ACTIONS_PER_PAGE = 60
ACTION_TIMEOUT_MS = 5000

# 로그인 후 둘러볼 메뉴 (api/main.py에 등록된 실제 라우트 기준)
PAGES = [
    ("/landing", "랜딩"),
    ("/tutorial", "기능 가이드"),
    ("/onboarding", "맞춤 훈련 설정"),
    ("/onboarding?mode=edit", "맞춤 훈련 설정 수정"),
    ("/dashboard", "대시보드"),
    ("/my-data", "내 수영 데이터"),
    ("/plan", "훈련 플랜"),
    ("/training-log", "훈련 일지"),
    ("/workout", "풀사이드 훈련"),
    ("/report", "월간 리포트"),
    ("/pool", "수영장 지도"),
    ("/drill", "드릴 가이드"),
    ("/faq", "FAQ"),
    ("/glossary", "용어집"),
    ("/badges", "뱃지"),
    ("/changelog", "변경 이력"),
    ("/community", "커뮤니티"),
    ("/challenge", "챌린지"),
    ("/equipment", "장비"),
    ("/feedback", "피드백"),
    ("/chat", "AI 코치 챗봇"),
    ("/videos", "영상 라이브러리"),
    ("/profile", "프로필"),
    ("/injury", "부상 예방"),
    ("/coach", "코치 연동"),
    ("/clubs", "클럽·반"),
]

PROTECTED_PATHS = {
    "/onboarding", "/dashboard", "/my-data", "/plan", "/training-log", "/workout", "/report", "/pool", "/badges",
    "/community", "/challenge", "/equipment", "/chat", "/videos",
    "/profile", "/injury", "/coach", "/clubs",
}

# 되돌릴 수 없는 동작 — 클릭하지 않고 "존재 확인"만 한다
DESTRUCTIVE_PATTERN = re.compile(
    r"탈퇴|회원\s*탈퇴|로그아웃|log\s*out|logout|delete\s*account|withdraw|결제|구독\s*취소",
    re.I,
)
DESTRUCTIVE_ID_PATTERN = re.compile(r"deleteBtn|withdraw|logout|ai-generate-btn|ai-save-btn|ai-publish-btn|insight-btn|insight-template-btn", re.I)

# 앱 코드와 무관한 서드파티/브라우저 노이즈는 에러로 치지 않음
IGNORE_CONSOLE_PATTERNS = [re.compile(p, re.I) for p in [
    r"ResizeObserver loop",
    r"kakao", r"daumcdn", r"kakaocdn",
    r"Download the React DevTools",
    r"X-Frame-Options",
    r"favicon\.ico",
]]

CLICKABLE_SELECTOR = (
    "button:not([disabled]), [role='button'], .tab-btn, .chip, .pool-filter-btn, "
    "[data-tab], [data-filter], [data-pool-length], [data-cycle-level], [data-type-filter], "
    "summary, .accordion-q, .faq-q, "
    "a[href^='/']"
)

# /admin은 실제 운영 데이터를 다루므로 탭·유형 필터만 일반 크롤 대상으로 삼는다.
# 카테고리 검색과 그래프는 아래 전용 읽기 검사에서 응답 계약까지 확인한다.
ADMIN_CLICKABLE_SELECTOR = ".admin-tab, .log-filter-btn, [data-tab], [data-type]"

RESULTS = []  # 페이지별 결과 dict 리스트

PAGE_EXPECTATIONS = {
    "/login": {
        "selectors": ["#login-btn", "#demo-btn"],
    },
    "/tutorial": {
        "selectors": ["#tutorial-hero", "#personal-flow", "#execution-flow", "#growth-flow", "#coach-flow", "#explore-flow", "#decision-guide", "[data-tutorial-shot]"],
        "texts": ["기능이 많아도", "훈련 일지와 테스트 세트", "내 수영 데이터", "코치 연결과 클럽·반", "어디로 가야 할지 모르겠다면"],
        "absent_texts": ["영상 영법 분석 기능을 제공합니다", "Apple Watch와 실시간 연동"],
    },
    "/onboarding": {
        "selectors": ["#onboarding-form", "[data-field='level']", "[data-field='goal']", "[data-field='weekly_goal']", "[data-field='preferred_pool_length']", "#next-btn"],
        "texts": ["내 수영에 맞는 기준부터 설정해요", "현재 수영 수준은 어떤가요?"],
        "absent_texts": ["AI 분석", "영상을 촬영"],
        "styles": [{"selector": ".step.active h2", "property": "color", "value": "rgb(237, 250, 255)"}],
    },
    "/onboarding?mode=edit": {
        "selectors": ["#onboarding-form", "#onboarding-exit-link", "#next-btn"],
        "texts": ["맞춤 훈련 설정을 수정해요", "프로필로 돌아가기"],
        "styles": [{"selector": ".step.active h2", "property": "color", "value": "rgb(237, 250, 255)"}],
    },
    "/dashboard": {
        "selectors": [".readiness-card", "#readiness-form", "#readiness-score", "#readiness-save", ".advisor-card", "#advisor-session", "#advisor-week", "#advisor-pool", "#advisor-readiness"],
        "texts": ["오늘의 훈련 준비도", "이번 주 훈련 추천"],
        "absent_texts": ["P3 Training Advisor"],
    },
    "/my-data": {
        "selectors": ["#data-content", "#lifetime-distance", "#monthly-trend-chart", "#stroke-distribution", "#recording-habits", "#insight-grid", "#personal-best-panel", "#pb-body"],
        "texts": ["내 기록을, 이해할 수 있는 데이터로", "전체 수영 이력", "원본 JSON 내보내기"],
        "wait_for_any_text": ["아직 해석할 훈련 기록이 없어요", "기록 습관과 데이터 깊이", "내 수영 데이터를 불러오지 못했습니다."],
    },
    "/training-log": {
        "selectors": ["#goal-section", "#stat-total", "#stat-avg", "#cal-body", "#btn-set-goal", "#f-set-summary", "#benchmark-section", "#btn-open-benchmark", "#benchmark-modal-backdrop", "#btn-open-import[disabled][aria-disabled='true'][data-feature-state='disabled']"],
        "texts": ["이번 달 목표 거리", "테스트 세트·개인 최고기록", "워치 데이터 가져오기 (준비 중)"],
    },
    "/workout": {
        "selectors": ["#workout-progress", "#set-strip", "#current-set-card", "#timer-value", "#timer-toggle", "#rep-complete", "#execution-sheet", "#wake-lock-btn"],
        "texts": ["풀사이드 훈련"],
        "wait_for_any_text": ["실행할 훈련을 선택해주세요", "저장된 세트가 없습니다", "훈련을 불러오지 못했습니다", "세트 완료"],
    },
    "/report": {
        "selectors": ["#stat-distance", "#stat-count", "#stat-avg", "#plan-performance", "#plan-goal-rate", "#plan-set-rate", "#plan-set-fill", "#benchmark-performance", "#benchmark-attempts", "#benchmark-pbs"],
        "texts": ["평균 거리 (m)", "플랜 수행률", "테스트 세트·개인 최고기록"],
    },
    "/chat": {
        "selectors": ["#chat-messages", "#chat-input", "#send-btn", "#chat-grounding-info", ".sample-grid", ".grounding-info"],
        "texts": ["영법·훈련·사이클·규정·장비·안전", "공식·교육기관 자료 기반", "개인화 질문에만 내 기록 반영", "의료 진단·영상 분석 미제공"],
    },
    "/profile": {
        "selectors": ["#p-email", "#training-profile-panel", "#p-training-level", "#p-training-goal", "#p-training-weekly", "#p-training-pool", "#onboarding-edit-link", "#my-data-panel", "#my-data-dashboard-link", "#password-panel", "#password-save-btn", "#data-export-panel", "#data-export-btn", "#session-security-panel", "#logout-all-btn", "#withdraw-open-btn"],
        "texts": ["맞춤 훈련 설정", "맞춤 훈련 설정 수정", "내 수영 데이터", "내 데이터 대시보드 보기", "내 데이터 내보내기", "로그인 세션 보안", "회원 탈퇴"],
    },
    "/plan": {
        "selectors": ["[data-pool-length]", "[data-cycle-level]", "[data-type-filter]", "[data-tab='myplan']"],
        "texts": ["내 플랜", "직접 구성"],
    },
    "/drill": {
        "selectors": ["#drill-search", "#focus-filters", "#level-filters", "#pool-filters", "#drill-count", ".drill-apply", ".tab-btn[data-tab='freestyle']", ".tab-btn[data-tab='backstroke']"],
        "texts": ["한 세션에는 교정 포인트 1~2개만", "출발 사이클", "25m", "50m"],
        "absent_texts": ["SwimMate 분석으로 확인할 것"],
    },
    "/injury": {
        "selectors": [".medical-notice", ".readiness-card", "[data-readiness='green']", "[data-readiness='yellow']", "[data-readiness='red']", "#readiness-result", ".prevention-grid", ".hospital-section", ".ref-note a"],
        "texts": ["의료 진단이 아닌 일반 안전 정보", "오늘 수영 전 상태 체크", "통증 동작 중단", "마지막 검토"],
        "absent_texts": ["허리 통증의 90%", "부담이 절반 이하", "SwimMate 분석으로 확인할 것"],
    },
    "/equipment": {
        "selectors": [".tab-btn[data-tab='swimwear']", "#tab-swimwear", "[data-suit-purpose='casual']", "[data-suit-purpose='training']", "[data-suit-purpose='race']", "#suit-recommendation", ".suit-table", ".care-strip", "#brand-size-guide", "#brand-size-tabs", "#brand-size-table", "#size-recommender-form", "#current-model", "#current-size", "#recommend-result"],
        "texts": ["수영 장비·수영복 가이드", "브랜드별 공식 사이즈표", "내 수영복 기준 브랜드별 사이즈 추천", "Speedo", "arena", "TYR", "Mizuno", "Nike Swim"],
    },
    "/faq": {
        "selectors": ["#search", "#faq-list", ".faq-item[data-q*='수영복']", ".faq-item[data-q*='드릴']", ".faq-item[data-q*='통증']"],
        "texts": ["훈련용 수영복은 어떻게 골라야 하나요?", "드릴은 몇 개를 골라 어떻게 세트에 넣나요?", "뻐근하거나 통증이 있는데 수영해도 되나요?"],
        "absent_texts": ["Google Sheets에 저장", "어떻게 촬영해야 분석이 잘 되나요", "분석 정확도는 얼마나 되나요", "PDF 저장"],
    },
    "/badges": {
        "selectors": ["#next-badge-panel", "#series-grid", ".badge-stage-card", ".next-badge-card", ".badge-card"],
        "texts": ["다음으로 노릴 뱃지", "단계별 뱃지 여정"],
    },
    "/coach": {
        "selectors": ["#coach-verification-card", "#my-invite-code", "#disconnect-coach-btn", "#coach-ai-studio", "#ai-doc-type", "#ai-generate-btn", "#coach-ai-insight", "#insight-btn", "#my-class-documents"],
        "texts": ["내 코치 코드", "선택 사항 · 코치 자격 인증"],
    },
    "/clubs": {
        "selectors": ["#clubs-grid", "#join-class-form", "#join-code", "#club-create-card", "#operations-overview", "#upcoming-sessions", "#recent-notices", "#club-modal", "#class-modal", "#attendance-modal"],
        "texts": ["내 클럽·반", "반 코드로 참여", "반 운영 한눈에 보기", "GROUP OPERATIONS"],
    },
    "/admin": {
        "selectors": [".admin-badge", "[data-tab='coaches']", "[data-tab='training-health']", "[data-tab='feedback']", "#tab-coaches", "#c-body", "#c-page-size", "#c-page-numbers", "#c-registered", "#c-pending", "#c-documents", "#tab-training-health", "#h-log-count", "#h-readiness-checkins", "#h-readiness-score", "#h-test-results", "#h-test-users", "#h-personal-bests", "#h-active-clubs", "#h-active-classes", "#h-class-sessions", "#h-attendance-rate", "#h-active-notices", "#h-recent-body", "#f-body", "#u-page-size", "#l-page-size", "#f-page-size", "#u-page-numbers", "#l-page-numbers", "#f-page-numbers", "#u-last", "#l-last", "#f-last", "#d-chart-days", "#d-page-views", "#d-visitors", "#d-active-users", "#d-traffic-chart", "#d-provider-chart", "#u-search-by", "#u-search", "#c-search-by", "#c-search", "#l-search-by", "#l-search", "#f-search-by", "#f-search", ".list-search-btn", ".list-search-reset"],
        # inner_text() excludes inactive tab panels and pagers hidden for a
        # single-page result. Their controls are therefore verified by stable
        # selectors above; only always-visible navigation copy belongs here.
        "texts": ["SUPER ADMIN", "코치 운영", "훈련 운영", "피드백"],
    },
}


def check_admin_search_and_charts(page):
    """관리자 그래프 렌더링과 네 목록의 읽기 전용 카테고리 검색을 실제 응답으로 확인한다."""
    actions, errors = [], []
    try:
        page.wait_for_function(
            "typeof Chart !== 'undefined' && Chart.getChart('d-traffic-chart') && Chart.getChart('d-provider-chart')",
            timeout=12000,
        )
        dataset_count = page.evaluate(
            "Chart.getChart('d-traffic-chart').data.datasets.length"
        )
        label_count = page.evaluate(
            "Chart.getChart('d-traffic-chart').data.labels.length"
        )
        if dataset_count < 4 or label_count < 7:
            errors.append({
                "type": "admin_chart_contract",
                "datasets": dataset_count,
                "labels": label_count,
            })
        else:
            actions.append({
                "action": f"관리자 방문·가입 그래프 {dataset_count}개 지표/{label_count}일",
                "status": "ok",
            })
    except Exception as error:
        errors.append({"type": "admin_chart_render_failed", "error": str(error)[:200]})

    marker = "qa-admin-ui-no-match-7f3a"
    search_specs = [
        ("users", "u", "username", "/api/admin/users"),
        ("coaches", "c", "specialty", "/api/admin/coaches"),
        ("logs", "l", "path", "/api/admin/logs"),
        ("feedback", "f", "title", "/api/feedback"),
    ]
    for list_name, prefix, category, api_path in search_specs:
        try:
            page.click(f".admin-tab[data-tab='{list_name}']")
            page.wait_for_timeout(150)
            page.select_option(f"#{prefix}-search-by", category)
            page.fill(f"#{prefix}-search", marker)
            with page.expect_response(
                lambda response, expected=api_path: expected in response.url and "q=" in response.url,
                timeout=12000,
            ) as response_info:
                page.click(f".list-search-btn[data-list='{list_name}']")
            response = response_info.value
            payload = response.json()
            if (
                response.status != 200
                or payload.get("search_by") != category
                or payload.get("q") != marker
                or payload.get("total") != 0
            ):
                errors.append({
                    "type": "admin_category_search_contract",
                    "list": list_name,
                    "status": response.status,
                    "search_by": payload.get("search_by"),
                    "total": payload.get("total"),
                })
            else:
                actions.append({"action": f"관리자 {list_name} {category} 검색", "status": "ok"})
            with page.expect_response(
                lambda reset_response, expected=api_path: expected in reset_response.url,
                timeout=12000,
            ):
                page.click(f".list-search-reset[data-list='{list_name}']")
        except Exception as error:
            errors.append({
                "type": "admin_category_search_failed",
                "list": list_name,
                "error": str(error)[:200],
            })
    try:
        page.click(".admin-tab[data-tab='dashboard']")
    except Exception:
        pass
    return actions, errors


def slug(text, n=40):
    s = re.sub(r"[^\w가-힣]+", "_", (text or "")[:n]).strip("_")
    return s or "el"


def is_destructive(text, el_id):
    if el_id and DESTRUCTIVE_ID_PATTERN.search(el_id):
        return True
    if text and DESTRUCTIVE_PATTERN.search(text):
        return True
    return False


def is_ignored_console(text):
    return any(p.search(text) for p in IGNORE_CONSOLE_PATTERNS)


def ensure_user_account(username=None, password=None, email=None, name="QA봇"):
    username = username or USERNAME
    password = password or PASSWORD
    email = email or EMAIL
    if requests is None:
        return username, password, email
    try:
        s = requests.Session()
        s.post(f"{BASE}/auth/register", json={
            "name": name,
            "email": email,
            "username": username,
            "password": password,
        }, timeout=30)
        r = s.post(f"{BASE}/auth/login", json={"username": username, "password": password}, timeout=30)
        if r.status_code == 200:
            return username, password, email

        raise RuntimeError(f"{username} 고정 QA 계정 로그인 실패({r.status_code})")
    except Exception as e:
        raise RuntimeError(f"QA 계정 준비 실패 — {e}")


def login(page, username=None, password=None):
    username = username or USERNAME
    password = password or PASSWORD
    page.goto(f"{BASE}/login", wait_until="domcontentloaded", timeout=30000)
    page.fill("#username", username)
    page.fill("#password", password)
    page.click("#login-btn")
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except PWTimeout:
        pass
    if "/login" in page.url:
        raise RuntimeError(f"로그인 실패 — 계정/비밀번호 확인 필요 (계정: {username})")
    expected_path = "/admin" if username == ADMIN_ID else "/landing"
    current_path = page.url.split("?", 1)[0].rstrip("/")
    if not current_path.endswith(expected_path):
        raise RuntimeError(
            f"로그인 후 대표 화면 불일치 — expected={expected_path}, actual={page.url}"
        )


def is_auth_redirect(path, page):
    route = path.split("?", 1)[0]
    if route == "/admin":
        return False
    current = page.url.split("?", 1)[0].rstrip("/")
    return route in PROTECTED_PATHS and (current.endswith("/login") or current.endswith("/landing"))


def goto_page(page, path, username=None, password=None, timeout=45000):
    resp = page.goto(f"{BASE}{path}", wait_until="domcontentloaded", timeout=timeout)
    try:
        page.wait_for_load_state("networkidle", timeout=8000)
    except PWTimeout:
        pass
    if is_auth_redirect(path, page):
        login(page, username, password)
        resp = page.goto(f"{BASE}{path}", wait_until="domcontentloaded", timeout=timeout)
        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except PWTimeout:
            pass
    return resp


def check_page_expectations(page, path):
    expected = PAGE_EXPECTATIONS.get(path)
    if not expected:
        return []
    errors = []
    for selector in expected.get("selectors", []):
        try:
            page.locator(selector).first.wait_for(state="attached", timeout=5000)
        except Exception:
            errors.append({"type": "missing_selector", "selector": selector})
    body_text = ""
    settled_texts = expected.get("wait_for_any_text", [])
    if settled_texts:
        for _ in range(30):
            try:
                body_text = page.locator("body").inner_text(timeout=3000)
            except Exception:
                body_text = ""
            if any(text in body_text for text in settled_texts):
                break
            page.wait_for_timeout(500)
        else:
            errors.append({"type": "async_state_not_settled", "expected_any": settled_texts})
    try:
        body_text = page.locator("body").inner_text(timeout=3000)
    except Exception:
        pass
    for text in expected.get("texts", []):
        if text not in body_text:
            errors.append({"type": "missing_text", "text": text})
    for text in expected.get("absent_texts", []):
        if text in body_text:
            errors.append({"type": "forbidden_text", "text": text})
    for style in expected.get("styles", []):
        selector = style["selector"]
        property_name = style["property"]
        expected_value = style["value"]
        try:
            actual_value = page.locator(selector).first.evaluate(
                "(element, propertyName) => getComputedStyle(element).getPropertyValue(propertyName)",
                property_name,
            ).strip()
            if actual_value != expected_value:
                errors.append({
                    "type": "unexpected_style",
                    "selector": selector,
                    "property": property_name,
                    "expected": expected_value,
                    "actual": actual_value,
                })
        except Exception:
            errors.append({
                "type": "style_check_failed",
                "selector": selector,
                "property": property_name,
            })
    return errors


def check_home_link_targets(page):
    """화면에 표시되는 홈 링크는 예외 없이 대표 URL인 /landing을 사용해야 한다."""
    errors = []
    try:
        links = page.locator("a[href]").all()
    except Exception:
        return errors
    for link in links:
        try:
            text = (link.inner_text(timeout=500) or "").strip()
            aria = link.get_attribute("aria-label") or ""
            title = link.get_attribute("title") or ""
            compact_text = text.replace("\n", " ").strip()
            is_home_control = (
                compact_text == "홈"
                or compact_text.startswith(("← 홈", "🏠 홈", "홈으로"))
                or aria.strip() in {"홈", "SwimMate 홈"}
                or title.strip() in {"홈", "SwimMate 홈"}
            )
            if not is_home_control:
                continue
            href = link.get_attribute("href") or ""
            if href != "/landing":
                errors.append({"type": "invalid_home_href", "href": href, "text": text[:60]})
        except Exception:
            continue
    return errors


def check_information_guide_interactions(page, path):
    """정보·도움 화면의 필터와 선택 결과가 실제 DOM 상태를 바꾸는지 읽기 전용으로 확인한다."""
    actions, errors = [], []
    try:
        if path == "/drill":
            page.fill("#drill-search", "호흡")
            page.click("#focus-filters [data-focus='breath']")
            page.click("#pool-filters [data-pool='50']")
            visible = page.locator("#tab-freestyle .drill-card:visible")
            if visible.count() < 1 or "50m" not in visible.first.locator(".drill-apply").inner_text():
                raise AssertionError("호흡 필터 또는 50m 적용 예시가 렌더링되지 않음")
            actions.append({"action": "드릴 검색·목적 필터·50m 적용 예시", "status": "ok"})
            page.fill("#drill-search", "")
            page.click("#focus-filters [data-focus='all']")
            page.click("#pool-filters [data-pool='25']")
        elif path == "/injury":
            page.click("[data-readiness='yellow']")
            result = page.locator("#readiness-result")
            if not result.is_visible() or "고강도·대시·패들 세트는 보류" not in result.inner_text():
                raise AssertionError("상태 체크 결과가 표시되지 않음")
            actions.append({"action": "부상 예방 주의 상태 체크", "status": "ok"})
        elif path == "/equipment":
            page.click(".tab-btn[data-tab='swimwear']")
            page.click("[data-suit-purpose='race']")
            result = page.locator("#suit-recommendation")
            if not page.locator("#tab-swimwear").is_visible() or "대회용 선택" not in result.inner_text():
                raise AssertionError("수영복 목적별 안내가 표시되지 않음")
            actions.append({"action": "수영복 구매 탭·대회 목적 선택", "status": "ok"})

            page.click("[data-size-profile='men']")
            page.click("[data-size-brand='arena']")
            if "남성 일반 수영복" not in page.locator("#brand-chart-title").inner_text():
                raise AssertionError("브랜드별 남성 사이즈표가 전환되지 않음")
            if page.locator("#brand-size-body tr").count() < 5:
                raise AssertionError("브랜드 사이즈표 행이 부족함")
            actions.append({"action": "브랜드·수영복 유형별 공식 사이즈표", "status": "ok"})

            page.select_option("#recommender-profile", "women")
            page.select_option("#current-brand", "auto")
            page.fill("#current-model", "미즈노 엑서수트 N2MAD785")
            page.fill("#current-size", "M")
            page.fill("#measure-bust", "83")
            page.fill("#measure-waist", "64")
            page.fill("#measure-hip", "91")
            page.fill("#measure-torso", "154")
            page.click(".recommend-submit")
            if not page.locator("#recommend-result").is_visible() or page.locator("#recommend-grid .recommend-card").count() != 5:
                raise AssertionError("현재 모델 기반 브랜드별 추천 5개가 표시되지 않음")
            if "신뢰도: 높음" not in page.locator("#recommend-summary").inner_text():
                raise AssertionError("실측 기반 추천 신뢰도가 표시되지 않음")
            actions.append({"action": "현재 모델·실측 기반 브랜드별 사이즈 추천", "status": "ok"})

            page.fill("#current-model", "Speedo Fastskin LZR")
            page.click(".recommend-submit")
            if "레이싱·테크수트 계열" not in page.locator("#recommend-message").inner_text():
                raise AssertionError("레이싱 수트 전용 표 안전 경계가 표시되지 않음")
            actions.append({"action": "레이싱 수트 일반표 교차 추천 차단", "status": "ok"})
            page.click(".tab-btn[data-tab='all']")
        elif path == "/faq":
            page.fill("#search", "수영복")
            visible = page.locator(".faq-item:visible")
            if visible.count() < 1 or "수영복" not in visible.first.inner_text():
                raise AssertionError("수영복 FAQ 검색 결과가 표시되지 않음")
            actions.append({"action": "수영복 FAQ 검색", "status": "ok"})
            page.fill("#search", "")
    except Exception as error:
        errors.append({"type": "information_guide_interaction_failed", "path": path, "error": str(error)[:200]})
    return actions, errors


def check_public_demo_entry(context):
    page = context.new_page()
    entry = {"page": "/login", "label": "Portfolio demo entry", "actions": [], "page_errors": []}
    try:
        page.goto(f"{BASE}/login", wait_until="domcontentloaded", timeout=30000)
        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except PWTimeout:
            pass
        expectation_errors = check_page_expectations(page, "/login")
        if expectation_errors:
            entry["page_errors"].append({"phase": "expectations", "errors": expectation_errors})
        page.click("#demo-btn")
        try:
            page.wait_for_url("**/landing", timeout=15000)
            page.wait_for_load_state("networkidle", timeout=15000)
        except PWTimeout:
            pass
        if not page.url.split("?", 1)[0].rstrip("/").endswith("/landing"):
            entry["page_errors"].append({
                "phase": "demo_redirect",
                "error": f"비회원 체험 후 /landing이 아님: {page.url}",
            })
        else:
            entry["actions"].append({"action": "비회원 체험 → /landing", "status": "ok"})
    except Exception as e:
        entry["page_errors"].append({"phase": "load", "error": str(e)[:200]})
    finally:
        try:
            page.close()
        except Exception:
            pass
    RESULTS.append(entry)
    mark = "FAIL" if entry["page_errors"] else "PASS"
    print(f"[Portfolio demo entry] /login {mark}")


def provision_coach_relationship():
    """QA 코치와 보조 학생을 연결하고 실패 시 전체 품질 게이트를 중단한다."""
    if requests is None:
        raise RuntimeError("requests 미설치 — 코치 권한 시나리오를 실행할 수 없습니다")
    try:
        s = requests.Session()
        r = s.post(f"{BASE}/auth/login", json={"username": USERNAME, "password": PASSWORD}, timeout=30)
        if r.status_code != 200:
            raise RuntimeError(f"QA 코치 계정 로그인 실패({r.status_code})")
        r = s.post(f"{BASE}/api/coach/register", json={
            "specialty": "QA", "career": "QA", "intro": "QA",
        }, timeout=30)
        if r.status_code != 200:
            raise RuntimeError(f"QA 코치 등록 실패({r.status_code})")
        profile = s.get(f"{BASE}/api/coach/me", timeout=30).json()
        invite_code = profile.get("invite_code")
        if not invite_code:
            raise RuntimeError("코치 코드가 즉시 발급되지 않았습니다")

        s2 = requests.Session()
        s2.post(f"{BASE}/auth/register", json={
            "name": "QA수강생", "email": STUDENT_EMAIL,
            "username": STUDENT_USERNAME, "password": STUDENT_PASSWORD,
        }, timeout=30)  # 이미 있으면 400 — 무시하고 로그인 시도
        r = s2.post(f"{BASE}/auth/login", json={"username": STUDENT_USERNAME, "password": STUDENT_PASSWORD}, timeout=30)
        if r.status_code != 200:
            raise RuntimeError(f"QA 학생 계정 로그인 실패({r.status_code})")
        if invite_code:
            join = s2.post(f"{BASE}/api/coach/join", json={"invite_code": invite_code}, timeout=30)
            if join.status_code != 200:
                raise RuntimeError(f"코치-학생 연동 실패({join.status_code})")
        return True
    except Exception as e:
        raise RuntimeError(f"/coach 사전 연동 중 오류: {e}") from e


def cleanup_coach_relationship():
    """전용 QA 학생 계정에 만든 코치 연결을 종료 시 정리한다."""
    if requests is None or not STUDENT_USERNAME or not STUDENT_PASSWORD:
        return
    try:
        session = requests.Session()
        login_result = session.post(
            f"{BASE}/auth/login",
            json={"username": STUDENT_USERNAME, "password": STUDENT_PASSWORD},
            timeout=30,
        )
        if login_result.status_code != 200:
            print(f"⚠ QA 학생 연결 정리 로그인 실패({login_result.status_code})")
            return
        result = session.delete(f"{BASE}/api/coach/my-coach", timeout=30)
        if result.status_code not in (200, 404):
            print(f"⚠ QA 코치-학생 연결 정리 실패({result.status_code})")
    except Exception as error:
        print(f"⚠ QA 코치-학생 연결 정리 중 오류: {error}")


def try_close_modal(page):
    """모달이 열려 있으면 닫고 기본 화면으로 복귀시킨다."""
    try:
        close_btn = page.locator(".modal-close:visible, [aria-label='닫기']:visible").first
        if close_btn.count() and close_btn.is_visible():
            close_btn.click(timeout=2000)
            page.wait_for_timeout(200)
            return
    except Exception:
        pass
    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(150)
    except Exception:
        pass


def collect_candidates(page, selector=CLICKABLE_SELECTOR):
    """클릭 후보 요소의 메타데이터(텍스트/id/태그)를 미리 수집한다."""
    try:
        handles = page.locator(selector).all()
    except Exception:
        return []
    candidates = []
    for i, h in enumerate(handles[:MAX_ACTIONS_PER_PAGE]):
        try:
            if not h.is_visible():
                continue
            text = (h.inner_text(timeout=1000) or "").strip().replace("\n", " ")[:60]
            el_id = h.get_attribute("id") or ""
            href = h.get_attribute("href") or ""
            label = text or el_id or href or f"요소#{i}"
            candidates.append({"index": i, "label": label, "text": text, "id": el_id, "href": href})
        except Exception:
            continue
    return candidates


def crawl_page(page, path, label, selector=CLICKABLE_SELECTOR, username=None, password=None):
    console_errors = []
    network_errors = []

    def on_console(msg):
        if msg.type == "error":
            text = msg.text
            if not is_ignored_console(text):
                console_errors.append({"text": text[:300], "location": str(msg.location)})

    def on_pageerror(exc):
        console_errors.append({"text": str(exc)[:300], "type": "uncaught_exception"})

    def on_response(resp):
        try:
            if resp.status == 401 and "/auth/refresh" in resp.url:
                return
            if resp.status >= 400 and resp.url.startswith(BASE) and "/static/" not in resp.url:
                network_errors.append({"url": resp.url, "status": resp.status})
        except Exception:
            pass

    page.on("console", on_console)
    page.on("pageerror", on_pageerror)
    page.on("response", on_response)

    entry = {"page": path, "label": label, "actions": [], "page_errors": []}
    SHOT_DIR.mkdir(parents=True, exist_ok=True)

    try:
        resp = goto_page(page, path, username=username, password=password)
        if resp and resp.status >= 400:
            entry["page_errors"].append({"phase": "load", "status": resp.status})
    except Exception as e:
        entry["page_errors"].append({"phase": "load", "error": str(e)[:200]})
        page.remove_listener("console", on_console)
        page.remove_listener("pageerror", on_pageerror)
        page.remove_listener("response", on_response)
        return entry

    page.screenshot(path=str(SHOT_DIR / f"{slug(path)}_00_load.png"))

    expectation_errors = check_page_expectations(page, path)
    expectation_errors.extend(check_home_link_targets(page))
    if path in {"/drill", "/injury", "/equipment", "/faq"}:
        guide_actions, guide_errors = check_information_guide_interactions(page, path)
        entry["actions"].extend(guide_actions)
        expectation_errors.extend(guide_errors)
    if path.split("?", 1)[0] == "/admin":
        admin_actions, admin_errors = check_admin_search_and_charts(page)
        entry["actions"].extend(admin_actions)
        expectation_errors.extend(admin_errors)
    if expectation_errors:
        entry["page_errors"].append({
            "phase": "expectations",
            "errors": expectation_errors,
        })

    if console_errors or network_errors:
        entry["page_errors"].append({
            "phase": "load",
            "console": console_errors.copy(),
            "network": network_errors.copy(),
        })
    console_errors.clear()
    network_errors.clear()

    candidates = collect_candidates(page, selector)
    for cand in candidates:
        action_label = cand["label"]
        if is_destructive(cand["text"], cand["id"]):
            entry["actions"].append({
                "action": action_label, "status": "skipped",
                "reason": "되돌릴 수 없는 동작으로 판단되어 클릭하지 않음(존재만 확인)",
            })
            continue

        try:
            el = page.locator(selector).nth(cand["index"])
            if not el.is_visible():
                continue
            console_errors.clear()
            network_errors.clear()
            before_url = page.url
            try:
                el.scroll_into_view_if_needed(timeout=2000)
            except Exception:
                pass
            try:
                el.click(timeout=ACTION_TIMEOUT_MS)
            except Exception as first_err:
                # 클릭이 페이지 이동을 유발하면 컨텍스트가 사라지며 예외가 날 수 있다.
                # 실제로 이동했다면 정상 동작이므로 무시하고 계속 진행한다.
                if page.url != before_url:
                    pass
                else:
                    # 다른 오버레이/요소가 가려서 클릭이 막히는 경우 — force 클릭으로 재시도.
                    try:
                        el.click(timeout=2000, force=True)
                    except Exception:
                        entry["actions"].append({
                            "action": action_label, "status": "blocked",
                            "reason": "요소가 다른 요소에 가려져 있거나 클릭 가능한 상태가 아님",
                            "error": str(first_err)[:200],
                        })
                        continue
            page.wait_for_timeout(400)
            try:
                page.wait_for_load_state("networkidle", timeout=4000)
            except PWTimeout:
                pass

            navigated = page.url != before_url
            action_result = {"action": action_label, "status": "ok"}
            if console_errors or network_errors:
                action_result["status"] = "error"
                action_result["console"] = console_errors.copy()
                action_result["network"] = network_errors.copy()
                shot_name = f"{slug(path)}_{cand['index']:02d}_{slug(action_label)}.png"
                try:
                    page.screenshot(path=str(SHOT_DIR / shot_name))
                    action_result["screenshot"] = shot_name
                except Exception:
                    pass

            try_close_modal(page)
            if navigated:
                try:
                    goto_page(page, path, username=username, password=password, timeout=30000)
                except Exception as nav_err:
                    action_result["status"] = "error"
                    action_result["error"] = f"원래 페이지 복귀 실패: {str(nav_err)[:160]}"
                console_errors.clear()
                network_errors.clear()
            entry["actions"].append(action_result)
        except PWTimeout as e:
            entry["actions"].append({"action": action_label, "status": "timeout", "error": str(e)[:200]})
        except Exception as e:
            entry["actions"].append({"action": action_label, "status": "click_failed", "error": str(e)[:200]})

    page.remove_listener("console", on_console)
    page.remove_listener("pageerror", on_pageerror)
    page.remove_listener("response", on_response)
    return entry


def main():
    global BASE, USERNAME, PASSWORD, EMAIL
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=BASE)
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--only", default="", help="콤마로 구분된 경로만 실행 (예: /plan,/chat)")
    args = ap.parse_args()
    BASE = args.base.rstrip("/")

    from validate_qa_credentials import missing_credentials

    missing = missing_credentials()
    if missing:
        print("❌ QA 계정 환경변수가 없습니다: " + ", ".join(missing))
        sys.exit(2)

    pages = PAGES
    if args.only:
        wanted = set(args.only.split(","))
        pages = [p for p in PAGES if p[0] in wanted]

    try:
        USERNAME, PASSWORD, EMAIL = ensure_user_account()
        print("✅ 일반 QA 계정 준비 완료")
    except Exception as e:
        print(f"❌ {e}")
        sys.exit(2)

    do_admin = not args.only or "/admin" in args.only.split(",")
    if any(p[0] == "/coach" for p in pages):
        print("코치-수강생 연동 사전 준비 중...")
        try:
            provision_coach_relationship()
            atexit.register(cleanup_coach_relationship)
        except Exception as e:
            print(f"❌ {e}")
            sys.exit(2)

    print(f"\n=== SwimMate UI QA 크롤 시작 ===\n대상: {BASE}\n페이지 수: {len(pages)}"
          f"{' (+/admin)' if do_admin else ''}\n")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not args.headed)
        context = browser.new_context(ignore_https_errors=True, viewport={"width": 1280, "height": 900})
        check_public_demo_entry(context)
        login_page = context.new_page()

        try:
            login(login_page)
            print("✅ 로그인 성공\n")
        except Exception as e:
            print(f"❌ {e}")
            browser.close()
            sys.exit(2)
        finally:
            try:
                login_page.close()
            except Exception:
                pass

        for path, label in pages:
            print(f"[{label}] {path} 검사 중...")
            page = context.new_page()
            entry = crawl_page(page, path, label)
            RESULTS.append(entry)
            n_err = sum(1 for a in entry["actions"] if a["status"] in ("error", "click_failed", "timeout", "blocked"))
            n_skip = sum(1 for a in entry["actions"] if a["status"] == "skipped")
            mark = "❌" if (entry["page_errors"] or n_err) else "✅"
            print(f"  {mark} 액션 {len(entry['actions'])}개 (에러 {n_err}, 건너뜀 {n_skip})")
            try:
                page.close()
            except Exception:
                pass

        if do_admin:
            print("\n[관리자] /admin 검사 중... (탭/필터 전환만 — 읽기 전용)")
            admin_context = browser.new_context(ignore_https_errors=True, viewport={"width": 1280, "height": 900})
            admin_page = admin_context.new_page()
            try:
                login(admin_page, ADMIN_ID, ADMIN_PW)
                entry = crawl_page(admin_page, "/admin", "관리자", selector=ADMIN_CLICKABLE_SELECTOR,
                                   username=ADMIN_ID, password=ADMIN_PW)
                if "/landing" in admin_page.url or admin_page.url.rstrip("/").endswith("/landing"):
                    entry["page_errors"].append({"phase": "load", "error": "관리자 권한으로 인식되지 않아 /landing으로 리다이렉트됨"})
                RESULTS.append(entry)
                n_err = sum(1 for a in entry["actions"] if a["status"] in ("error", "click_failed", "timeout", "blocked"))
                mark = "❌" if (entry["page_errors"] or n_err) else "✅"
                print(f"  {mark} 액션 {len(entry['actions'])}개 (에러 {n_err})")
            except Exception as e:
                print(f"  ❌ 관리자 로그인/검사 실패: {e}")
                RESULTS.append({"page": "/admin", "label": "관리자", "actions": [],
                                 "page_errors": [{"phase": "login", "error": str(e)[:200]}]})
            admin_context.close()

        browser.close()

    # ── 리포트 저장 ──────────────────────────────────────
    summary = {
        "base": BASE, "role": "qa-user", "ran_at": datetime.now().isoformat(),
        "pages": RESULTS,
    }
    REPORT_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n" + "=" * 60)
    total_errors = []
    for entry in RESULTS:
        if entry["page_errors"]:
            total_errors.append((entry["page"], "페이지 로드 오류", entry["page_errors"]))
        for a in entry["actions"]:
            if a["status"] in ("error", "click_failed", "timeout", "blocked"):
                total_errors.append((entry["page"], a["action"], a))

    print(f"  검사한 페이지: {len(RESULTS)}  /  발견된 문제: {len(total_errors)}")
    print("=" * 60)
    if total_errors:
        print("\n❌ 문제 상세:")
        for page_path, action, detail in total_errors:
            print(f"  [{page_path}] {action}")
            details = detail if isinstance(detail, list) else [detail]
            for item in details:
                if not isinstance(item, dict):
                    continue
                if "phase" in item:
                    print(f"      phase: {item['phase']}")
                for e in item.get("errors", []):
                    print(f"      expectation: {e}")
                for c in item.get("console", []):
                    print(f"      console: {c['text']}")
                for n in item.get("network", []):
                    print(f"      network: {n['status']} {n['url']}")
                if "reason" in item:
                    print(f"      reason: {item['reason']}")
                if "error" in item:
                    print(f"      error: {item['error']}")
    print(f"\n  → {REPORT_PATH} / {SHOT_DIR}/ 저장됨")
    sys.exit(1 if total_errors else 0)


if __name__ == "__main__":
    main()
