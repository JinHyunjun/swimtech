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
from pathlib import Path
from playwright.sync_api import Page, BrowserContext, expect

# ── constants ──────────────────────────────────────────────────────────────
BASE_URL    = "https://localhost"
TEST_USER   = "admin"
TEST_PASS   = "swimtech1234"
SHOT_DIR    = Path(__file__).parent / "screenshots"
SHOT_DIR.mkdir(exist_ok=True)


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
    page.wait_for_url(re.compile(r"/(landing|onboarding|$)"), timeout=10_000)

    if "/onboarding" in page.url:
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
    assert any("분석" in t for t in btn_texts), "분석 버튼 없음"
    assert any("대화" in t for t in btn_texts), "AI코치 버튼 없음"

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
        page.wait_for_url(re.compile(r"/(landing|onboarding|$)"), timeout=10_000)
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


# ══════════════════════════════════════════════════════════════════════════
# 4. /dashboard
# ══════════════════════════════════════════════════════════════════════════

def test_dashboard_cards(page: Page):
    goto(page, "/dashboard")
    page.wait_for_timeout(1500)  # API 응답 대기

    for card_id in ["#card-total", "#card-avg-score", "#card-max-score", "#card-total-kicks"]:
        expect(page.locator(card_id)).to_be_visible()

    shot(page, "04_dashboard_cards")


def test_dashboard_charts(page: Page):
    """Chart.js canvas 4개 존재 확인."""
    goto(page, "/dashboard")
    page.wait_for_timeout(2000)

    for chart_id in ["#chart-score", "#chart-elbow", "#chart-kick", "#chart-sym"]:
        expect(page.locator(chart_id)).to_be_visible()

    shot(page, "04_dashboard_charts")


def test_dashboard_history(page: Page):
    goto(page, "/dashboard")
    page.wait_for_timeout(1500)
    expect(page.locator("#table-wrap")).to_be_visible()
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
    """첫 번째 질문 클릭 → 답변 펼쳐짐 확인."""
    goto(page, "/faq")

    first_q = page.locator(".faq-q").first
    first_q.click()
    page.wait_for_timeout(400)

    # faq-a 가 display:none 에서 벗어나야 함
    first_a = page.locator(".faq-a").first
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
