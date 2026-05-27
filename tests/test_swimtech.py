"""
SwimTech E2E Test Suite — pytest-playwright

Setup:
    pip install pytest playwright pytest-playwright pytest-html
    playwright install chromium

Run:
    pytest tests/test_swimtech.py -v --html=tests/report.html --self-contained-html

    # headed mode (browser visible):
    pytest tests/test_swimtech.py -v --headed --html=tests/report.html --self-contained-html

--------------------------------------------------------------------------------
GUIDE FOR CONTRIBUTORS
When adding a new page or feature, add the corresponding test case(s) to this
file, then run `tests/run_tests.bat` from the project root to verify immediately.

Test naming convention:
    test_<page>_<what_is_verified>(page: Page)

Each new route (e.g. /settings, /profile) should have at minimum:
    1. A "load" test — confirms the page renders key elements
    2. Interaction tests — covers primary user actions on that page

After adding tests, run:
    cd C:\swim
    tests\run_tests.bat
--------------------------------------------------------------------------------
"""

import re
import pytest
from datetime import date
from pathlib import Path
from playwright.sync_api import Page, BrowserContext, expect

# ── constants ──────────────────────────────────────────────────────────────
BASE_URL    = "https://localhost"
TEST_USER   = "admin"
TEST_PASS   = "swimtech1234"
SHOT_DIR    = Path(__file__).parent / "screenshots" / date.today().strftime("%Y%m%d")
SHOT_DIR.mkdir(parents=True, exist_ok=True)

from conftest import COACH_ID, COACH_PW, STUDENT_ID, STUDENT_PW  # noqa: E402


# ── fixtures ───────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def browser_context_args(browser_context_args):
    """SSL 인증서 무시, 뷰포트 설정."""
    return {
        **browser_context_args,
        "ignore_https_errors": True,
        "viewport": {"width": 1280, "height": 800},
    }


@pytest.fixture(scope="session")
def logged_in_state(browser, browser_context_args):
    """세션 단위 로그인 — 쿠키/스토리지를 재사용해 매 테스트 로그인 비용 제거."""
    ctx: BrowserContext = browser.new_context(**browser_context_args)
    page = ctx.new_page()

    page.goto(f"{BASE_URL}/login", wait_until="domcontentloaded")
    page.fill("#username", TEST_USER)
    page.fill("#password", TEST_PASS)
    page.click("#login-btn")
    # 로그인 성공 → /landing 또는 /onboarding 으로 리디렉트
    page.wait_for_url(re.compile(r"/(landing|onboarding|nickname|$)"), timeout=10_000)

    if "/onboarding" in page.url or "/nickname" in page.url:
        page.evaluate("localStorage.setItem('swimtech_onboarded', 'true')")
        page.goto(f"{BASE_URL}/landing", wait_until="domcontentloaded")

    state = ctx.storage_state()
    page.close()
    ctx.close()
    return state


@pytest.fixture()
def page(browser, browser_context_args, logged_in_state) -> Page:
    """각 테스트에 로그인된 신규 탭 제공."""
    ctx: BrowserContext = browser.new_context(
        **browser_context_args,
        storage_state=logged_in_state,
    )
    p = ctx.new_page()
    p.goto(f"{BASE_URL}/landing", wait_until="domcontentloaded")
    yield p
    p.close()
    ctx.close()


def shot(page: Page, name: str):
    path = SHOT_DIR / f"{name}.png"
    page.screenshot(path=str(path), full_page=True)
    return path


# ── helpers ────────────────────────────────────────────────────────────────

def goto(page: Page, path: str):
    page.goto(f"{BASE_URL}{path}", wait_until="domcontentloaded")


# ══════════════════════════════════════════════════════════════════════════
# 1. /landing
# ══════════════════════════════════════════════════════════════════════════

def test_landing_load(page: Page):
    goto(page, "/landing")

    # 헤더 로고
    expect(page.locator(".logo").first).to_be_visible()

    # 주요 카드 버튼 6개 이상
    cards = page.locator(".choice-card")
    assert cards.count() >= 6, f"choice-card count: {cards.count()}"

    # 핵심 CTA 버튼 텍스트 확인
    btn_texts = page.locator(".choice-btn").all_text_contents()
    # 영상 분석 카드는 숨김 처리됨 — AI 코치/수영장 버튼은 활성화
    assert any("대화" in t for t in btn_texts), "AI코치 버튼 없음"
    assert any("보기" in t or "찾기" in t for t in btn_texts), "수영장/드릴 버튼 없음"

    shot(page, "01_landing")


# ══════════════════════════════════════════════════════════════════════════
# 2. /login
# ══════════════════════════════════════════════════════════════════════════

def test_login_form_visible(browser, browser_context_args):
    """비로그인 상태에서 폼 요소 확인."""
    ctx = browser.new_context(**browser_context_args)
    page = ctx.new_page()
    try:
        goto(page, "/login")
        expect(page.locator("#username")).to_be_visible()
        expect(page.locator("#password")).to_be_visible()
        expect(page.locator("#login-btn")).to_be_visible()
        shot(page, "02_login_form")
    finally:
        page.close()
        ctx.close()


def test_login_success(browser, browser_context_args):
    """실제 로그인 후 /landing 리디렉트 확인."""
    ctx = browser.new_context(**browser_context_args)
    page = ctx.new_page()
    try:
        goto(page, "/login")
        page.fill("#username", TEST_USER)
        page.fill("#password", TEST_PASS)
        page.click("#login-btn")
        page.wait_for_url(re.compile(r"/(landing|onboarding|nickname|$)"), timeout=10_000)
        shot(page, "02_login_success")
        assert "/login" not in page.url, f"로그인 후 /login 잔류: {page.url}"
    finally:
        page.close()
        ctx.close()


def test_login_wrong_password(browser, browser_context_args):
    """잘못된 비밀번호 → 에러 메시지 표시."""
    ctx = browser.new_context(**browser_context_args)
    page = ctx.new_page()
    try:
        goto(page, "/login")
        page.fill("#username", TEST_USER)
        page.fill("#password", "wrong_password_xyz")
        page.click("#login-btn")
        page.wait_for_timeout(1500)
        error = page.locator("#error-msg")
        expect(error).to_be_visible()
        assert error.inner_text().strip() != "", "에러 메시지가 비어있음"
        shot(page, "02_login_error")
    finally:
        page.close()
        ctx.close()


# ══════════════════════════════════════════════════════════════════════════
# 3. /upload
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.skip(reason="AI 분석 기능 정식 배포 전 비활성화 - 내부 테스트 전용")
def test_upload_ui(page: Page):
    page.evaluate("""() => {
        sessionStorage.setItem('swimtech_stroke', 'freestyle');
        sessionStorage.setItem('swimtech_context', 'free_swim');
        sessionStorage.setItem('swimtech_purpose', 'health');
    }""")
    page.goto("https://localhost/upload")

    expect(page.locator("#upload-zone")).to_be_visible()
    # 파일 input은 hidden이지만 DOM에 존재해야 함
    expect(page.locator("#file-input")).to_have_count(1)

    shot(page, "03_upload")


@pytest.mark.skip(reason="AI 분석 기능 정식 배포 전 비활성화 - 내부 테스트 전용")
def test_upload_zone_drag_style(page: Page):
    """드래그 존 호버 시 drag-over 클래스 진입 여부."""
    page.evaluate("""() => {
        sessionStorage.setItem('swimtech_stroke', 'freestyle');
        sessionStorage.setItem('swimtech_context', 'free_swim');
        sessionStorage.setItem('swimtech_purpose', 'health');
    }""")
    page.goto("https://localhost/upload")
    zone = page.locator("#upload-zone")
    zone.dispatch_event("dragenter")
    page.wait_for_timeout(300)
    shot(page, "03_upload_dragenter")


def test_upload_redirects_non_admin(browser, browser_context_args):
    """비관리자 사용자의 /upload 접근 → /landing 리다이렉트 확인.

    비관리자 계정을 등록하고(이미 존재하면 무시),
    로그인 후 /upload 접근 시 /landing 리다이렉트를 검증합니다.
    """
    import json as _json
    ctx = browser.new_context(**browser_context_args)
    page = ctx.new_page()
    try:
        # 비관리자 테스트 계정 준비 (이미 존재해도 무시)
        ctx.request.post(
            f"{BASE_URL}/auth/register",
            data=_json.dumps({
                "name": "NoAdmin Test",
                "email": "nonadmin01@example.com",
                "username": "nonadmin01",
                "password": "Nonadmin1",
            }),
            headers={"Content-Type": "application/json"},
        )

        # 로그인
        page.goto(f"{BASE_URL}/login", wait_until="domcontentloaded")
        page.fill("#username", "nonadmin01")
        page.fill("#password", "Nonadmin1")
        page.click("#login-btn")
        page.wait_for_url(re.compile(r"/(landing|onboarding|$)"), timeout=10_000)

        # /upload 접근 → /landing 리다이렉트 확인
        page.goto(f"{BASE_URL}/upload", wait_until="domcontentloaded")
        assert "/landing" in page.url, (
            f"/upload는 /landing으로 리다이렉트되어야 함, 현재 URL: {page.url}"
        )
        shot(page, "03_upload_redirect_nonadmin")
    finally:
        page.close()
        ctx.close()


# ══════════════════════════════════════════════════════════════════════════
# 4. /dashboard
# ══════════════════════════════════════════════════════════════════════════

def test_dashboard_cards(page: Page):
    """AI 분析 섹션은 숨겨지고 뱃지 섹션과 준비 중 안내는 표시 확인."""
    goto(page, "/dashboard")
    page.wait_for_timeout(1000)

    # 뱃지 섹션은 표시
    expect(page.locator(".mini-badge-row")).to_be_visible()
    # 준비 중 안내 표시
    expect(page.locator("#analysis-coming-soon")).to_be_visible()
    # 분析 카드 섹션은 숨김
    expect(page.locator(".summary-cards")).to_be_hidden()

    shot(page, "04_dashboard_cards")


def test_dashboard_charts(page: Page):
    """차트 섹션 숨김 확인."""
    goto(page, "/dashboard")

    expect(page.locator(".charts-grid")).to_be_hidden()

    shot(page, "04_dashboard_charts")


def test_dashboard_history(page: Page):
    """분析 히스토리 섹션 숨김, 대시보드 기본 구조 확인."""
    goto(page, "/dashboard")
    page.wait_for_timeout(500)
    # 분析 테이블 숨김
    expect(page.locator(".table-card")).to_be_hidden()
    # 페이지 구조 유지
    expect(page.locator(".dash-page")).to_be_visible()
    shot(page, "04_dashboard_history")


# ══════════════════════════════════════════════════════════════════════════
# 5. /chat
# ══════════════════════════════════════════════════════════════════════════

def test_chat_load(page: Page):
    goto(page, "/chat")
    page.wait_for_timeout(1000)

    expect(page.locator("#chat-input")).to_be_visible()
    expect(page.locator("#send-btn")).to_be_visible()

    shot(page, "05_chat_load")


def test_chat_sample_cards(page: Page):
    """예시 질문 카드 1개 이상 존재 확인."""
    goto(page, "/chat")
    page.wait_for_timeout(1000)

    samples = page.locator(".sample-card")
    assert samples.count() >= 1, f"sample-card count: {samples.count()}"

    shot(page, "05_chat_samples")


def test_chat_send_message(page: Page):
    """입력창에 메시지 입력 후 전송 버튼 클릭."""
    goto(page, "/chat")
    page.wait_for_timeout(1000)

    page.fill("#chat-input", "자유형 팔동작 교정 방법 알려줘")
    page.click("#send-btn")
    page.wait_for_timeout(1000)

    shot(page, "05_chat_send")


# ══════════════════════════════════════════════════════════════════════════
# 6. /pool
# ══════════════════════════════════════════════════════════════════════════

def test_pool_map_container(page: Page):
    """카카오맵 컨테이너 렌더링 확인."""
    goto(page, "/pool")
    page.wait_for_timeout(2000)

    expect(page.locator("#map")).to_be_visible()

    shot(page, "06_pool_map")


def test_pool_search_ui(page: Page):
    """검색 입력창과 버튼 존재 확인."""
    goto(page, "/pool")
    page.wait_for_timeout(1000)

    expect(page.locator("#search-input")).to_be_visible()
    expect(page.locator(".search-btn").first).to_be_visible()

    shot(page, "06_pool_search")


# 헤드리스 브라우저 환경에서는 카카오맵이 canvas를 생성하지 않음
# (외부 지도 SDK가 GPU/렌더링 컨텍스트 없이 동작하지 않는 환경 이슈)
@pytest.mark.skip(reason="헤드리스 브라우저에서 카카오맵 canvas 미렌더링 — 환경 이슈로 스킵")
def test_pool_map_canvas_rendered(page: Page):
    """카카오맵 canvas 태그 생성 여부 (스크립트 로드 결과)."""
    goto(page, "/pool")
    page.wait_for_timeout(3000)

    canvas_count = page.locator("#map canvas").count()
    assert canvas_count >= 1, (
        f"카카오맵 canvas 미생성 (count={canvas_count}). "
        "KAKAO_JS_KEY 또는 네트워크 확인 필요."
    )
    shot(page, "06_pool_map_canvas")


# ══════════════════════════════════════════════════════════════════════════
# 7. /drill
# ══════════════════════════════════════════════════════════════════════════

def test_drill_tabs_visible(page: Page):
    goto(page, "/drill")
    tabs = page.locator(".tab-btn")
    assert tabs.count() == 4, f"tab-btn count: {tabs.count()}"

    for label in ["자유형", "배영", "평영", "접영"]:
        expect(page.get_by_role("button", name=re.compile(label))).to_be_visible()

    shot(page, "07_drill_tabs")


def test_drill_tab_switch(page: Page):
    """탭 클릭 → active 클래스 이동 확인."""
    goto(page, "/drill")

    backstroke_tab = page.locator(".tab-btn[data-tab='backstroke']")
    backstroke_tab.click()
    page.wait_for_timeout(400)

    expect(backstroke_tab).to_have_class(re.compile(r"\bactive\b"))
    expect(page.locator(".tab-btn[data-tab='freestyle']")).not_to_have_class(re.compile(r"\bactive\b"))

    shot(page, "07_drill_tab_switch")


def test_drill_cards_visible(page: Page):
    goto(page, "/drill")
    page.wait_for_timeout(500)
    cards = page.locator(".drill-card")
    assert cards.count() >= 1, "드릴 카드 없음"
    shot(page, "07_drill_cards")


# ══════════════════════════════════════════════════════════════════════════
# 8. /faq
# ══════════════════════════════════════════════════════════════════════════

def test_faq_load(page: Page):
    goto(page, "/faq")
    expect(page.locator("#faq-list")).to_be_visible()
    assert page.locator(".faq-item").count() >= 1
    shot(page, "08_faq_load")


def test_faq_accordion(page: Page):
    """첫 번째 표시된 질문 클릭 → 답변 펼쳐짐 확인."""
    goto(page, "/faq")

    first_item = page.locator(".faq-item:visible").first
    first_item.locator(".faq-q").click()
    page.wait_for_timeout(400)

    first_a = first_item.locator(".faq-a")
    expect(first_a).not_to_have_css("display", "none")

    shot(page, "08_faq_accordion_open")


def test_faq_search(page: Page):
    """검색어 입력 → 관련 항목만 필터링."""
    goto(page, "/faq")

    page.fill("#search", "촬영")
    page.wait_for_timeout(400)

    visible_items = [
        item for item in page.locator(".faq-item").all()
        if item.is_visible()
    ]
    assert len(visible_items) >= 1, "검색 후 표시 항목 없음"

    shot(page, "08_faq_search")


# ══════════════════════════════════════════════════════════════════════════
# 9. /glossary
# ══════════════════════════════════════════════════════════════════════════

def test_glossary_load(page: Page):
    goto(page, "/glossary")
    page.wait_for_timeout(500)
    expect(page.locator("#cards-container")).to_be_visible()
    shot(page, "09_glossary_load")


def test_glossary_search(page: Page):
    """검색어 입력 → 카드 필터링."""
    goto(page, "/glossary")
    page.wait_for_timeout(500)

    page.fill("#search-input", "자유형")
    page.wait_for_timeout(400)

    cards = page.locator(".term-card")
    visible = [c for c in cards.all() if c.is_visible()]
    assert len(visible) >= 1, "검색 후 term-card 없음"

    # 빈 상태 메시지가 숨겨져 있어야 함
    expect(page.locator("#empty-state")).to_have_class(re.compile(r"\bhidden\b"))

    shot(page, "09_glossary_search")


def test_glossary_no_result(page: Page):
    """결과 없는 검색 → empty-state 노출."""
    goto(page, "/glossary")
    page.wait_for_timeout(500)

    page.fill("#search-input", "xyzqwerty12345")
    page.wait_for_timeout(400)

    expect(page.locator("#empty-state")).not_to_have_class(re.compile(r"\bhidden\b"))

    shot(page, "09_glossary_no_result")


# ══════════════════════════════════════════════════════════════════════════
# 10. /badges
# ══════════════════════════════════════════════════════════════════════════

def test_badges_load(page: Page):
    goto(page, "/badges")
    page.wait_for_timeout(1500)

    expect(page.locator("#earned-grid")).to_be_visible()
    expect(page.locator("#locked-grid")).to_be_visible()

    shot(page, "10_badges_load")


def test_badges_progress_bar(page: Page):
    """획득 진행 바 및 카운트 렌더링 확인."""
    goto(page, "/badges")
    page.wait_for_timeout(1500)

    expect(page.locator("#prog-bar")).to_be_visible()
    expect(page.locator("#prog-earned")).to_be_visible()
    expect(page.locator("#prog-total")).to_be_visible()

    shot(page, "10_badges_progress")


def test_badges_cards_exist(page: Page):
    """뱃지 카드 1개 이상 렌더링 확인."""
    goto(page, "/badges")
    page.wait_for_timeout(1500)

    cards = page.locator(".badge-card")
    assert cards.count() >= 1, f"badge-card count: {cards.count()}"

    shot(page, "10_badges_cards")


# ══════════════════════════════════════════════════════════════════════════
# 11. /changelog
# ══════════════════════════════════════════════════════════════════════════

def test_changelog_load(page: Page):
    """릴리즈 노트 페이지 로드 — 헤더 및 컨테이너 렌더링 확인."""
    goto(page, "/changelog")

    expect(page.locator(".cl-header h1")).to_be_visible()
    # 로딩·타임라인·에러 중 하나 이상 노출
    loading  = page.locator("#cl-loading")
    timeline = page.locator("#cl-timeline")
    error    = page.locator("#cl-error")
    page.wait_for_timeout(3000)

    visible = (
        timeline.is_visible()
        or error.is_visible()
        or loading.is_visible()
    )
    assert visible, "changelog: 로딩/타임라인/에러 중 하나도 표시되지 않음"

    shot(page, "11_changelog_load")


def test_changelog_api_responds(page: Page):
    """GET /api/changelog — 200 또는 503(토큰 미설정) 응답 확인, 500/404 아님."""
    resp = page.request.get("https://localhost/api/changelog")
    assert resp.status in (200, 503), (
        f"/api/changelog 응답 코드 {resp.status} — 200(정상) 또는 503(NOTION_TOKEN 미설정) 예상"
    )


def test_changelog_footer_link(page: Page):
    """landing.html 푸터에 릴리즈 노트 링크 존재 확인."""
    goto(page, "/landing")
    link = page.locator("a[href='/changelog']")
    expect(link.first).to_be_visible()
    shot(page, "11_landing_changelog_link")


# ══════════════════════════════════════════════════════════════════════════
# 12. /plan (강화된 훈련 플랜 페이지)
# ══════════════════════════════════════════════════════════════════════════

def test_plan_load(page: Page):
    """훈련 플랜 페이지 로드 — 탭 바·플랜 카드 렌더링 확인."""
    goto(page, "/plan")
    page.wait_for_timeout(800)

    # 헤더
    expect(page.locator(".plan-title")).to_be_visible()

    # 탭 바 존재
    expect(page.locator(".tab-bar")).to_be_visible()

    # 기본 탭(기록 단축) 플랜 카드 렌더링
    expect(page.locator(".plan-card").first).to_be_visible()

    shot(page, "12_plan_load")


def test_plan_tab_switching(page: Page):
    """탭 전환 — 건강하게 오래 탭 클릭 시 카드 교체 확인."""
    goto(page, "/plan")
    page.wait_for_timeout(800)

    page.click('[data-tab="health"]')
    page.wait_for_timeout(400)

    expect(page.locator("#tab-health")).to_have_class(re.compile(r"\bactive\b"))
    expect(page.locator("#tab-health .plan-card")).to_be_visible()

    shot(page, "12_plan_tab_health")


def test_plan_week_selector(page: Page):
    """주차 선택 버튼 클릭 — 2주차 세션 카드 표시 확인."""
    goto(page, "/plan")
    page.wait_for_timeout(800)

    # 2주차 버튼 클릭 (기록단축 탭)
    week2_btn = page.locator('.week-sel-btn[data-week="1"]').first
    expect(week2_btn).to_be_visible()
    week2_btn.click()
    page.wait_for_timeout(300)

    # 세션 카드 최소 1개
    cards = page.locator("#tab-speed .session-card")
    assert cards.count() >= 1, f"세션 카드 없음: {cards.count()}"

    shot(page, "12_plan_week_selector")


def test_plan_session_detail_visible(page: Page):
    """세션 카드에 웜업·메인셋·쿨다운·총 거리·코치 팁 포함 확인."""
    goto(page, "/plan")
    page.wait_for_timeout(800)

    card = page.locator("#tab-speed .session-card").first
    expect(card.locator(".session-total")).to_be_visible()
    expect(card.locator(".coach-tip")).to_be_visible()
    expect(card.locator(".mainset-items")).to_be_visible()

    shot(page, "12_plan_session_detail")


def test_plan_intensity_badge(page: Page):
    """강도 뱃지(쉬움/보통/힘듦) 렌더링 확인."""
    goto(page, "/plan")
    page.wait_for_timeout(800)

    badges = page.locator(".intensity")
    assert badges.count() >= 1, "intensity 뱃지 없음"

    shot(page, "12_plan_intensity")


def test_plan_create_btn_visible(page: Page):
    """'내 플랜 만들기' 버튼 및 '내 플랜' 탭 존재 확인."""
    goto(page, "/plan")
    page.wait_for_timeout(500)

    expect(page.locator("#open-modal-btn")).to_be_visible()
    expect(page.locator('[data-tab="myplan"]')).to_be_visible()

    shot(page, "12_plan_create_btn")


def test_plan_random_tab_form(page: Page):
    """'내 플랜 만들기' 버튼 → 랜덤 생성 탭 전환 및 폼 표시 확인."""
    goto(page, "/plan")
    page.wait_for_timeout(500)

    # 버튼 클릭 → 랜덤 탭으로 전환
    page.click("#open-modal-btn")
    page.wait_for_timeout(300)

    expect(page.locator("#tab-random")).to_have_class(re.compile(r"\bactive\b"))
    expect(page.locator("#r-name")).to_be_visible()
    expect(page.locator("#btn-gen-random")).to_be_visible()

    shot(page, "12_plan_modal")


def test_plan_builder_tab_load(page: Page):
    """직접 구성 탭 로드 — 풀 목록·드롭존·주간 총합 표시 확인."""
    goto(page, "/plan")
    page.wait_for_timeout(800)

    page.click('[data-tab="builder"]')
    page.wait_for_timeout(600)

    expect(page.locator("#tab-builder")).to_have_class(re.compile(r"\bactive\b"))
    # 풀 아이템 존재
    assert page.locator("#pool-list .pool-item").count() >= 1, "풀 아이템 없음"
    # 주간 총합 표시
    expect(page.locator("#week-total-display")).to_be_visible()
    # 드롭존 월요일 존재
    expect(page.locator("#drop-월요일")).to_be_visible()

    shot(page, "12_plan_builder_tab")


def test_plan_builder_add_item(page: Page):
    """직접 구성 탭 — 풀 아이템 클릭 시 월요일 칸에 카드 추가 확인."""
    goto(page, "/plan")
    page.wait_for_timeout(800)

    page.click('[data-tab="builder"]')
    page.wait_for_timeout(600)

    # 첫 번째 풀 아이템 클릭 → 월요일에 추가
    page.locator("#pool-list .pool-item").first.click()
    page.wait_for_timeout(300)

    # 빌더 카드가 생성됐는지
    assert page.locator(".builder-card").count() >= 1, "builder-card 생성 안 됨"
    # 도구 토글 버튼 확인
    expect(page.locator(".equip-btn").first).to_be_visible()
    # 거리 입력 필드 확인
    expect(page.locator(".card-num-input").first).to_be_visible()

    shot(page, "12_plan_builder_add")


def test_plan_api_get(page: Page):
    """GET /api/plans — 200 응답 및 plans 키 포함 확인."""
    resp = page.request.get("https://localhost/api/plans")
    assert resp.status == 200, f"/api/plans 응답 코드 {resp.status}"
    body = resp.json()
    assert "plans" in body, f"plans 키 없음: {body}"


def test_plan_myplan_tab(page: Page):
    """'내 플랜' 탭 클릭 — 탭 전환 및 콘텐츠 렌더링 확인."""
    goto(page, "/plan")
    page.wait_for_timeout(800)

    page.click('[data-tab="myplan"]')
    page.wait_for_timeout(1000)

    expect(page.locator("#tab-myplan")).to_have_class(re.compile(r"\bactive\b"))
    expect(page.locator("#myplan-content")).to_be_visible()

    shot(page, "12_plan_myplan_tab")


# ══════════════════════════════════════════════════════════════════════════
# 13. 오늘 추가된 기능 통합 확인 (2026-05-24)
#     changelog 캐시 TTL 단축 / 플랜 랜덤·빌더 탭 / 검색·드래그 / PWA 버튼
#     ※ test_changelog_load 는 섹션 11에 이미 존재하므로 여기서는 생략
# ══════════════════════════════════════════════════════════════════════════


def test_changelog_page_renders(page: Page):
    """/changelog 페이지 로드 — 헤더·콘텐츠 영역 렌더링 확인 (캐시 TTL 5분)."""
    goto(page, "/changelog")
    page.wait_for_timeout(3000)

    expect(page.locator(".cl-header h1")).to_be_visible()
    visible = (
        page.locator("#cl-timeline").is_visible()
        or page.locator("#cl-error").is_visible()
        or page.locator("#cl-loading").is_visible()
    )
    assert visible, "changelog: 로딩/타임라인/에러 중 하나도 표시되지 않음"

    shot(page, "13_changelog_load")


def test_plan_random_tab(page: Page):
    """/plan — 랜덤 생성 탭(data-tab='random') 탭 버튼 및 콘텐츠 영역 존재 확인."""
    goto(page, "/plan")
    page.wait_for_timeout(600)

    expect(page.locator('[data-tab="random"]')).to_be_visible()

    page.click('[data-tab="random"]')
    page.wait_for_timeout(400)
    expect(page.locator("#tab-random")).to_have_class(re.compile(r"\bactive\b"))
    expect(page.locator("#r-name")).to_be_visible()

    shot(page, "13_plan_random_tab")


def test_plan_builder_tab(page: Page):
    """/plan — 직접 구성 탭(data-tab='builder') 탭 버튼 및 에디터 로드 확인."""
    goto(page, "/plan")
    page.wait_for_timeout(600)

    expect(page.locator('[data-tab="builder"]')).to_be_visible()

    page.click('[data-tab="builder"]')
    page.wait_for_timeout(500)

    expect(page.locator("#tab-builder")).to_have_class(re.compile(r"\bactive\b"))
    expect(page.locator("#builder-editor-body")).to_be_visible()

    shot(page, "13_plan_builder_tab")


def test_plan_builder_search(page: Page):
    """직접 구성 탭 — #pool-search 검색창 존재 및 실시간 필터링 동작 확인."""
    goto(page, "/plan")
    page.wait_for_timeout(600)
    page.click('[data-tab="builder"]')
    page.wait_for_timeout(500)

    search = page.locator("#pool-search")
    expect(search).to_be_visible()

    count_before = page.locator("#pool-list .pool-item").count()
    assert count_before >= 1, "검색 전 풀 아이템 없음"

    search.fill("캐치업")
    page.wait_for_timeout(300)
    count_after = page.locator("#pool-list .pool-item").count()
    assert count_after < count_before, (
        f"검색 후 필터링 안 됨: {count_before}개 → {count_after}개"
    )

    shot(page, "13_plan_builder_search")


def test_plan_builder_drag(page: Page):
    """직접 구성 탭 — 풀 아이템 draggable 속성 및 고정 기타 카드 존재 확인."""
    goto(page, "/plan")
    page.wait_for_timeout(600)
    page.click('[data-tab="builder"]')
    page.wait_for_timeout(500)

    items = page.locator("#pool-list .pool-item")
    assert items.count() >= 1, "풀 아이템 없음"

    draggable = items.first.get_attribute("draggable")
    assert draggable == "true", f"풀 아이템에 draggable='true' 없음: {draggable}"

    # 고정 기타 카드 (#pool-custom-pin) 존재 및 draggable
    pin = page.locator("#pool-custom-pin")
    expect(pin).to_be_visible()
    assert pin.get_attribute("draggable") == "true", "기타 카드 draggable 없음"

    shot(page, "13_plan_builder_drag")


def test_pwa_install_btn(page: Page):
    """landing.html — #pwa-install-btn DOM 존재 및 클릭 핸들러 오류 없음 확인."""
    goto(page, "/landing")
    page.wait_for_timeout(500)

    btn = page.locator("#pwa-install-btn")
    assert btn.count() == 1, "#pwa-install-btn 엘리먼트 없음"

    # 버튼을 강제로 visible 상태로 만들어 클릭해도 JS 오류가 없는지 확인
    page.evaluate("document.getElementById('pwa-install-btn').style.display = 'block'")
    expect(btn).to_be_visible()

    # deferredPrompt 없는 상태 클릭 — 오류 없이 조기 반환 확인
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    btn.click()
    page.wait_for_timeout(300)
    assert not errors, f"클릭 시 JS 오류 발생: {errors}"

    shot(page, "13_pwa_install_btn")


# ══════════════════════════════════════════════════════════════════════════
# 14. 커뮤니티 v2.4.1 — 신고/북마크/알림/태그/정렬
# ══════════════════════════════════════════════════════════════════════════

def test_community_sort(page: Page):
    """/community — 정렬 버튼(최신/인기/조회순) 표시 및 클릭 후 active 전환 확인."""
    goto(page, "/community")
    page.wait_for_selector(".sort-row", timeout=5000)

    expect(page.locator("button.sort-btn[data-sort='latest']")).to_be_visible()
    expect(page.locator("button.sort-btn[data-sort='popular']")).to_be_visible()
    expect(page.locator("button.sort-btn[data-sort='views']")).to_be_visible()

    page.click("button.sort-btn[data-sort='popular']")
    page.wait_for_timeout(500)
    expect(page.locator("button.sort-btn[data-sort='popular']")).to_have_class(re.compile(r"\bactive\b"))

    shot(page, "14_community_sort")


def test_community_report_api(page: Page):
    """POST /api/community/report — 비로그인 403 또는 잘못된 사유로 400/422 응답 확인."""
    resp = page.request.post(
        "https://localhost/api/community/report",
        data='{"target_type":"post","target_id":9999,"reason":"잘못된사유"}',
        headers={"Content-Type": "application/json"},
    )
    assert resp.status in (400, 401, 403, 409, 422), (
        f"/api/community/report 예상 외 응답: {resp.status}"
    )
    shot(page, "14_community_report_api")


def test_community_bookmark_api(page: Page):
    """GET /api/community/bookmarks — 200 또는 비로그인 401/403 응답 확인."""
    resp = page.request.get("https://localhost/api/community/bookmarks")
    assert resp.status in (200, 401, 403), f"/api/community/bookmarks 응답 코드: {resp.status}"
    if resp.status == 200:
        body = resp.json()
        assert "posts" in body, f"posts 키 없음: {body}"
    shot(page, "14_community_bookmark_api")


def test_community_notifications_api(page: Page):
    """GET /api/notifications — 200 또는 비로그인 401/403 응답 확인."""
    resp = page.request.get("https://localhost/api/notifications")
    assert resp.status in (200, 401, 403), f"/api/notifications 응답 코드: {resp.status}"
    if resp.status == 200:
        body = resp.json()
        assert "notifications" in body, f"notifications 키 없음: {body}"
    shot(page, "14_community_notifications_api")


def test_community_tags_api(page: Page):
    """GET /api/community/tags — 200 응답 및 tags 키 포함 확인."""
    resp = page.request.get("https://localhost/api/community/tags")
    assert resp.status == 200, f"/api/community/tags 응답 코드: {resp.status}"
    body = resp.json()
    assert "tags" in body, f"tags 키 없음: {body}"
    shot(page, "14_community_tags_api")


def test_community_notifications_ui(page: Page):
    """/community — 알림 벨 버튼(.btn-notif) 및 정렬 버튼 UI 확인."""
    goto(page, "/community")
    # 로그인 후 JS가 #header-right에 알림 버튼을 동적 주입하므로 명시적 대기
    page.wait_for_selector(".btn-notif", timeout=5000)

    expect(page.locator(".btn-notif")).to_be_visible()
    expect(page.locator(".sort-row")).to_be_visible()

    shot(page, "14_community_notif_ui")


# ══════════════════════════════════════════════════════════════════════════
# 15. 훈련 일지 (v2.4.4)
# ══════════════════════════════════════════════════════════════════════════

def test_training_log_load(page: Page):
    """/training-log 페이지 로드 — 통계 카드·캘린더·기록 목록 영역 렌더링 확인."""
    goto(page, "/training-log")
    page.wait_for_timeout(1500)

    # 통계 카드 4개
    expect(page.locator("#stat-count")).to_be_visible()
    expect(page.locator("#stat-total")).to_be_visible()
    expect(page.locator("#stat-avg")).to_be_visible()
    expect(page.locator("#stat-streak")).to_be_visible()

    # 캘린더 래퍼 (cal-body는 JS 실행 전 빈 grid)
    expect(page.locator(".cal-wrap")).to_be_visible()

    # 기록 추가 버튼
    expect(page.locator("#btn-open-modal")).to_be_visible()

    # 월 이동 버튼
    expect(page.locator("#prev-month")).to_be_visible()
    expect(page.locator("#next-month")).to_be_visible()

    shot(page, "15_training_log_load")


def test_training_log_api_requires_login(browser, browser_context_args):
    """GET /api/training-log — 비로그인 요청은 401 응답."""
    ctx = browser.new_context(**browser_context_args)
    page = ctx.new_page()
    try:
        resp = page.request.get("https://localhost/api/training-log")
        assert resp.status in (401, 403, 500), f"/api/training-log 비로그인 응답 코드: {resp.status}"
        shot(page, "15_training_log_unauth")
    finally:
        page.close()
        ctx.close()


def test_training_log_stats_api(page: Page):
    """GET /api/training-log/stats — 로그인 상태 200 또는 admin(customer_id 없음) 403 확인."""
    resp = page.request.get("https://localhost/api/training-log/stats")
    assert resp.status in (200, 403), f"/api/training-log/stats 응답 코드: {resp.status}"
    if resp.status == 200:
        body = resp.json()
        for key in ("count", "total_distance", "avg_distance", "total_minutes"):
            assert key in body, f"stats 응답에 '{key}' 키 없음: {body}"
    shot(page, "15_training_log_stats_api")


def test_training_log_streak_api(page: Page):
    """GET /api/training-log/streak — 로그인 상태 200 또는 admin(customer_id 없음) 403 확인."""
    resp = page.request.get("https://localhost/api/training-log/streak")
    assert resp.status in (200, 403), f"/api/training-log/streak 응답 코드: {resp.status}"
    if resp.status == 200:
        body = resp.json()
        assert "streak" in body, f"streak 응답에 'streak' 키 없음: {body}"
        assert isinstance(body["streak"], int), f"streak 값이 정수가 아님: {body['streak']}"
    shot(page, "15_training_log_streak_api")


# ══════════════════════════════════════════════════════════════════════════
# 16. /report (월간 성장 리포트)
# ══════════════════════════════════════════════════════════════════════════

def test_report_load(page: Page):
    """/report 페이지 로드 — 월 선택 네비게이션·통계 카드 렌더링 확인."""
    goto(page, "/report")
    page.wait_for_timeout(1500)

    # 월 이동 버튼
    expect(page.locator("#prev-month")).to_be_visible()
    expect(page.locator("#next-month")).to_be_visible()
    expect(page.locator("#month-label")).to_be_visible()

    # 통계 카드 4개
    expect(page.locator("#stat-distance")).to_be_visible()
    expect(page.locator("#stat-count")).to_be_visible()
    expect(page.locator("#stat-time")).to_be_visible()
    expect(page.locator("#stat-cal")).to_be_visible()

    # 성장률 배너
    expect(page.locator("#growth-rate")).to_be_visible()
    expect(page.locator("#growth-streak")).to_be_visible()

    # 공유 버튼
    expect(page.locator("#btn-link")).to_be_visible()

    shot(page, "16_report_load")


def test_report_api(page: Page):
    """GET /api/report/monthly — 200 응답 및 필수 키 확인."""
    now = date.today()
    resp = page.request.get(
        f"https://localhost/api/report/monthly?year={now.year}&month={now.month}",
    )
    assert resp.status == 200, f"/api/report/monthly 응답 코드: {resp.status}"
    body = resp.json()
    for key in ("total_distance", "total_count", "total_minutes", "growth_rate",
                "stroke_dist", "weekday_freq", "weekly_dist", "max_streak", "share_token"):
        assert key in body, f"'{key}' 키 없음: {list(body.keys())}"
    assert len(body["weekday_freq"]) == 7, "weekday_freq 길이 != 7"
    assert len(body["weekly_dist"]) == 5, "weekly_dist 길이 != 5"
    shot(page, "16_report_api")


def test_report_month_nav(page: Page):
    """/report — 이전 달 화살표 클릭 시 월 레이블 변경 확인."""
    goto(page, "/report")
    page.wait_for_timeout(1000)

    initial = page.locator("#month-label").inner_text()
    page.click("#prev-month")
    page.wait_for_timeout(800)
    after = page.locator("#month-label").inner_text()

    assert initial != after, f"월 레이블이 변경되지 않음: {initial}"
    shot(page, "16_report_month_nav")


# ══════════════════════════════════════════════════════════════════════════
# 17. /challenge (수영 챌린지)
# ══════════════════════════════════════════════════════════════════════════

def test_challenge_load(page: Page):
    """/challenge 페이지 로드 — 탭·챌린지 카드 렌더링 확인."""
    goto(page, "/challenge")
    page.wait_for_timeout(2000)

    # 탭 버튼
    expect(page.locator("#tab-all")).to_be_visible()
    expect(page.locator("#tab-my")).to_be_visible()

    # 챌린지 카드 최소 1개 또는 빈 상태 메시지
    cards = page.locator(".ch-card")
    empty = page.locator(".ch-empty")
    assert cards.count() >= 1 or empty.count() >= 1, "ch-card 또는 ch-empty 없음"

    shot(page, "17_challenge_load")


def test_challenge_api(page: Page):
    """GET /api/challenge — 200 응답 및 challenges 키 확인."""
    resp = page.request.get("https://localhost/api/challenge")
    assert resp.status == 200, f"/api/challenge 응답 코드: {resp.status}"
    body = resp.json()
    assert "challenges" in body, f"challenges 키 없음: {body}"
    assert isinstance(body["challenges"], list), "challenges가 리스트가 아님"
    shot(page, "17_challenge_api")


def test_challenge_ranking_api(page: Page):
    """GET /api/challenge/1/ranking — 200 응답 및 ranking 키 확인."""
    resp = page.request.get("https://localhost/api/challenge/1/ranking")
    assert resp.status in (200, 404), f"/api/challenge/1/ranking 응답 코드: {resp.status}"
    if resp.status == 200:
        body = resp.json()
        assert "ranking" in body, f"ranking 키 없음: {body}"
    shot(page, "17_challenge_ranking_api")


def test_challenge_my_tab(page: Page):
    """/challenge — '내 챌린지' 탭 전환 확인."""
    goto(page, "/challenge")
    page.wait_for_timeout(1000)

    page.click("#tab-my")
    page.wait_for_timeout(1500)

    expect(page.locator("#tab-my")).to_have_class(re.compile(r"\bactive\b"))
    expect(page.locator("#panel-my")).to_be_visible()

    shot(page, "17_challenge_my_tab")


# ══════════════════════════════════════════════════════════════════════════
# 18. /feedback (개발자에게 한마디, v2.4.8)
# ══════════════════════════════════════════════════════════════════════════

def test_feedback_load(page: Page):
    """/feedback 페이지 로드 — 헤더·폼 영역 렌더링 확인."""
    goto(page, "/feedback")
    page.wait_for_timeout(500)

    expect(page.locator(".feedback-card h1")).to_be_visible()
    expect(page.locator("#feedback-form")).to_be_visible()
    expect(page.locator("#submit-btn")).to_be_visible()

    shot(page, "18_feedback_load")


def test_feedback_form(page: Page):
    """/feedback — 유형 버튼·제목·내용 입력 요소 존재 확인."""
    goto(page, "/feedback")
    page.wait_for_timeout(500)

    # 유형 버튼 4개 (버그 신고 / 기능 요청 / 개선 제안 / 기타)
    type_btns = page.locator(".type-btn")
    assert type_btns.count() == 4, f"type-btn 개수 불일치: {type_btns.count()}"
    expect(type_btns.first).to_be_visible()

    # 제목 입력
    expect(page.locator("#feedback-title")).to_be_visible()

    # 내용 입력
    expect(page.locator("#feedback-content")).to_be_visible()

    # 유형 버튼 클릭 시 selected 클래스 전환
    first_btn = page.locator(".type-btn").first
    first_btn.click()
    expect(first_btn).to_have_class(re.compile(r"\bselected\b"))

    shot(page, "18_feedback_form")


def test_feedback_api(page: Page):
    """POST /api/feedback — 200(SMTP 설정 시) 또는 500(SMTP 미설정) 응답 확인."""
    resp = page.request.post(
        "https://localhost/api/feedback",
        data='{"feedback_type":"버그 신고","page":"홈 / 랜딩","title":"테스트","content":"자동화 테스트 피드백입니다."}',
        headers={"Content-Type": "application/json"},
    )
    assert resp.status in (200, 500), (
        f"/api/feedback 예상 외 응답: {resp.status}"
    )
    shot(page, "18_feedback_api")


# ══════════════════════════════════════════════════════════════════════════
# 19. /equipment (수영 장비 가이드, v2.5.0)
# ══════════════════════════════════════════════════════════════════════════

def test_equipment_load(page: Page):
    """/equipment 페이지 로드 — 탭·장비 카드 렌더링 확인."""
    goto(page, "/equipment")
    page.wait_for_timeout(600)

    # 탭 3개 (전체 / 기초장비 / 상급장비)
    tabs = page.locator(".tab-btn")
    assert tabs.count() == 3, f"tab-btn 개수 불일치: {tabs.count()}"

    # 전체 탭에 장비 카드 존재
    cards = page.locator("#grid-all .eq-card")
    assert cards.count() >= 8, f"장비 카드 개수 부족: {cards.count()}"

    shot(page, "19_equipment_load")


def test_equipment_tab_switch(page: Page):
    """/equipment — 탭 전환 시 기초장비 카드만 표시."""
    goto(page, "/equipment")
    page.wait_for_timeout(600)

    basic_tab = page.locator(".tab-btn[data-tab='basic']")
    basic_tab.click()
    page.wait_for_timeout(400)

    expect(basic_tab).to_have_class(re.compile(r"\bactive\b"))

    # 기초장비 그리드 카드 수 확인 (오리발·킥판·풀부이 = 3개)
    basic_cards = page.locator("#grid-basic .eq-card")
    assert basic_cards.count() == 3, f"기초장비 카드 수 불일치: {basic_cards.count()}"

    shot(page, "19_equipment_tab_basic")


def test_equipment_card_toggle(page: Page):
    """/equipment — 카드 클릭 시 상세 섹션 토글."""
    goto(page, "/equipment")
    page.wait_for_timeout(600)

    first_header = page.locator("#grid-all .eq-card-header").first
    first_header.click()
    page.wait_for_timeout(300)

    # 토글 후 .open 클래스 추가 확인
    first_card = page.locator("#grid-all .eq-card").first
    expect(first_card).to_have_class(re.compile(r"\bopen\b"))

    # 상세 섹션 표시 확인
    detail = first_card.locator(".eq-detail")
    expect(detail).to_be_visible()

    shot(page, "19_equipment_card_toggle")


def test_equipment_landing_card(page: Page):
    """/landing — 정보/도움 섹션에 장비 가이드 카드 존재 확인."""
    goto(page, "/landing")
    page.wait_for_timeout(500)

    card = page.locator("a.menu-card[href='/equipment']")
    expect(card).to_be_visible()

    shot(page, "19_equipment_landing_card")


# ══════════════════════════════════════════════════════════════════════════
# 20. /videos (수영 영상 큐레이션, v2.5.1)
# ══════════════════════════════════════════════════════════════════════════

def test_videos_load(page: Page):
    """/videos 페이지 로드 — 카테고리 탭·영상 그리드 렌더링 확인."""
    goto(page, "/videos")
    page.wait_for_timeout(600)

    expect(page.locator("#cat-tab-bar")).to_be_visible()
    expect(page.locator("#video-grid")).to_be_visible()

    shot(page, "20_videos_load")


def test_videos_filter(page: Page):
    """/videos — 카테고리 탭 클릭 시 active 클래스 전환 확인."""
    goto(page, "/videos")
    page.wait_for_timeout(600)

    tabs = page.locator("#cat-tab-bar .tab-btn")
    assert tabs.count() > 1, f"탭 개수 부족: {tabs.count()}"

    second_tab = tabs.nth(1)
    second_tab.click()
    page.wait_for_timeout(400)

    expect(second_tab).to_have_class(re.compile(r"\bactive\b"))

    shot(page, "20_videos_filter")


def test_videos_search(page: Page):
    """/videos — 검색창 존재 및 입력 가능 확인."""
    goto(page, "/videos")
    page.wait_for_timeout(600)

    search = page.locator("#search-input")
    expect(search).to_be_visible()
    search.fill("자유형")
    page.wait_for_timeout(300)

    shot(page, "20_videos_search")


# ══════════════════════════════════════════════════════════════════════════
# 21. /coach (코치-수강생 연동 시스템, v2.5.2)
# ══════════════════════════════════════════════════════════════════════════

def test_coach_load(page: Page):
    """/coach 페이지 로드 — 탭 구조 렌더링 확인."""
    goto(page, "/coach")
    page.wait_for_timeout(700)

    expect(page.locator("#coach-tab-bar")).to_be_visible()
    expect(page.locator("#tab-btn-coach")).to_be_visible()
    expect(page.locator("#tab-btn-student")).to_be_visible()

    shot(page, "21_coach_load")


def test_coach_register_api(page: Page):
    """POST /api/coach/register — 코치 등록 또는 기존 프로필 반환."""
    resp = page.request.post(
        "https://localhost/api/coach/register",
        data='{"specialty":"자유형","career":"10년","intro":"테스트 코치"}',
        headers={"Content-Type": "application/json"},
    )
    assert resp.status in (200, 400, 401, 409, 422), (
        f"/api/coach/register 예상 외 응답: {resp.status}"
    )
    if resp.status == 200:
        body = resp.json()
        assert "invite_code" in body or "already_exists" in body, f"응답 키 없음: {body}"
    shot(page, "21_coach_register_api")


def test_coach_join_api(page: Page):
    """POST /api/coach/join — 유효하지 않은 코드로 404 응답 확인."""
    resp = page.request.post(
        "https://localhost/api/coach/join",
        data='{"invite_code":"SWIM-INVALID999"}',
        headers={"Content-Type": "application/json"},
    )
    assert resp.status in (400, 401, 404, 422), (
        f"/api/coach/join 예상 외 응답: {resp.status}"
    )
    shot(page, "21_coach_join_api")


def test_coach_feedback_api(page: Page):
    """POST /api/coach/feedback — 코치 미등록 또는 권한 없을 때 403/400 응답 확인."""
    resp = page.request.post(
        "https://localhost/api/coach/feedback",
        data='{"student_id":9999,"content":"테스트 피드백"}',
        headers={"Content-Type": "application/json"},
    )
    assert resp.status in (400, 401, 403, 404, 422), (
        f"/api/coach/feedback 예상 외 응답: {resp.status}"
    )
    shot(page, "21_coach_feedback_api")


# ══════════════════════════════════════════════════════════════════════════
# 22. /coach — 고정 테스트 계정 기반 E2E (coach_test / student_test)
# ══════════════════════════════════════════════════════════════════════════

def _login_as(page: Page, username: str, password: str) -> None:
    """주어진 계정으로 로그인 후 쿠키(swimtech_token)를 현재 컨텍스트에 설정."""
    resp = page.request.post(
        f"{BASE_URL}/api/auth/login",
        data=f'{{"username":"{username}","password":"{password}"}}',
        headers={"Content-Type": "application/json"},
    )
    # 401 → 계정 미생성(test_accounts.sql 미실행) 으로 간주, 테스트를 스킵
    if resp.status == 401:
        pytest.skip(f"{username} 계정이 DB에 없습니다. db/test_accounts.sql 을 먼저 실행하세요.")
    assert resp.status == 200, f"로그인 실패 ({username}): {resp.status}"


def test_coach_page_load(page: Page):
    """/coach 페이지 로드 — 탭 바 및 코치·수강생 탭 버튼 존재 확인."""
    goto(page, "/coach")
    page.wait_for_timeout(700)

    expect(page.locator("#coach-tab-bar")).to_be_visible()
    expect(page.locator("#tab-btn-coach")).to_be_visible()
    expect(page.locator("#tab-btn-student")).to_be_visible()

    shot(page, "22_coach_page_load")


def test_coach_register_form(page: Page):
    """코치 등록 폼 UI — specialty·career·intro 입력란 존재 확인."""
    goto(page, "/coach")
    page.wait_for_timeout(700)

    # 코치 탭이 기본 선택
    expect(page.locator("#tab-btn-coach")).to_be_visible()

    # 입력 필드가 DOM 에 있는지 확인 (미등록 상태에서 보임)
    expect(page.locator("#reg-specialty")).to_be_attached()
    expect(page.locator("#reg-career")).to_be_attached()
    expect(page.locator("#reg-intro")).to_be_attached()

    shot(page, "22_coach_register_form")


def test_coach_invite_code_api(page: Page):
    """/api/coach/me — coach_test 로 로그인 후 invite_code 형식 확인."""
    _login_as(page, COACH_ID, COACH_PW)

    resp = page.request.get(f"{BASE_URL}/api/coach/me")
    assert resp.status == 200, f"/api/coach/me 응답 오류: {resp.status}"

    body = resp.json()
    assert body.get("is_coach") is True, f"coach_test 가 코치로 등록되지 않음: {body}"
    invite_code = body.get("invite_code", "")
    assert invite_code.startswith("SWIM-"), (
        f"invite_code 형식 이상: {invite_code!r} (SWIM-으로 시작해야 함)"
    )

    shot(page, "22_coach_invite_code_api")


def test_student_join_ui(page: Page):
    """수강생 탭 — 초대코드 입력란(#join-code) 존재 확인."""
    goto(page, "/coach")
    page.wait_for_timeout(500)

    # 수강생 탭 전환
    page.click("#tab-btn-student")
    page.wait_for_timeout(500)

    expect(page.locator("#join-code")).to_be_attached()

    shot(page, "22_student_join_ui")


def test_coach_api_unauthorized(page: Page):
    """비로그인 상태에서 /api/coach/me 호출 → 401 또는 403 확인."""
    # 쿠키 없이 별도 요청 컨텍스트 사용
    resp = page.request.get(
        f"{BASE_URL}/api/coach/me",
        headers={"Cookie": ""},  # 쿠키 무효화
    )
    assert resp.status in (401, 403), (
        f"비로그인 /api/coach/me 예상 외 응답: {resp.status}"
    )

    shot(page, "22_coach_api_unauthorized")
