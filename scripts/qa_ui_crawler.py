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
    ("/tutorial/personal", "가이드 · 개인 훈련"),
    ("/tutorial/record", "가이드 · 기록·스크린샷"),
    ("/tutorial/data", "가이드 · 성장 데이터"),
    ("/tutorial/coach", "가이드 · 코치·클럽"),
    ("/tutorial/help", "가이드 · 정보·도움"),
    ("/privacy", "개인정보처리방침"),
    ("/terms", "이용약관"),
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

# 랜딩을 제외한 주요 기능 화면에는 동일한 서비스 사이드바가 유지되어야 한다.
SERVICE_NAV_PATHS = {
    "/dashboard", "/my-data", "/plan", "/training-log", "/workout", "/report",
    "/pool", "/drill", "/faq", "/glossary", "/badges", "/changelog",
    "/community", "/challenge", "/equipment", "/feedback", "/chat", "/videos",
    "/profile", "/injury", "/coach", "/clubs", "/tutorial",
    "/tutorial/personal", "/tutorial/record", "/tutorial/data", "/tutorial/coach", "/tutorial/help",
}

APP_HEADER_PATHS = SERVICE_NAV_PATHS | {
    "/landing", "/admin", "/privacy", "/terms", "/onboarding",
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
    "a[href^='/']:not(.global-service-nav-link):not(.service-nav-link)"
)

# /admin은 실제 운영 데이터를 다루므로 탭·유형 필터만 일반 크롤 대상으로 삼는다.
# 카테고리 검색과 그래프는 아래 전용 읽기 검사에서 응답 계약까지 확인한다.
ADMIN_CLICKABLE_SELECTOR = ".admin-tab, .log-filter-btn, [data-tab], [data-type]"

RESULTS = []  # 페이지별 결과 dict 리스트

PAGE_EXPECTATIONS = {
    "/login": {
        "selectors": ["#login-btn", "#demo-btn"],
    },
    "/landing": {
        "selectors": [
            "#service-sidebar",
            "#menu-toggle",
            "#landing-nav-search",
            ".landing-nav-primary",
            ".home-stat-details",
            ".home-mobile-nav",
            ".service-nav-link[href='/landing'][aria-current='page']",
            ".service-nav-link[href='/dashboard']",
            ".service-nav-link[href='/training-log']",
            ".service-nav-link[href='/plan']",
            ".service-nav-link[href='/report']",
            ".service-nav-link[href='/my-data']",
            "#home-week-distance",
            "#home-week-sessions",
            "#home-month-distance",
            "#home-total-distance",
            "#weekly-bar",
            "#advisor-title",
            "#home-history",
            "#tutorial-guide-card",
        ],
        "texts": [
            "내 훈련 분석",
            "코치·커뮤니티",
            "수영 정보·도구",
            "이번 주 거리",
            "이번 주 훈련",
            "최근 훈련 기록",
            "오늘 훈련 기록",
        ],
        "wait_for_any_text": [
            "목표까지",
            "이번 주 목표를 달성했습니다",
            "최근 기록을 불러오지 못했습니다",
        ],
        "absent_texts": ["무엇을 도와드릴까요? 원하는 서비스를 선택해주세요"],
    },
    "/tutorial": {
        "selectors": ["#tutorial-hero", "#guide-categories", "#quick-start", "[data-guide-card='personal']", "[data-guide-card='record']", "[data-guide-card='data']", "[data-guide-card='coach']", "[data-guide-card='help']", "[data-guide-link='home'][aria-current='page']"],
        "texts": ["필요한 기능만 골라서", "개인 훈련 시작", "기록·AI 스크린샷", "성장 데이터", "코치·클럽 운영", "수영 정보·도움"],
        "absent_texts": ["영상 영법 분석 기능을 제공합니다", "Apple Watch와 실시간 연동"],
    },
    "/tutorial/personal": {
        "selectors": ["#personal-guide-hero", "#personal-steps", "[data-tutorial-shot='personal-settings']", "[data-tutorial-shot='training-dashboard']", "[data-tutorial-shot='training-plan']", "[data-guide-link='personal'][aria-current='page']"],
        "texts": ["내 기준을 정하고", "처음 사용하는 순서", "추천의 기준 만들기", "오늘 할 수 있는 만큼 판단하기"],
    },
    "/tutorial/record": {
        "selectors": ["#record-guide-hero", "#screenshot-import-flow", "[data-screenshot-guide-preview]", "[data-tutorial-shot='training-log-pb']", "[data-tutorial-shot='poolside-workout']", "[data-guide-link='record'][aria-current='page']"],
        "texts": ["운동 스크린샷 등록 순서", "실제로 한 운동이 맞나요?", "원본 이미지와 비용·사용량 안내", "워치 직접 연동과 건강 전체 파일 가져오기는 아직 지원하지 않습니다"],
        "absent_texts": ["Apple Watch와 실시간 연동", "AI가 자동으로 확정 저장"],
    },
    "/tutorial/data": {
        "selectors": ["#data-guide-hero", "#data-relationship", "[data-tutorial-shot='monthly-report']", "[data-tutorial-shot='my-data']", "[data-guide-link='data'][aria-current='page']"],
        "texts": ["한 번의 기록부터", "세 화면의 차이", "이번 달은 어땠나", "장기적으로 어떻게 변했나"],
    },
    "/tutorial/coach": {
        "selectors": ["#coach-guide-hero", "#coach-roles", "[data-tutorial-shot='clubs-classes']", "[data-tutorial-shot='class-operations']", "[data-guide-link='coach'][aria-current='page']"],
        "texts": ["개인 운동과 분리된", "누가 무엇을 하나요?", "코치와 학생 연결하기", "반을 운영하고 강습 자료 배포"],
    },
    "/tutorial/help": {
        "selectors": ["#help-guide-hero", "#help-finder", "[data-tutorial-shot='training-guides']", "[data-tutorial-shot='pool-map']", "[data-tutorial-shot='community']", "[data-guide-link='help'][aria-current='page']"],
        "texts": ["궁금한 주제만 골라", "주제별 바로가기", "검수된 수영 정보 찾기", "브랜드별 수영복 사이즈 참고"],
        "absent_texts": ["영상 영법 분석을 제공합니다"],
    },
    "/onboarding": {
        "selectors": ["#onboarding-form", "[data-field='level']", "[data-field='goal']", "[data-field='weekly_goal']", "[data-field='preferred_pool_length']", "#next-btn"],
        "texts": ["내 수영에 맞는 기준부터 설정해요", "현재 수영 수준은 어떤가요?"],
        "absent_texts": ["AI 분석", "영상을 촬영"],
        "styles": [{"selector": ".step.active h2", "property": "color", "value": "rgb(237, 250, 255)"}],
    },
    "/onboarding?mode=edit": {
        "selectors": ["#onboarding-form", "#onboarding-exit-link", "#next-btn"],
        "texts": ["맞춤 훈련 설정을 수정해요", "프로필 수정"],
        "styles": [{"selector": ".step.active h2", "property": "color", "value": "rgb(237, 250, 255)"}],
    },
    "/dashboard": {
        "selectors": [".readiness-card", "#readiness-form", "#readiness-score", "#readiness-save", ".advisor-card", "#advisor-session", "#advisor-week", "#advisor-pool", "#advisor-readiness", ".advisor-more"],
        "texts": ["오늘의 훈련 준비도", "이번 주 훈련 추천"],
        "absent_texts": ["P3 Training Advisor"],
    },
    "/my-data": {
        "selectors": ["#data-content", "#lifetime-distance", "#monthly-trend-chart", "#stroke-distribution", "#recording-habits", "#insight-grid", "#personal-best-panel", "#pb-body"],
        "texts": ["내 기록을, 이해할 수 있는 데이터로", "전체 수영 이력", "원본 JSON 내보내기"],
        "wait_for_any_text": ["아직 해석할 훈련 기록이 없어요", "기록 습관과 데이터 깊이", "내 수영 데이터를 불러오지 못했습니다."],
    },
    "/training-log": {
        "selectors": ["#goal-section", "#stat-total", "#stat-avg", "#cal-body", "#btn-set-goal", "#f-set-summary", "#benchmark-section", "#btn-open-benchmark", "#benchmark-modal-backdrop", "#log-import-menu", "#btn-open-screenshot", "#screenshot-modal-backdrop", "#screenshot-file-input[multiple]", "#screenshot-batch-list", "#screenshot-review-progress", "#screenshot-analyze-btn", "#btn-open-import[disabled][aria-disabled='true'][data-feature-state='disabled']"],
        "texts": ["이번 달 목표 거리", "테스트 세트·개인 최고기록", "가져오기"],
    },
    "/workout": {
        "selectors": ["#workout-progress", "#set-strip", "#current-set-card", "#timer-value", "#timer-toggle", "#rep-complete", "#execution-sheet", "#wake-lock-btn"],
        "texts": ["풀사이드 훈련"],
        "wait_for_any_text": ["실행할 훈련을 선택해주세요", "저장된 세트가 없습니다", "훈련을 불러오지 못했습니다", "세트 완료"],
    },
    "/report": {
        "selectors": ["#stat-distance", "#stat-count", "#stat-avg", "#plan-performance", "#plan-goal-rate", "#plan-set-rate", "#plan-set-fill", "#benchmark-performance", "#benchmark-attempts", "#benchmark-pbs", "#result-share-panel", "#share-nickname", "#btn-create-share", "#share-ready"],
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
        "selectors": [".plan-choice-shell", "[data-plan-mode='purpose']", "[data-plan-mode='random']", "[data-plan-mode='builder']", "[data-plan-mode='myplan']", "#plan-purpose-select", ".plan-context-details", ".plan-tool-details", "[data-pool-length]", "[data-cycle-level]", "[data-type-filter]", "[data-tab='myplan']"],
        "texts": ["어떻게 만들까요?", "추천 플랜", "내 플랜", "직접 구성"],
    },
    "/drill": {
        "selectors": ["#drill-search", ".drill-principle", "#drill-filter-details", "#focus-filters", "#level-filters", "#pool-filters", "#drill-count", ".drill-apply", ".drill-card-more", ".tab-btn[data-tab='freestyle']", ".tab-btn[data-tab='backstroke']"],
        "texts": ["드릴 활용법 보기", "상세 필터", "25m"],
        "absent_texts": ["SwimMate 분석으로 확인할 것"],
    },
    "/injury": {
        "selectors": [".medical-notice", ".readiness-card", "[data-readiness='green']", "[data-readiness='yellow']", "[data-readiness='red']", "#readiness-result", ".prevention-grid", ".hospital-section", ".ref-note a"],
        "texts": ["의료 진단이 아닌 일반 안전 정보", "오늘 수영 전 상태 체크", "통증 동작 중단", "마지막 검토"],
        "absent_texts": ["허리 통증의 90%", "부담이 절반 이하", "SwimMate 분석으로 확인할 것"],
    },
    "/equipment": {
        "selectors": [".tab-btn[data-tab='swimwear']", "#tab-swimwear", "[data-suit-purpose='casual']", "[data-suit-purpose='training']", "[data-suit-purpose='race']", "#suit-recommendation", ".suit-table", ".care-strip", "#brand-size-guide", "#brand-size-tabs", "#brand-size-table", "[data-chart-unit='in']", "#size-recommender-form", "#measurement-unit", "#measure-bust-conversion", "#current-model", "#current-size", "#current-size-region", "#target-purchase-region", "#size-reference-confirm", "#recommend-result"],
        # 최초 진입에서는 수영복 탭이 숨겨져 있으므로 항상 보이는 제목만 확인한다.
        # 탭 내부 문구는 check_information_guide_interactions()에서 탭을 연 뒤 검증한다.
        "texts": ["수영 장비·수영복 가이드"],
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
        "selectors": [".admin-badge", "#admin-sidebar", "#admin-menu-toggle", "#admin-nav-backdrop", ".admin-tab-index", "[data-tab='coaches']", "[data-tab='training-health']", "[data-tab='qa-logs']", "[data-tab='feedback']", "#tab-coaches", "#c-body", "#c-page-size", "#c-page-numbers", "#c-registered", "#c-pending", "#c-documents", "#tab-training-health", "#h-log-count", "#h-readiness-checkins", "#h-readiness-score", "#h-test-results", "#h-test-users", "#h-personal-bests", "#h-screenshot-imports", "#h-result-shares", "#h-result-share-views", "#h-public-campaigns", "#h-campaign-views", "#h-active-clubs", "#h-active-classes", "#h-class-sessions", "#h-attendance-rate", "#h-active-notices", "#h-recent-body", "#q-body", "#q-account-count", "#q-events-30d", "#q-page-views-30d", "#q-account-list", "#f-body", "#u-account-scope", "#u-page-size", "#l-page-size", "#q-page-size", "#f-page-size", "#u-page-numbers", "#l-page-numbers", "#q-page-numbers", "#f-page-numbers", "#u-last", "#l-last", "#q-last", "#f-last", "#d-chart-days", "#d-page-views", "#d-visitors", "#d-active-users", "#d-traffic-chart", "#d-provider-chart", "#u-search-by", "#u-search", "#c-search-by", "#c-search", "#l-search-by", "#l-search", "#q-search-by", "#q-search", "#f-search-by", "#f-search", ".list-search-btn", ".list-search-reset"],
        # inner_text() excludes inactive tab panels and pagers hidden for a
        # single-page result. Their controls are therefore verified by stable
        # selectors above; only always-visible navigation copy belongs here.
        "texts": ["SUPER ADMIN", "코치 운영", "훈련 운영", "QA 검증 로그", "피드백"],
    },
}


def check_admin_search_and_charts(page):
    """관리자 그래프와 일반/QA 분리 로그를 포함한 다섯 목록 검색을 확인한다."""
    actions, errors = [], []
    original_viewport = page.viewport_size
    try:
        sidebar_box = page.locator("#admin-sidebar").bounding_box()
        content_box = page.locator("#admin-content").bounding_box()
        if (
            not sidebar_box or not content_box
            or sidebar_box["width"] < 220
            or content_box["x"] < sidebar_box["x"] + sidebar_box["width"] - 1
        ):
            errors.append({
                "type": "admin_sidebar_desktop_layout",
                "sidebar": sidebar_box,
                "content": content_box,
            })
        else:
            actions.append({"action": "관리자 데스크톱 고정 사이드 메뉴", "status": "ok"})

        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_timeout(250)
        page.click("#admin-menu-toggle")
        page.wait_for_timeout(300)
        mobile_nav = page.evaluate(
            """() => {
              const sidebar = document.getElementById('admin-sidebar').getBoundingClientRect();
              const items = [...document.querySelectorAll('.admin-tab')].map(button => {
                const rect = button.getBoundingClientRect();
                const label = button.querySelector('.admin-tab-label').getBoundingClientRect();
                return {top:rect.top, bottom:rect.bottom, width:rect.width, labelLeft:label.left, labelRight:label.right};
              });
              const overlaps = items.some((item, index) => index > 0 && item.top < items[index - 1].bottom - 1);
              const labelsOutside = items.some(item => item.labelLeft < sidebar.left || item.labelRight > sidebar.right);
              return {
                sidebar:{left:sidebar.left, right:sidebar.right, width:sidebar.width},
                itemCount:items.length,
                minItemWidth:Math.min(...items.map(item => item.width)),
                overlaps,
                labelsOutside,
                documentOverflow:Math.max(0, document.documentElement.scrollWidth - document.documentElement.clientWidth),
              };
            }"""
        )
        if (
            mobile_nav["itemCount"] != 8
            or mobile_nav["minItemWidth"] < 220
            or mobile_nav["overlaps"]
            or mobile_nav["labelsOutside"]
            or mobile_nav["documentOverflow"] > 1
        ):
            errors.append({"type": "admin_sidebar_mobile_layout", **mobile_nav})
        else:
            actions.append({"action": "관리자 모바일 드로어 8개 메뉴 비겹침", "status": "ok"})
        page.keyboard.press("Escape")
        page.wait_for_timeout(250)
    except Exception as error:
        errors.append({"type": "admin_sidebar_interaction_failed", "error": str(error)[:200]})
    finally:
        if original_viewport:
            page.set_viewport_size(original_viewport)
            page.wait_for_timeout(250)

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

    try:
        page.click(".admin-tab[data-tab='users']")
        with page.expect_response(
            lambda response: "/api/admin/users" in response.url and "account_scope=candidate" in response.url,
            timeout=12000,
        ) as candidate_response_info:
            page.select_option("#u-account-scope", "candidate")
        candidate_response = candidate_response_info.value
        candidate_payload = candidate_response.json()
        candidate_users = candidate_payload.get("users") or []
        if (
            candidate_response.status != 200
            or candidate_payload.get("account_scope") != "candidate"
            or any(user.get("is_qa_account") or not (user.get("qa_evidence") or {}).get("is_candidate") for user in candidate_users)
        ):
            errors.append({"type": "admin_qa_candidate_filter_contract"})
        else:
            actions.append({"action": f"관리자 미분류 QA 후보 {candidate_payload.get('total', 0)}개 조회", "status": "ok"})
        with page.expect_response(
            lambda response: "/api/admin/users" in response.url and "account_scope=all" in response.url,
            timeout=12000,
        ):
            page.select_option("#u-account-scope", "all")
    except Exception as error:
        errors.append({"type": "admin_qa_candidate_filter_failed", "error": str(error)[:200]})

    marker = "qa-admin-ui-no-match-7f3a"
    search_specs = [
        ("users", "users", "u", "username", "/api/admin/users", None),
        ("coaches", "coaches", "c", "specialty", "/api/admin/coaches", None),
        ("logs", "logs", "l", "path", "/api/admin/logs", "regular"),
        ("qaLogs", "qa-logs", "q", "path", "/api/admin/logs", "qa"),
        ("feedback", "feedback", "f", "title", "/api/feedback", None),
    ]
    for list_name, tab_name, prefix, category, api_path, expected_scope in search_specs:
        try:
            page.click(f".admin-tab[data-tab='{tab_name}']")
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
                or (expected_scope and payload.get("account_scope") != expected_scope)
            ):
                errors.append({
                    "type": "admin_category_search_contract",
                    "list": list_name,
                    "status": response.status,
                    "search_by": payload.get("search_by"),
                    "account_scope": payload.get("account_scope"),
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
    # 실제 사용 흐름처럼 비밀번호 입력 후 Enter로 폼을 제출한다. 이 경로가
    # 실패하면 일반·학생·관리자 브라우저 QA가 모두 로그인 단계에서 중단된다.
    page.keyboard.press("Enter")
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


def check_service_navigation(page, path):
    """주요 기능 페이지에서 공통 메뉴의 구조·활성 상태·대표 이동 경로를 검증한다."""
    route = path.split("?", 1)[0].rstrip("/") or "/"
    if route not in SERVICE_NAV_PATHS:
        return []
    # 목적별 가이드 상세 화면은 공통 서비스 메뉴에서 하나의
    # `/tutorial` 항목으로 묶이고, 상세 구분은 가이드 내부 탭이 담당한다.
    expected_active_route = "/tutorial" if route.startswith("/tutorial/") else route

    errors = []
    sidebar = page.locator("#global-service-nav")
    try:
        sidebar.wait_for(state="attached", timeout=7000)
    except Exception:
        return [{"type": "missing_service_navigation", "path": route}]

    required_hrefs = {
        "/landing", "/dashboard", "/training-log", "/plan", "/workout", "/report",
        "/my-data", "/chat", "/coach", "/clubs", "/pool", "/drill", "/injury",
        "/equipment", "/tutorial", "/profile", "/feedback",
    }
    actual_hrefs = set()
    try:
        links = page.locator("#global-service-nav .global-service-nav-link")
        for index in range(links.count()):
            href = links.nth(index).get_attribute("href")
            if href:
                actual_hrefs.add(href)
        if links.count() < 25:
            errors.append({"type": "service_navigation_link_count", "actual": links.count(), "minimum": 25})
    except Exception as error:
        errors.append({"type": "service_navigation_links_unreadable", "error": str(error)[:160]})

    missing_hrefs = sorted(required_hrefs - actual_hrefs)
    if missing_hrefs:
        errors.append({"type": "service_navigation_missing_hrefs", "hrefs": missing_hrefs})

    active = page.locator("#global-service-nav .global-service-nav-link[aria-current='page']")
    try:
        if active.count() != 1:
            errors.append({"type": "service_navigation_active_count", "actual": active.count(), "expected": 1})
        elif active.first.get_attribute("data-route") != expected_active_route:
            errors.append({
                "type": "service_navigation_wrong_active_route",
                "expected": expected_active_route,
                "actual": active.first.get_attribute("data-route"),
            })
    except Exception as error:
        errors.append({"type": "service_navigation_active_unreadable", "error": str(error)[:160]})

    try:
        if not page.locator("body.global-service-nav-enabled").count():
            errors.append({"type": "service_navigation_body_layout_missing"})
        if page.locator("#global-service-nav-toggle").count() != 1:
            errors.append({"type": "service_navigation_toggle_missing"})
        if page.locator("#global-service-nav .global-service-nav-primary .global-service-nav-link").count() != 4:
            errors.append({"type": "service_navigation_primary_count"})
        if page.locator("#global-service-nav .global-service-nav-group").count() != 3:
            errors.append({"type": "service_navigation_group_count"})
        if page.locator("#global-service-nav .global-service-nav-search input").count() != 1:
            errors.append({"type": "service_navigation_search_missing"})
        if page.viewport_size and page.viewport_size["width"] > 1100:
            position = sidebar.evaluate("element => getComputedStyle(element).position")
            if position != "fixed" or not sidebar.is_visible():
                errors.append({"type": "service_navigation_not_persistent_desktop", "position": position})
        overflow = page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
        if overflow > 1:
            errors.append({"type": "service_navigation_horizontal_overflow", "pixels": overflow})
    except Exception as error:
        errors.append({"type": "service_navigation_layout_unreadable", "error": str(error)[:160]})

    # 접힌 보조 메뉴에서도 검색 한 번으로 원하는 기능을 찾을 수 있어야 한다.
    try:
        search = page.locator("#global-service-nav .global-service-nav-search input")
        search.fill("수영복")
        page.wait_for_timeout(100)
        swimsuit = page.locator("#global-service-nav .global-service-nav-link[href='/equipment?tab=swimwear']")
        if not swimsuit.is_visible() or not swimsuit.locator("xpath=ancestor::*[contains(@class,'global-service-nav-group')][1]").evaluate("element => element.classList.contains('open')"):
            errors.append({"type": "service_navigation_search_result_hidden"})
        search.fill("")
    except Exception as error:
        errors.append({"type": "service_navigation_search_failed", "error": str(error)[:160]})

    # 대표 화면에서 모바일 드로어의 열기·ESC 닫기·스크롤 잠금까지 실제로 동작시킨다.
    if route == "/dashboard":
        original_viewport = page.viewport_size
        try:
            page.set_viewport_size({"width": 390, "height": 844})
            toggle = page.locator("#global-service-nav-toggle")
            toggle.wait_for(state="visible", timeout=3000)
            if sidebar.get_attribute("aria-hidden") != "true":
                errors.append({"type": "service_navigation_mobile_initial_state"})
            toggle.click()
            page.wait_for_timeout(250)
            if (
                toggle.get_attribute("aria-expanded") != "true"
                or "open" not in (sidebar.get_attribute("class") or "").split()
                or not page.locator("body.global-service-nav-open").count()
                or not page.locator("#global-service-nav-backdrop.open").count()
            ):
                errors.append({"type": "service_navigation_mobile_open_failed"})
            page.keyboard.press("Escape")
            page.wait_for_timeout(250)
            if toggle.get_attribute("aria-expanded") != "false" or page.locator("body.global-service-nav-open").count():
                errors.append({"type": "service_navigation_mobile_escape_close_failed"})
            mobile_nav = page.locator("#global-mobile-nav")
            if not mobile_nav.is_visible() or mobile_nav.locator(".global-service-nav-link").count() != 4:
                errors.append({"type": "service_navigation_mobile_quick_nav_missing"})
            else:
                mobile_nav.locator(".global-mobile-nav-more").click()
                page.wait_for_timeout(120)
                if toggle.get_attribute("aria-expanded") != "true" or not sidebar.is_visible():
                    errors.append({"type": "service_navigation_mobile_more_failed"})
                page.keyboard.press("Escape")
            overflow = page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
            if overflow > 1:
                errors.append({"type": "service_navigation_mobile_horizontal_overflow", "pixels": overflow})
        except Exception as error:
            errors.append({"type": "service_navigation_mobile_interaction_failed", "error": str(error)[:160]})
        finally:
            if original_viewport:
                page.set_viewport_size(original_viewport)
    return errors


def check_global_app_header(page, path):
    """공통 홈·프로필·로그아웃·테마 헤더의 인증 상태, 순서와 반응형 배치를 검증한다."""
    route = path.split("?", 1)[0].rstrip("/") or "/"
    if route not in APP_HEADER_PATHS:
        return []

    errors = []
    header = page.locator("#global-app-header")
    try:
        header.wait_for(state="visible", timeout=7000)
    except Exception:
        return [{"type": "missing_global_app_header", "path": route}]

    try:
        if header.count() != 1:
            errors.append({"type": "global_app_header_count", "actual": header.count(), "expected": 1})
        home = header.locator(".global-app-home")
        if home.get_attribute("href") != "/landing":
            errors.append({"type": "global_app_header_home_target", "href": home.get_attribute("href")})
        if header.locator("#theme-toggle-btn").count() != 1 or not header.locator("#theme-toggle-btn").is_visible():
            errors.append({"type": "global_app_header_theme_missing"})

        profile = header.locator("#global-app-profile")
        logout = header.locator("#global-app-logout")
        login = header.locator("#global-app-login")
        profile.wait_for(state="visible", timeout=7000)
        if profile.get_attribute("href") != "/profile" or not logout.is_visible() or login.is_visible():
            errors.append({
                "type": "global_app_header_authenticated_actions",
                "profileHref": profile.get_attribute("href"),
                "profileVisible": profile.is_visible(),
                "logoutVisible": logout.is_visible(),
                "loginVisible": login.is_visible(),
            })

        action_order = page.evaluate(
            """() => [...document.querySelectorAll('#global-app-header .global-app-header-actions > :not([hidden])')]
              .map(element => element.id).filter(Boolean)"""
        )
        if action_order != ["global-app-profile", "global-app-logout", "theme-toggle-btn"]:
            errors.append({"type": "global_app_header_action_order", "actual": action_order})

        expected_menu = (
            "#menu-toggle" if route == "/landing"
            else "#admin-menu-toggle" if route == "/admin"
            else "#global-service-nav-toggle" if route in SERVICE_NAV_PATHS
            else None
        )
        if expected_menu:
            try:
                page.locator(
                    f"#global-app-header .global-app-header-left > {expected_menu}"
                ).wait_for(state="attached", timeout=5000)
            except Exception:
                errors.append({"type": "global_app_header_menu_placement", "selector": expected_menu})
        if route == "/chat" and not page.locator("#global-app-header .global-app-header-left > #sidebar-toggle-btn").count():
            errors.append({"type": "global_app_header_chat_history_missing"})
        if route == "/community":
            try:
                page.locator("#global-app-header .global-app-header-actions #notif-bell").wait_for(state="visible", timeout=7000)
            except Exception:
                errors.append({"type": "global_app_header_notification_missing"})

        duplicate_legacy = page.locator(
            ".header:not(#global-app-header):visible, body > .home-header:visible, body > .navbar:visible, "
            ".club-header > a[href='/landing']:visible, .profile-topbar > a[href='/landing']:visible"
        ).count()
        if duplicate_legacy:
            errors.append({"type": "global_app_header_legacy_home_visible", "count": duplicate_legacy})

        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(80)
        desktop = page.evaluate(
            """() => {
              const headerElement = document.getElementById('global-app-header');
              const header = headerElement.getBoundingClientRect();
              const leftGroup = document.querySelector('#global-app-header .global-app-header-left').getBoundingClientRect();
              const actionGroup = document.querySelector('#global-app-header .global-app-header-actions').getBoundingClientRect();
              const children = [...document.querySelectorAll('#global-app-header .global-app-home, #global-app-header .global-app-header-actions > :not([hidden])')]
                .filter(element => getComputedStyle(element).display !== 'none')
                .map(element => { const rect = element.getBoundingClientRect(); return {id:element.id || element.className, left:rect.left, right:rect.right}; });
              const overlaps = children.some((item, index) => index > 0 && item.left < children[index - 1].right - 1);
              return {left:header.left, right:header.right, width:header.width, viewport:document.documentElement.clientWidth, position:getComputedStyle(headerElement).position, overlaps:overlaps || leftGroup.right > actionGroup.left + 1};
            }"""
        )
        if (
            abs(desktop["left"]) > 1
            or abs(desktop["right"] - desktop["viewport"]) > 1
            or desktop["position"] not in ("static", "relative")
            or desktop["overlaps"]
        ):
            errors.append({"type": "global_app_header_desktop_layout", **desktop})

        scroll_probe = page.evaluate(
            """() => ({
              available: Math.max(0, document.documentElement.scrollHeight - innerHeight),
              headerBottom: document.getElementById('global-app-header').getBoundingClientRect().bottom
            })"""
        )
        if scroll_probe["available"] >= 80:
            page.evaluate("distance => window.scrollTo(0, distance)", min(180, scroll_probe["available"]))
            page.wait_for_timeout(120)
            scrolled = page.evaluate(
                """() => {
                  const header = document.getElementById('global-app-header').getBoundingClientRect();
                  const nav = [
                    document.getElementById('global-service-nav'),
                    document.getElementById('service-sidebar'),
                    document.querySelector('.admin-sidebar')
                  ].filter(Boolean).find(element => {
                    const style = getComputedStyle(element);
                    const rect = element.getBoundingClientRect();
                    return style.display !== 'none' && rect.width > 0 && rect.right > 0;
                  });
                  const navRect = nav ? nav.getBoundingClientRect() : null;
                  return {scrollY, headerTop:header.top, headerBottom:header.bottom, navTop:navRect ? navRect.top : null};
                }"""
            )
            expected_header_bottom = max(0, scroll_probe["headerBottom"] - scrolled["scrollY"])
            if (
                scrolled["scrollY"] < 20
                or abs(max(0, scrolled["headerBottom"]) - expected_header_bottom) > 3
                or (scrolled["navTop"] is not None and abs(scrolled["navTop"] - max(0, scrolled["headerBottom"])) > 3)
            ):
                errors.append({"type": "global_app_header_scroll_flow", **scroll_probe, **scrolled})
            page.evaluate("window.scrollTo(0, 0)")
            page.wait_for_timeout(80)
    except Exception as error:
        errors.append({"type": "global_app_header_unreadable", "error": str(error)[:200]})

    original_viewport = page.viewport_size
    try:
        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_timeout(250)
        mobile = page.evaluate(
            """() => {
              const headerElement = document.getElementById('global-app-header');
              const header = headerElement.getBoundingClientRect();
              const leftGroup = document.querySelector('#global-app-header .global-app-header-left').getBoundingClientRect();
              const actionGroup = document.querySelector('#global-app-header .global-app-header-actions').getBoundingClientRect();
              const visible = [...document.querySelectorAll('#global-app-header .global-app-home, #global-app-header .global-app-header-actions > :not([hidden])')]
                .filter(element => { const style=getComputedStyle(element); const rect=element.getBoundingClientRect(); return style.display !== 'none' && rect.width > 0; })
                .map(element => { const rect=element.getBoundingClientRect(); return {id:element.id || 'home', left:rect.left, right:rect.right}; });
              const overlaps = visible.some((item, index) => index > 0 && item.left < visible[index - 1].right - 1);
              return {left:header.left, right:header.right, width:header.width, viewport:document.documentElement.clientWidth, position:getComputedStyle(headerElement).position, overlaps:overlaps || leftGroup.right > actionGroup.left + 1, visible};
            }"""
        )
        if (
            abs(mobile["left"]) > 1
            or abs(mobile["right"] - mobile["viewport"]) > 1
            or mobile["position"] not in ("static", "relative")
            or mobile["overlaps"]
        ):
            errors.append({"type": "global_app_header_mobile_layout", **mobile})
    except Exception as error:
        errors.append({"type": "global_app_header_mobile_unreadable", "error": str(error)[:200]})
    finally:
        if original_viewport:
            page.set_viewport_size(original_viewport)
            page.wait_for_timeout(150)

    if route == "/dashboard":
        try:
            original_theme = page.locator("html").get_attribute("data-theme") or "dark"
            page.locator("#theme-toggle-btn").click()
            changed_theme = page.locator("html").get_attribute("data-theme")
            if changed_theme == original_theme:
                errors.append({"type": "global_app_header_theme_toggle_failed"})
            page.locator("#theme-toggle-btn").click()
        except Exception as error:
            errors.append({"type": "global_app_header_theme_toggle_unreadable", "error": str(error)[:160]})
    return errors


def check_responsive_layout(page, path):
    """와이드·노트북·태블릿·모바일에서 overflow, 겹침, 비정상 줄바꿈을 찾는다."""
    errors = []
    original_viewport = page.viewport_size

    def inspect_viewport(label):
        return page.evaluate(
            """label => {
              const viewportWidth = document.documentElement.clientWidth;
              const ignored = element => Boolean(
                element.closest('[aria-hidden="true"], [hidden], .global-service-nav-backdrop') ||
                element.closest('.service-sidebar:not(.open)') ||
                (window.matchMedia('(max-width: 1100px)').matches && element.closest('.admin-sidebar:not(.open)')) ||
                element.closest('.admin-nav-backdrop:not(.open)') ||
                // Kakao 지도는 패닝을 위해 #map 경계 밖에 타일 이미지를 배치한 뒤
                // 지도 컨테이너에서 잘라낸다. 문서 overflow가 아닌 정상 렌더링이다.
                element.closest('#map') ||
                element.matches('script, style, link, meta, path, br')
              );
              const insideHorizontalScroller = element => {
                for (let current = element.parentElement; current; current = current.parentElement) {
                  const currentStyle = getComputedStyle(current);
                  if (['auto', 'scroll'].includes(currentStyle.overflowX) && current.scrollWidth > current.clientWidth + 1) return true;
                }
                return false;
              };
              const visible = element => {
                const style = getComputedStyle(element);
                const rect = element.getBoundingClientRect();
                return !ignored(element) && style.display !== 'none' && style.visibility !== 'hidden' &&
                  Number(style.opacity || 1) > 0 && rect.width > 0 && rect.height > 0;
              };
              const selector = element => {
                if (element.id) return `#${element.id}`;
                const classes = [...element.classList].slice(0, 2).join('.');
                return `${element.tagName.toLowerCase()}${classes ? `.${classes}` : ''}`;
              };
              const ownTextNodes = element => [...element.childNodes]
                .filter(node => node.nodeType === Node.TEXT_NODE && node.textContent.trim());
              const textLineCount = element => {
                const lines = new Set();
                for (const node of ownTextNodes(element)) {
                  const range = document.createRange();
                  range.selectNodeContents(node);
                  for (const rect of range.getClientRects()) {
                    if (rect.width > .5 && rect.height > .5) lines.add(Math.round(rect.top));
                  }
                }
                return lines.size;
              };
              const intersects = (a, b) => (
                Math.min(a.right, b.right) - Math.max(a.left, b.left) > 2 &&
                Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top) > 2
              );
              const outside = [];
              const squeezed = [];
              const compactWrap = [];
              const overlaps = [];
              for (const element of document.body.querySelectorAll('*')) {
                if (!visible(element)) continue;
                const rect = element.getBoundingClientRect();
                const style = getComputedStyle(element);
                const scrollOwner = ['auto', 'scroll'].includes(style.overflowX);
                if (!scrollOwner && !insideHorizontalScroller(element) && (rect.left < -2 || rect.right > viewportWidth + 2)) {
                  if (!element.closest('.global-service-nav')) {
                    outside.push({selector: selector(element), left: Math.round(rect.left), right: Math.round(rect.right)});
                  }
                }
                const ownText = ownTextNodes(element).map(node => node.textContent.trim()).join(' ').trim();
                const lineHeight = Number.parseFloat(style.lineHeight) || Number.parseFloat(style.fontSize) * 1.4 || 20;
                const lineCount = ownText ? textLineCount(element) : 0;
                if (
                  ownText.length >= 8 && style.writingMode === 'horizontal-tb' &&
                  ((rect.width < 48 && rect.height > lineHeight * 3) || (lineCount >= 4 && ownText.length / lineCount < 3.5))
                ) {
                  squeezed.push({selector: selector(element), width: Math.round(rect.width), lines: lineCount, text: ownText.slice(0, 60)});
                }
                const compactMetric = /(?:^|[-_])(value|number|count|rate|distance|time|streak|score|total)(?:$|[-_])/i
                  .test(`${element.id} ${element.className || ''}`);
                if (compactMetric && ownText.length > 0 && ownText.length <= 14 && lineCount > 1) {
                  compactWrap.push({selector: selector(element), lines: lineCount, text: ownText.slice(0, 40)});
                }

                if (['flex', 'grid', 'inline-flex', 'inline-grid'].includes(style.display) && !element.closest('canvas, #map')) {
                  const children = [...element.children].filter(child => {
                    if (!visible(child)) return false;
                    const childStyle = getComputedStyle(child);
                    return !['absolute', 'fixed'].includes(childStyle.position) && !child.matches('script, style');
                  });
                  for (let index = 0; index < children.length; index += 1) {
                    const first = children[index].getBoundingClientRect();
                    for (let next = index + 1; next < children.length; next += 1) {
                      const second = children[next].getBoundingClientRect();
                      if (intersects(first, second)) {
                        overlaps.push({parent: selector(element), first: selector(children[index]), second: selector(children[next])});
                      }
                    }
                  }
                }
              }
              const reportLayout = location.pathname === '/report' ? (() => {
                const layout = document.querySelector('.rp-layout');
                const sidebar = document.querySelector('.rp-sidebar');
                const stats = document.querySelector('.stat-grid');
                const compactSelectors = ['.stat-value', '.growth-rate', '.growth-streak-num', '.plan-performance-value'];
                const wrappedValues = compactSelectors.flatMap(rule => [...document.querySelectorAll(rule)]
                  .filter(visible)
                  .map(element => ({selector: selector(element), lines: textLineCount(element), text: element.textContent.trim()}))
                  .filter(item => item.lines > 1));
                const streakLabel = document.querySelector('.growth-streak-lbl');
                return {
                  columns: layout ? getComputedStyle(layout).gridTemplateColumns.split(' ').length : 0,
                  summaryColumns: sidebar ? getComputedStyle(sidebar).gridTemplateColumns.split(' ').length : 0,
                  statColumns: stats ? getComputedStyle(stats).gridTemplateColumns.split(' ').length : 0,
                  sidebarWidth: sidebar ? Math.round(sidebar.getBoundingClientRect().width) : 0,
                  wrappedValues,
                  streakLabelLines: streakLabel ? textLineCount(streakLabel) : 0,
                };
              })() : null;
              const shellLayout = (() => {
                const headerElement = document.getElementById('global-app-header');
                const header = headerElement ? headerElement.getBoundingClientRect() : null;
                const desktopShell = viewportWidth > 1100;
                const sideCandidates = [
                  document.getElementById('global-service-nav'),
                  document.getElementById('service-sidebar'),
                  document.querySelector('.admin-sidebar')
                ].filter(Boolean);
                const sidebar = desktopShell ? sideCandidates.find(element => {
                  const style = getComputedStyle(element);
                  const rect = element.getBoundingClientRect();
                  return style.display !== 'none' && rect.width > 0 && rect.right > 0;
                }) : null;
                const sidebarRect = sidebar ? sidebar.getBoundingClientRect() : null;
                const workspaceLeft = sidebarRect ? Math.max(0, sidebarRect.right) : 0;
                const frameElement = document.querySelector('.global-content-frame');
                const frame = frameElement ? frameElement.getBoundingClientRect() : null;
                const expectedFrameWidth = frame ? Math.min(1280, viewportWidth - workspaceLeft) : null;
                const expectedCenter = workspaceLeft + (viewportWidth - workspaceLeft) / 2;
                return {
                  header: header ? {
                    left: Math.round(header.left * 10) / 10,
                    right: Math.round(header.right * 10) / 10,
                    position: getComputedStyle(headerElement).position
                  } : null,
                  sidebarWidth: sidebarRect ? Math.round(sidebarRect.width * 10) / 10 : 0,
                  workspaceLeft: Math.round(workspaceLeft * 10) / 10,
                  frame: frame ? {
                    left: Math.round(frame.left * 10) / 10,
                    right: Math.round(frame.right * 10) / 10,
                    width: Math.round(frame.width * 10) / 10,
                    widthError: Math.round(Math.abs(frame.width - expectedFrameWidth) * 10) / 10,
                    centerError: Math.round(Math.abs((frame.left + frame.right) / 2 - expectedCenter) * 10) / 10
                  } : null
                };
              })();
              return {
                label,
                documentOverflow: Math.max(0, document.documentElement.scrollWidth - viewportWidth),
                outside: outside.slice(0, 12),
                squeezed: squeezed.slice(0, 12),
                compactWrap: compactWrap.slice(0, 12),
                overlaps: overlaps.slice(0, 12),
                reportLayout,
                shellLayout,
              };
            }""",
            label,
        )

    try:
        viewports = [
            ("ultrawide-2560", 2560, 1400),
            ("wide-1440", 1440, 1000),
            ("desktop-1280", 1280, 900),
            ("navigation-breakpoint-1100", 1100, 900),
            ("laptop-1024", 1024, 768),
            ("tablet-768", 768, 1024),
            ("mobile-390", 390, 844),
        ]
        for label, width, height in viewports:
            page.set_viewport_size({"width": width, "height": height})
            page.wait_for_timeout(120)
            result = inspect_viewport(label)
            has_layout_error = any([
                result["documentOverflow"] > 1,
                result["outside"],
                result["squeezed"],
                result["compactWrap"],
                result["overlaps"],
            ])
            report_layout = result.get("reportLayout")
            if report_layout:
                expected_summary_columns = 2 if width > 980 else 1
                expected_stat_columns = 2 if width <= 760 else 5
                has_layout_error = has_layout_error or any([
                    report_layout["columns"] != 1,
                    report_layout["summaryColumns"] != expected_summary_columns,
                    report_layout["statColumns"] != expected_stat_columns,
                    report_layout["wrappedValues"],
                    report_layout["streakLabelLines"] > 2,
                ])
            shell_layout = result.get("shellLayout") or {}
            shell_header = shell_layout.get("header")
            shell_frame = shell_layout.get("frame")
            if shell_header:
                has_layout_error = has_layout_error or any([
                    abs(shell_header["left"]) > 1,
                    abs(shell_header["right"] - width) > 1,
                    shell_header["position"] not in ("static", "relative"),
                ])
            if shell_frame:
                has_layout_error = has_layout_error or any([
                    shell_frame["widthError"] > 2,
                    shell_frame["centerError"] > 2,
                    shell_frame["left"] < shell_layout["workspaceLeft"] - 2,
                    shell_frame["right"] > width + 2,
                ])
            if has_layout_error:
                errors.append({"type": "responsive_layout", **result})

        if path.split("?", 1)[0] == "/training-log":
            page.set_viewport_size({"width": 390, "height": 844})
            page.wait_for_timeout(120)
            page.evaluate("showReportToast('2026-08-08', false, 1)")
            toast = page.locator("#report-toast")
            message = page.locator("#report-toast .report-toast-message")
            toast_box = toast.bounding_box()
            message_box = message.bounding_box()
            if (
                not toast_box or not message_box
                or toast_box["x"] < -1
                or toast_box["x"] + toast_box["width"] > 391
                or message_box["width"] < 200
                or message_box["height"] > 100
            ):
                errors.append({
                    "type": "training_log_mobile_toast_layout",
                    "toast": toast_box,
                    "message": message_box,
                })
            toast.evaluate("element => element.remove()")
    except Exception as error:
        errors.append({"type": "responsive_layout_check_failed", "error": str(error)[:200]})
    finally:
        if original_viewport:
            page.set_viewport_size(original_viewport)
            page.wait_for_timeout(150)
    return errors


def check_information_guide_interactions(page, path):
    """정보·도움 화면의 필터와 선택 결과가 실제 DOM 상태를 바꾸는지 읽기 전용으로 확인한다."""
    actions, errors = [], []
    try:
        if path == "/drill":
            page.locator("#drill-filter-details > summary").click()
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
            swimwear_text = page.locator("#tab-swimwear").inner_text()
            swimwear_required_texts = [
                "브랜드별 공식 사이즈표",
                "공식표 표시 단위",
                "신체 치수 입력 단위",
                "내 수영복 기준 브랜드별 사이즈 참고 비교",
                "구매 확정값이 아닙니다",
                "Speedo",
                "arena",
                "TYR",
                "Mizuno",
                "Nike Swim",
            ]
            missing_swimwear_texts = [
                text for text in swimwear_required_texts if text not in swimwear_text
            ]
            if missing_swimwear_texts:
                raise AssertionError(
                    "수영복 탭 필수 문구 누락: " + ", ".join(missing_swimwear_texts)
                )
            page.click("[data-suit-purpose='race']")
            result = page.locator("#suit-recommendation")
            if not page.locator("#tab-swimwear").is_visible() or "대회용 선택" not in result.inner_text():
                raise AssertionError("수영복 목적별 안내가 표시되지 않음")
            actions.append({"action": "수영복 구매 탭·대회 목적 선택", "status": "ok"})

            page.click("[data-size-profile='men']")
            page.click("[data-size-brand='arena']")
            if "남성 일반 수영복" not in page.locator("#brand-chart-title").inner_text():
                raise AssertionError("브랜드별 남성 사이즈표가 전환되지 않음")
            if "arena 국제몰(en_ROW)" not in page.locator("#brand-chart-region").inner_text():
                raise AssertionError("브랜드 공식표 기준 지역이 표시되지 않음")
            if page.locator("#brand-size-body tr").count() < 5:
                raise AssertionError("브랜드 사이즈표 행이 부족함")
            page.click("[data-chart-unit='in']")
            if "가슴 (in)" not in page.locator("#brand-size-head").inner_text() or "33.1" not in page.locator("#brand-size-body tr").first.inner_text():
                raise AssertionError("공식 사이즈표 cm→inch 전환이 동작하지 않음")
            page.click("[data-chart-unit='cm']")
            actions.append({"action": "브랜드·수영복 유형별 공식 사이즈표", "status": "ok"})

            page.select_option("#recommender-profile", "women")
            page.select_option("#current-brand", "auto")
            page.fill("#current-model", "미즈노 엑서수트 N2MAD785")
            page.fill("#current-size", "M")
            page.select_option("#current-size-region", "jp")
            page.select_option("#target-purchase-region", "kr")
            page.select_option("#measurement-unit", "in")
            page.fill("#measure-bust", "32.7")
            page.fill("#measure-waist", "25.2")
            page.fill("#measure-hip", "35.8")
            page.fill("#measure-torso", "60.6")
            if "83.1 cm" not in page.locator("#measure-bust-conversion").inner_text():
                raise AssertionError("inch 입력의 cm 즉시 환산이 표시되지 않음")
            page.select_option("#measurement-unit", "cm")
            if page.locator("#measure-bust").input_value() != "83.1":
                raise AssertionError("inch→cm 단위 전환 시 물리적 치수가 보존되지 않음")
            page.select_option("#measurement-unit", "in")
            if page.locator("#measure-bust").input_value() != "32.7":
                raise AssertionError("cm→inch 왕복 단위 전환 시 물리적 치수가 보존되지 않음")
            page.check("#size-reference-confirm")
            page.click(".recommend-submit")
            if not page.locator("#recommend-result").is_visible() or page.locator("#recommend-grid .recommend-card").count() != 5:
                raise AssertionError("현재 모델 기반 브랜드별 참고 후보 5개가 표시되지 않음")
            summary_text = page.locator("#recommend-summary").inner_text()
            if "실측 4개 반영" not in summary_text or "inch 입력 → cm 정규화" not in summary_text or "구매 예정 지역: 대한민국(KR)" not in summary_text:
                raise AssertionError("실측 범위·입력 단위 정규화와 구매 예정 국가가 표시되지 않음")
            if page.locator("#recommend-grid .region-mismatch").count() < 1:
                raise AssertionError("공식표와 구매 지역 불일치가 표시되지 않음")
            actions.append({"action": "현재 모델·inch 실측 기반 국가별 사이즈 참고 비교", "status": "ok"})

            page.fill("#current-model", "Speedo Endurance+")
            page.fill("#current-size", "30")
            page.select_option("#current-size-region", "kr")
            for field_id in ["measure-bust", "measure-waist", "measure-hip", "measure-torso"]:
                page.fill(f"#{field_id}", "")
            page.click(".recommend-submit")
            mismatch_message = page.locator("#recommend-message").inner_text()
            if (
                "라벨만으로 환산하지 않습니다" not in mismatch_message
                or page.locator("#recommend-result").is_visible()
            ):
                raise AssertionError("국가별 라벨 불일치 환산이 차단되지 않음")
            actions.append({"action": "현재 사이즈 라벨 국가 불일치 환산 차단", "status": "ok"})

            page.fill("#current-model", "Speedo Fastskin LZR")
            page.select_option("#current-size-region", "us")
            page.click(".recommend-submit")
            if "레이싱·테크수트 계열" not in page.locator("#recommend-message").inner_text():
                raise AssertionError("레이싱 수트 전용 표 안전 경계가 표시되지 않음")
            actions.append({"action": "레이싱 수트 일반표 교차 추천 차단", "status": "ok"})
            page.click(".tab-btn[data-tab='all']")
        elif path == "/faq":
            query = "수영복"
            page.fill("#search", query)
            visible = page.locator(".faq-item:visible")
            visible_count = visible.count()
            total_count = page.locator(".faq-item").count()
            counter_text = page.locator("#search-count").inner_text()
            if visible_count < 1 or visible_count >= total_count or counter_text != f"{visible_count}건":
                raise AssertionError("수영복 FAQ 검색 결과가 표시되지 않음")
            for index in range(visible_count):
                item = visible.nth(index)
                searchable_text = " ".join([
                    item.get_attribute("data-q") or "",
                    item.locator(".faq-a").text_content() or "",
                ]).lower()
                if query not in searchable_text:
                    raise AssertionError("수영복과 무관한 FAQ 항목이 검색 결과에 남아 있음")
            actions.append({"action": "수영복 FAQ 검색", "status": "ok"})
            page.fill("#search", "")
    except Exception as error:
        errors.append({"type": "information_guide_interaction_failed", "path": path, "error": str(error)[:200]})
    return actions, errors


def check_clarity_ui_interactions(page, path):
    """핵심 행동 우선 UI의 접기·검색·모드 전환이 기존 기능을 숨기거나 끊지 않는지 확인한다."""
    actions, errors = [], []
    try:
        if path == "/landing":
            details = page.locator(".home-stat-details")
            if details.get_attribute("open") is not None:
                raise AssertionError("보조 누적 수치가 최초 진입부터 펼쳐져 있음")
            details.locator("summary").click()
            if not page.locator("#home-month-distance").is_visible() or not page.locator("#home-total-distance").is_visible():
                raise AssertionError("누적 수치 펼치기 실패")
            details.locator("summary").click()
            search = page.locator("#landing-nav-search")
            search.fill("수영복")
            target = page.locator("#service-sidebar .service-nav-link[href='/equipment?tab=swimwear']")
            if not target.is_visible():
                raise AssertionError("랜딩 기능 검색 결과가 보이지 않음")
            search.fill("")
            actions.append({"action": "랜딩 보조 수치 접기·기능 검색", "status": "ok"})
        elif path == "/dashboard":
            readiness = page.locator(".readiness-card")
            if readiness.get_attribute("open") is not None:
                raise AssertionError("준비도 입력이 최초 진입부터 펼쳐져 있음")
            readiness.locator("summary").click()
            if not page.locator("#readiness-form").is_visible():
                raise AssertionError("준비도 입력 펼치기 실패")
            readiness.locator("summary").click()
            page.locator(".advisor-more > summary").click()
            if not page.locator("#advisor-pool").is_visible():
                raise AssertionError("추천 기준 펼치기 실패")
            page.locator(".advisor-more > summary").click()
            actions.append({"action": "준비도·추천 기준 점진적 공개", "status": "ok"})
        elif path == "/training-log":
            page.set_viewport_size({"width": 390, "height": 844})
            page.evaluate("window.scrollTo(0, 0)")
            primary_action = page.locator("#btn-open-modal")
            primary_box = primary_action.bounding_box()
            if not primary_action.is_visible() or not primary_box or primary_box["y"] > 260:
                raise AssertionError("기록 추가가 모바일 첫 화면의 핵심 행동으로 보이지 않음")
            menu = page.locator("#log-import-menu")
            if menu.get_attribute("open") is not None:
                raise AssertionError("가져오기 메뉴가 최초 진입부터 펼쳐져 있음")
            menu.locator("summary").click()
            if not page.locator("#btn-open-screenshot").is_visible() or not page.locator("#btn-open-import").is_disabled():
                raise AssertionError("스크린샷·준비 중 기능 구분 실패")
            page.locator("#btn-open-screenshot").click()
            if not page.locator("#screenshot-modal-backdrop").is_visible():
                raise AssertionError("스크린샷 등록 열기 실패")
            page.locator("#screenshot-pick-cancel").click()
            actions.append({"action": "훈련 일지 상단 기록 추가·가져오기 메뉴·스크린샷 등록", "status": "ok"})
        elif path == "/plan":
            page.locator("[data-plan-mode='builder']").click()
            if not page.locator("#tab-builder").is_visible():
                raise AssertionError("직접 구성 모드 전환 실패")
            page.locator("[data-plan-mode='purpose']").click()
            page.select_option("#plan-purpose-select", "health")
            if not page.locator("#tab-health").is_visible() or page.locator("#plan-purpose-select").input_value() != "health":
                raise AssertionError("추천 플랜 목적 전환 실패")
            context = page.locator(".plan-context-details")
            context.locator("summary").click()
            page.locator("[data-pool-length='50']").click()
            if "50m 풀" not in page.locator("#plan-context-summary").inner_text():
                raise AssertionError("훈련 기준 요약 갱신 실패")
            page.locator("[data-pool-length='25']").click()
            context.locator("summary").click()
            actions.append({"action": "플랜 방식·목적·훈련 기준 전환", "status": "ok"})
    except Exception as error:
        errors.append({"type": "clarity_ui_interaction_failed", "error": str(error)[:220]})
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


def install_qa_tracking_marker(context):
    """Mark QA analytics without rewriting request headers or auth cookies."""
    context.add_cookies([{
        "name": "swimmate_qa_run",
        "value": "1",
        "url": BASE,
        "sameSite": "Lax",
    }])


def check_public_promotion_pages(context):
    """Render the two public promotion pages with deterministic API fixtures.

    The production UI is exercised without leaving a permanent public QA share or
    club behind. Authenticated API scenarios separately verify real DB writes,
    permissions, revocation and cleanup.
    """
    result_payload = {
        "result": {
            "year": 2026, "month": 8, "total_distance": 12800,
            "total_count": 8, "avg_distance": 1600, "growth_rate": 12.5,
            "by_stroke": {"freestyle": 8000, "backstroke": 2400, "breaststroke": 2400},
            "benchmark_performance": {"personal_bests": 2},
        },
        "display_name": None,
        "privacy": "훈련 위치·심박·메모·원본 스크린샷은 포함되지 않습니다.",
    }
    club_payload = {
        "club": {"name": "SwimMate QA Club", "description": "함께 꾸준히 수영하는 클럽", "default_pool_length": 25},
        "campaign": {
            "headline": "이번 달 함께 100km를 완주해요", "target_distance": 100000,
            "total_distance": 62500, "progress_rate": 63, "start_date": "2026-08-01",
            "end_date": "2026-08-31", "member_count": 12,
        },
        "class": {"name": "저녁 마스터즈", "level": "중급", "goal": "체력 향상", "pool_length": 25, "invite_code": "LANE-QATEST"},
        "privacy": "직접 동의한 회원의 거리만 익명 합산하며 이름과 개인 훈련 상세는 공개하지 않습니다.",
    }
    cases = [
        ("/result/qa-ui-contract", "공개 결과 카드", result_payload,
         ["#result-card", "#distance", "#download", "#share", "#copy"],
         ["12,800", "수영 훈련 기록", "원본 스크린샷은 포함되지 않습니다"]),
        ("/club/qa-ui-contract", "공개 클럽 초대", club_payload,
         ["#public-shell", "#headline", "#progress", "#join", "#code", "#qr", "#join-link"],
         ["SwimMate QA Club", "62,500m", "LANE-QATEST", "직접 동의한 회원"]),
    ]

    def json_fixture(payload):
        body = json.dumps(payload, ensure_ascii=False)

        def fulfill(route, _request=None):
            route.fulfill(
                status=200,
                content_type="application/json; charset=utf-8",
                body=body,
            )

        return fulfill

    for path, label, fixture, selectors, texts in cases:
        page = context.new_page()
        entry = {"page": path, "label": label, "actions": [], "page_errors": []}
        try:
            if path.startswith("/result/"):
                page.route(
                    "**/api/promotion/public/results/qa-ui-contract",
                    json_fixture(fixture),
                )
            else:
                page.route(
                    "**/api/promotion/public/clubs/qa-ui-contract",
                    json_fixture(fixture),
                )
                page.route(
                    "**/api/promotion/public/clubs/qa-ui-contract/qr.svg",
                    lambda route: route.fulfill(
                        status=200, content_type="image/svg+xml",
                        body='<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64"><rect width="64" height="64" fill="#08b9d6"/></svg>',
                    ),
                )
            page.goto(f"{BASE}{path}", wait_until="domcontentloaded", timeout=30000)
            page.wait_for_function("document.body.innerText.includes('12,800') || document.body.innerText.includes('62,500m')", timeout=10000)
            body_text = page.locator("body").inner_text()
            missing = [selector for selector in selectors if page.locator(selector).count() != 1 or not page.locator(selector).is_visible()]
            missing_text = [text for text in texts if text not in body_text]
            if missing or missing_text:
                entry["page_errors"].append({"phase": "expectations", "missing": missing, "missing_text": missing_text})
            elif path.startswith("/result/"):
                if not page.evaluate("makeCanvas().toDataURL('image/png').startsWith('data:image/png')"):
                    entry["page_errors"].append({"phase": "png", "error": "결과 카드 PNG canvas 생성 실패"})
                else:
                    entry["actions"].append({"action": "익명 결과 카드 렌더·PNG 생성", "status": "ok"})
            else:
                href = page.locator("#join-link").get_attribute("href") or ""
                if "next=%2Fclubs%3Finvite%3DLANE-QATEST" not in href:
                    entry["page_errors"].append({"phase": "invite", "error": f"로그인 후 초대 경로 불일치: {href}"})
                else:
                    entry["actions"].append({"action": "클럽 목표·초대 코드·QR 렌더", "status": "ok"})
            page.set_viewport_size({"width": 390, "height": 844})
            page.wait_for_timeout(250)
            overflow = page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
            if overflow > 1:
                entry["page_errors"].append({"phase": "mobile_layout", "error": f"가로 넘침 {overflow}px"})
            else:
                entry["actions"].append({"action": "390px 모바일 가로 넘침 없음", "status": "ok"})
        except Exception as error:
            entry["page_errors"].append({"phase": "load", "error": str(error)[:240]})
        finally:
            try:
                page.close()
            except Exception:
                pass
        RESULTS.append(entry)
        mark = "FAIL" if entry["page_errors"] else "PASS"
        print(f"[{label}] {path} {mark}")


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
            # 공통 헤더와 서비스 내비게이션은 전용 좌표·경로·드로어 검사에서
            # 이미 검증한다. 페이지 이동 뒤 DOM이 재주입되는 이 요소들을 저장한
            # nth 인덱스로 다시 클릭하면 다른 버튼(특히 로그아웃)을 누를 수 있으므로
            # 일반 콘텐츠 상호작용 대상에서는 제외한다.
            if selector == CLICKABLE_SELECTOR and h.evaluate(
                "element => Boolean(element.closest('#global-app-header, #global-service-nav, #service-sidebar'))"
            ):
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
    expectation_errors.extend(check_global_app_header(page, path))
    expectation_errors.extend(check_service_navigation(page, path))
    expectation_errors.extend(check_responsive_layout(page, path))
    expectation_errors.extend(check_home_link_targets(page))
    if path in {"/landing", "/dashboard", "/training-log", "/plan"}:
        clarity_actions, clarity_errors = check_clarity_ui_interactions(page, path)
        entry["actions"].extend(clarity_actions)
        expectation_errors.extend(clarity_errors)
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
        # 서비스 워커가 API 요청을 먼저 가로채면 Playwright route fixture와
        # 응답 오류 수집이 무력화된다. 운영 QA에서는 네트워크를 직접 관찰한다.
        context = browser.new_context(
            ignore_https_errors=True,
            viewport={"width": 1280, "height": 900},
            service_workers="block",
        )
        install_qa_tracking_marker(context)
        check_public_demo_entry(context)
        check_public_promotion_pages(context)
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
            admin_context = browser.new_context(
                ignore_https_errors=True,
                viewport={"width": 1280, "height": 900},
                service_workers="block",
            )
            install_qa_tracking_marker(admin_context)
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
