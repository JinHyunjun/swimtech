"""영상 분석 비활성화와 훈련 중심 제품 흐름을 지키는 정적 계약 테스트."""
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_database_schema_changes_are_versioned_and_deploy_gated():
    main = (ROOT / "api" / "main.py").read_text(encoding="utf-8")
    render = (ROOT / "render.yaml").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "qa.yml").read_text(encoding="utf-8")
    alembic_ini = (ROOT / "api" / "alembic.ini").read_text(encoding="utf-8")
    alembic_env = (ROOT / "api" / "alembic" / "env.py").read_text(encoding="utf-8")
    baseline = (
        ROOT / "api" / "alembic" / "versions" / "20260723_01_production_baseline.py"
    ).read_text(encoding="utf-8")
    onboarding_revision = (
        ROOT / "api" / "alembic" / "versions" / "20260723_02_personalized_onboarding.py"
    ).read_text(encoding="utf-8")
    set_revision = (
        ROOT / "api" / "alembic" / "versions" / "20260723_03_training_log_sets.py"
    ).read_text(encoding="utf-8")
    club_revision = (
        ROOT / "api" / "alembic" / "versions" / "20260723_04_clubs_classes_roles.py"
    ).read_text(encoding="utf-8")
    operations_revision = (
        ROOT / "api" / "alembic" / "versions" / "20260723_05_class_operations.py"
    ).read_text(encoding="utf-8")
    benchmark_revision = (
        ROOT / "api" / "alembic" / "versions" / "20260723_06_swim_test_results.py"
    ).read_text(encoding="utf-8")
    account_revision = (
        ROOT / "api" / "alembic" / "versions" / "20260723_07_account_security.py"
    ).read_text(encoding="utf-8")
    qa_account_revision = (
        ROOT / "api" / "alembic" / "versions" / "20260723_08_qa_account_classification.py"
    ).read_text(encoding="utf-8")
    promotion_revision = (
        ROOT / "api" / "alembic" / "versions" / "20260723_09_promotion_shares_club_campaigns.py"
    ).read_text(encoding="utf-8")
    qa_session_revision = (
        ROOT / "api" / "alembic" / "versions" / "20260723_10_qa_activity_session_index.py"
    ).read_text(encoding="utf-8")

    assert "alembic -c alembic.ini upgrade head && uvicorn" in render
    assert "python -m alembic -c api/alembic.ini heads" in workflow
    assert "script_location = %(here)s/alembic" in alembic_ini
    assert "DATABASE_URL is required" in alembic_env
    assert "pg_advisory_xact_lock" in alembic_env
    assert 'revision: str = "20260723_01"' in baseline
    assert 'revision: str = "20260723_02"' in onboarding_revision
    assert 'down_revision: Union[str, None] = "20260723_01"' in onboarding_revision
    assert "preferred_pool_length" in onboarding_revision
    assert "onboarding_completed_at" in onboarding_revision
    assert 'revision: str = "20260723_03"' in set_revision
    assert 'down_revision: Union[str, None] = "20260723_02"' in set_revision
    assert '"training_log_sets"' in set_revision
    assert "target_cycle_seconds" in set_revision
    assert "completed_distance_m" in set_revision
    assert 'revision: str = "20260723_04"' in club_revision
    assert 'down_revision: Union[str, None] = "20260723_03"' in club_revision
    for table in ["swim_clubs", "swim_club_members", "swim_classes", "swim_class_members"]:
        assert f'"{table}"' in club_revision
    assert "owner', 'coach', 'assistant', 'member" in club_revision
    assert "coach', 'assistant', 'student" in club_revision
    assert 'revision: str = "20260723_05"' in operations_revision
    assert 'down_revision: Union[str, None] = "20260723_04"' in operations_revision
    for table in ["swim_class_sessions", "swim_class_attendance", "swim_class_notices", "swim_class_notice_reads"]:
        assert f'"{table}"' in operations_revision
    assert 'revision: str = "20260723_06"' in benchmark_revision
    assert 'down_revision: Union[str, None] = "20260723_05"' in benchmark_revision
    assert '"swim_test_results"' in benchmark_revision
    assert "duration_ms" in benchmark_revision and "pool_length" in benchmark_revision
    assert 'revision: str = "20260723_07"' in account_revision
    assert 'down_revision: Union[str, None] = "20260723_06"' in account_revision
    assert "auth_version" in account_revision and "password_changed_at" in account_revision
    assert 'revision: str = "20260723_08"' in qa_account_revision
    assert 'down_revision: Union[str, None] = "20260723_07"' in qa_account_revision
    assert "is_qa_account" in qa_account_revision
    assert "ix_customers_qa_account_true" in qa_account_revision
    assert 'revision: str = "20260723_09"' in promotion_revision
    assert 'down_revision: Union[str, None] = "20260723_08"' in promotion_revision
    assert '"promotion_result_shares"' in promotion_revision
    assert '"club_promotion_campaigns"' in promotion_revision
    assert '"promotion_distance_opt_in"' in promotion_revision
    assert 'revision: str = "20260723_10"' in qa_session_revision
    assert 'down_revision: Union[str, None] = "20260723_09"' in qa_session_revision
    assert "ix_activity_qa_session_anchor" in qa_session_revision
    assert 'EXPECTED_SCHEMA_REVISION = "20260723_10"' in main
    assert 'command.upgrade(config, "head")' in main
    assert "lifespan=lifespan" in main
    assert 'SELECT version_num FROM alembic_version' in main
    assert 'health.get("schema_revision") == "20260723_10"' in (
        ROOT / "scripts" / "qa_runner.py"
    ).read_text(encoding="utf-8")
    assert '@app.on_event("startup")' not in main
    assert "def apply_migrations" not in main


def test_analysis_routers_are_not_publicly_registered():
    main = (ROOT / "api" / "main.py").read_text(encoding="utf-8")
    assert "include_router(videos.router" not in main
    assert "include_router(analysis.router" not in main
    assert "include_router(stream.router" not in main


def test_drill_loads_shared_utils_before_initializing_tabs():
    drill = (ROOT / "frontend" / "drill.html").read_text(encoding="utf-8")
    injury = (ROOT / "frontend" / "injury.html").read_text(encoding="utf-8")
    equipment = (ROOT / "frontend" / "equipment.html").read_text(encoding="utf-8")
    swimwear_sizing = (ROOT / "frontend" / "static" / "swimwear-sizing.js").read_text(encoding="utf-8")
    faq = (ROOT / "frontend" / "faq.html").read_text(encoding="utf-8")
    landing = (ROOT / "frontend" / "landing.html").read_text(encoding="utf-8")
    qa_ui = (ROOT / "scripts" / "qa_ui_crawler.py").read_text(encoding="utf-8")

    assert drill.index('/static/utils.js') < drill.index("SW.initTabs")
    for marker in ["drill-search", "data-focus", "data-level", "data-pool", "출발 사이클"]:
        assert marker in drill
    assert "의료 진단이 아닌 일반 안전 정보" in injury
    assert "data-readiness=\"yellow\"" in injury
    assert "허리 통증의 90%" not in injury
    assert "부담이 절반 이하" not in injury
    assert "SwimMate 분석으로 확인할 것" not in injury
    assert "data-tab=\"swimwear\"" in equipment
    assert "World Aquatics 승인 수영복" in equipment
    assert "new URLSearchParams(window.location.search)" in equipment
    assert "/static/swimwear-sizing.js" in equipment
    for marker in ["brand-size-guide", "data-chart-unit=\"in\"", "size-recommender-form", "measurement-unit", "measure-bust-conversion", "current-model", "current-size-region", "target-purchase-region", "size-reference-confirm", "recommend-grid"]:
        assert marker in equipment
    for marker in ["Speedo", "arena", "TYR", "Mizuno", "Nike Swim", "regionCode", "regionLabel", "labelSystem", "RACE_MODEL_PATTERN", "proxyFromCurrent", "recommend"]:
        assert marker in swimwear_sizing
    assert "innerHTML" not in swimwear_sizing
    for marker in ["구매 확정값이 아닙니다", "결과를 맹신하지 마세요", "모델별 원단", "공식표 기준 지역"]:
        assert marker in equipment
    for marker in ["cmToInches", "inchesToCm", "applyMeasurementUnit", "inch 입력 → cm 정규화", "1 inch = 2.54 cm"]:
        assert marker in equipment
    assert "구매·착용을 보장하지 않습니다" in faq
    assert "수영복은 어떻게 골라야 하나요" in faq
    assert "data-hidden=\"true\"" not in faq
    assert "이메일 자동 비밀번호 재설정은 제공하지 않습니다" in faq
    assert "직접 가져오거나 동기화하지 않습니다" in faq
    assert 'href="/equipment?tab=swimwear"' in landing

    equipment_expectation = qa_ui.split('"/equipment": {', 1)[1].split("    },", 1)[0]
    assert '"texts": ["수영 장비·수영복 가이드"]' in equipment_expectation
    assert "swimwear_required_texts" in qa_ui
    assert "수영복 탭 필수 문구 누락" in qa_ui
    assert "라벨만으로 환산하지 않습니다" in qa_ui
    assert 'page.locator("#recommend-result").is_visible()' in qa_ui
    assert "같은 “30”이라도 의미가 다를 수 있어" not in qa_ui
    assert "searchable_text" in qa_ui
    assert 'counter_text != f"{visible_count}건"' in qa_ui


def test_readme_describes_current_training_helper_and_retires_analysis_claims():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "# 🏊 SwimMate — 수영 훈련 기록 및 설계 올인원 도우미" in readme
    assert "영상 영법 분석 — 개선 중 · 공개 서비스 비활성" in readme
    assert "Vercel 프론트엔드 + Render FastAPI + Neon PostgreSQL" in readme
    assert "코치 코드" in readme and "비회원 체험" in readme
    assert "AI 수영 영법 분석 & 올인원 트레이닝 플랫폼" not in readme
    assert "영법 분류 정확도 **94.4%**" not in readme
    assert "관절 검출 정확도 **81.5%**" not in readme
    assert "[데모 영상 / 스크린샷 자리]" not in readme
    assert "[웹서비스 바로가기](https://swimtech.vercel.app)" in readme
    assert "별도의 프로그램이나 설치 마법사가 필요 없는 웹서비스" in readme
    assert "비회원 체험 시작" in readme
    assert "## 로컬 실행" not in readme
    assert "docker compose up" not in readme
    assert not (ROOT / "실행파일_설치.zip").exists()


def test_legacy_analysis_urls_are_redirected_or_retired():
    main = (ROOT / "api" / "main.py").read_text(encoding="utf-8")
    # Vercel serves the frontend directory; its tracked config is the deploy source.
    for config_path in (ROOT / "frontend" / "vercel.json",):
        config = json.loads(config_path.read_text(encoding="utf-8"))
        redirect_sources = {item["source"] for item in config["redirects"]}
        assert {"/meta", "/upload", "/viewer", "/share/:path*"} <= redirect_sources
    assert "status_code=410" in main
    for retired_page in ("upload.html", "viewer.html", "viewer.js", "meta.html", "share.html", "index_ai_beta.html"):
        assert not (ROOT / "frontend" / retired_page).exists()
    assert not (ROOT / "frontend" / "static" / "viewer.js").exists()


def test_dashboard_reads_training_logs_not_analysis_results():
    dashboard = (ROOT / "api" / "routers" / "dashboard.py").read_text(encoding="utf-8")
    assert "training_logs" in dashboard
    assert "analysis_results" not in dashboard


def test_customer_routes_require_admin_authorization():
    customers = (ROOT / "api" / "routers" / "customers.py").read_text(encoding="utf-8")
    assert customers.count("_require_admin(swimtech_token)") == 3


def test_quick_log_reuses_the_latest_training_record():
    api = (ROOT / "api" / "routers" / "training_log.py").read_text(encoding="utf-8")
    page = (ROOT / "frontend" / "training_log.html").read_text(encoding="utf-8")
    dashboard = (ROOT / "frontend" / "dashboard.html").read_text(encoding="utf-8")

    assert '@router.get("/recent")' in api
    assert "ORDER BY log_date DESC, created_at DESC" in api
    assert "openQuickLog" in page
    assert "/api/training-log/recent" in page
    assert "/training-log?quick=1" in dashboard


def test_training_dashboard_is_visible_from_the_landing_page():
    landing = (ROOT / "frontend" / "landing.html").read_text(encoding="utf-8")
    icons = (ROOT / "frontend" / "static" / "icons.svg").read_text(encoding="utf-8")

    assert 'href="/dashboard"' in landing
    assert "상세 훈련 대시보드" in landing
    assert "#icon-dashboard" in landing
    assert 'id="icon-dashboard"' in icons


def test_landing_is_a_personal_training_home_with_categorized_service_navigation():
    landing = (ROOT / "frontend" / "landing.html").read_text(encoding="utf-8")
    ui_qa = (ROOT / "scripts" / "qa_ui_crawler.py").read_text(encoding="utf-8")

    for marker in (
        'id="service-sidebar"',
        'id="menu-toggle"',
        'id="home-week-distance"',
        'id="home-week-sessions"',
        'id="home-month-distance"',
        'id="home-total-distance"',
        'id="weekly-bar"',
        'id="home-history"',
        'id="advisor-title"',
    ):
        assert marker in landing

    for heading in ("내 훈련 홈", "기록과 훈련", "코칭과 함께", "탐색과 도움"):
        assert heading in landing

    for endpoint in (
        "/api/dashboard/summary",
        "/api/dashboard/weekly",
        "/api/dashboard/history",
        "/api/dashboard/training-advisor",
    ):
        assert endpoint in landing

    assert "@media (max-width:900px)" in landing
    assert "aria-expanded" in landing
    assert "syncHeaderOffset" in landing
    assert "sidebarBackdrop.setAttribute('aria-hidden', String(!open))" in landing
    assert "if (summaryResult.status === 'fulfilled') renderSummary(summaryResult.value)" in landing
    assert "if (weeklyResult.status === 'fulfilled')" in landing
    assert '"/landing": {' in ui_qa
    assert "#service-sidebar" in ui_qa
    assert "무엇을 도와드릴까요? 원하는 서비스를 선택해주세요" not in landing


def test_feature_pages_keep_the_shared_service_navigation_visible():
    service_nav = (ROOT / "frontend" / "static" / "service-nav.js").read_text(encoding="utf-8")
    static_theme = (ROOT / "frontend" / "static" / "theme.js").read_text(encoding="utf-8")
    root_theme = (ROOT / "frontend" / "theme.js").read_text(encoding="utf-8")
    static_style = (ROOT / "frontend" / "static" / "style.css").read_text(encoding="utf-8")
    root_style = (ROOT / "frontend" / "style.css").read_text(encoding="utf-8")
    ui_qa = (ROOT / "scripts" / "qa_ui_crawler.py").read_text(encoding="utf-8")

    service_nav_paths_static = static_theme.split("var SERVICE_NAV_PATHS = [", 1)[1].split("];", 1)[0]
    service_nav_paths_root = root_theme.split("var SERVICE_NAV_PATHS = [", 1)[1].split("];", 1)[0]

    for route in (
        "/dashboard", "/training-log", "/plan", "/workout", "/report", "/my-data",
        "/badges", "/chat", "/coach", "/clubs", "/challenge", "/community",
        "/pool", "/drill", "/injury", "/equipment", "/videos", "/glossary",
        "/faq", "/tutorial", "/profile", "/feedback", "/changelog",
    ):
        assert f"'{route}'" in service_nav_paths_static
        assert f"'{route}'" in service_nav_paths_root
        assert f"href: '{route}'" in service_nav

    for excluded_route in ("'/landing'", "'/login'", "'/register'", "'/admin'", "'/onboarding'", "'/privacy'", "'/terms'"):
        assert excluded_route not in service_nav_paths_static
        assert excluded_route not in service_nav_paths_root

    for marker in (
        "global-service-nav", "global-service-nav-toggle", "global-service-nav-backdrop",
        "aria-current", "MOBILE_QUERY", "aria-expanded", "aria-hidden", "inert",
        "swimmate:service-nav-ready", "fetch('/auth/me'", "profile.is_demo",
        "profile.is_admin", "textContent = displayName",
    ):
        assert marker in service_nav

    assert "--global-service-nav-width: 268px" in static_style
    assert "body.global-service-nav-enabled" in static_style
    assert "body.global-service-nav-open" in static_style
    assert "@media (max-width: 900px)" in static_style
    assert "공통 레이아웃 안전망" in static_style
    assert ":where(main, section, article, aside, nav, header, footer, .app)" in static_style
    assert "overflow-wrap: anywhere" in static_style
    assert "word-break: keep-all" in static_style
    assert static_style == root_style
    assert "SERVICE_NAV_PATHS" in ui_qa
    assert "def check_service_navigation(page, path):" in ui_qa
    assert "check_service_navigation(page, path)" in ui_qa
    assert "service_navigation_mobile_open_failed" in ui_qa
    assert "service_navigation_mobile_escape_close_failed" in ui_qa
    assert ":not(.global-service-nav-link):not(.service-nav-link)" in ui_qa


def test_service_pages_use_one_authenticated_global_header_and_swimming_favicon():
    static_theme = (ROOT / "frontend" / "static" / "theme.js").read_text(encoding="utf-8")
    root_theme = (ROOT / "frontend" / "theme.js").read_text(encoding="utf-8")
    static_style = (ROOT / "frontend" / "static" / "style.css").read_text(encoding="utf-8")
    root_style = (ROOT / "frontend" / "style.css").read_text(encoding="utf-8")
    service_nav = (ROOT / "frontend" / "static" / "service-nav.js").read_text(encoding="utf-8")
    community = (ROOT / "frontend" / "community.html").read_text(encoding="utf-8")
    manifest = (ROOT / "frontend" / "manifest.json").read_text(encoding="utf-8")
    favicon = (ROOT / "frontend" / "static" / "icons" / "favicon.svg").read_text(encoding="utf-8")
    api_main = (ROOT / "api" / "main.py").read_text(encoding="utf-8")
    ui_qa = (ROOT / "scripts" / "qa_ui_crawler.py").read_text(encoding="utf-8")

    for theme in (static_theme, root_theme):
        header_paths = theme.split("var APP_HEADER_PATHS = [", 1)[1].split("];", 1)[0]
        for route in ("/landing", "/dashboard", "/plan", "/training-log", "/report", "/profile", "/admin", "/privacy", "/terms", "/onboarding"):
            assert f"'{route}'" in header_paths
        for route in ("/login", "/register", "/nickname"):
            assert f"'{route}'" not in header_paths
        for marker in (
            "global-app-header", "global-app-home", "href=\"/landing\"",
            "global-app-profile", "href=\"/profile\"", "global-app-logout",
            "theme-toggle-btn", "loadHeaderSession", "fetch('/auth/me'",
            "fetch('/auth/logout'", "swimmate:app-header-ready",
            "/static/icons/favicon.svg",
        ):
            assert marker in theme

    assert static_style == root_style
    for marker in (
        ".global-app-header", ".global-app-header-actions", ".global-app-action[hidden]",
        "body.global-app-header-enabled .header", "@media (max-width: 700px)",
        "inset: var(--global-app-header-height, 70px) auto 0 0",
    ):
        assert marker in static_style

    assert "favicon.svg" in manifest
    assert "<circle" in favicon and "<path" in favicon and "#48cae4" in favicon
    assert "image/svg+xml" in api_main
    assert "favicon.svg" in service_nav
    assert "document.querySelector('.global-app-header-left')" in service_nav
    assert "document.getElementById('sidebar-toggle-btn')" in static_theme
    assert "#global-app-header .global-app-header-actions" in community
    assert "commonActions.insertAdjacentHTML('afterbegin', notificationHtml)" in community
    assert "APP_HEADER_PATHS" in ui_qa
    assert "def check_global_app_header(page, path):" in ui_qa
    assert "check_global_app_header(page, path)" in ui_qa
    assert "global_app_header_action_order" in ui_qa
    assert "global_app_header_mobile_layout" in ui_qa
    assert "global_app_header_chat_history_missing" in ui_qa
    assert "global_app_header_notification_missing" in ui_qa


def test_render_deploy_hook_is_triggered_for_backend_changes():
    workflow = (ROOT / ".github" / "workflows" / "render-deploy.yml").read_text(encoding="utf-8")

    assert "RENDER_DEPLOY_HOOK" in workflow
    assert '"api/**"' in workflow
    assert 'curl --fail --silent --show-error --request POST' in workflow


def test_plan_completion_is_saved_only_with_a_training_log():
    api = (ROOT / "api" / "routers" / "training_log.py").read_text(encoding="utf-8")
    plan = (ROOT / "frontend" / "plan.html").read_text(encoding="utf-8")
    log = (ROOT / "frontend" / "training_log.html").read_text(encoding="utf-8")

    assert '@router.get("/plan-completions")' in api
    assert api.index('@router.get("/plan-completions")') < api.index('@router.put("/{log_id}")')
    assert "INSERT INTO plan_completions" in api
    assert "DELETE FROM plan_completions WHERE training_log_id" in api
    assert "plan_completion" in plan
    assert "loadPlanCompletions" in plan
    assert "swimtech_completed_days" not in plan
    assert "pendingPlanCompletion" in log


def test_plan_p0_improvements_are_kept():
    plan = (ROOT / "frontend" / "plan.html").read_text(encoding="utf-8")
    checklist = (ROOT / "FEATURE_CHECKLIST.md").read_text(encoding="utf-8")

    assert "SESSION_LIBRARY_EXTRAS" in plan
    assert "GOAL_TO_TAGS" in plan
    assert "data-cycle-level" in plan
    assert "validatePlanQuality" in plan
    assert "myplan-filter-panel" in plan
    assert "addSavedPlanToTrainingLog" in plan
    assert "buildTrainingMemo" in plan
    assert "shareCustomPlan" in plan and "sharePresetPlan" in plan
    assert "## P0 — 완료" in checklist


def test_plan_p1_improvements_are_kept():
    plan = (ROOT / "frontend" / "plan.html").read_text(encoding="utf-8")
    coach_page = (ROOT / "frontend" / "coach.html").read_text(encoding="utf-8")
    coach_api = (ROOT / "api" / "routers" / "coach.py").read_text(encoding="utf-8")
    checklist = (ROOT / "FEATURE_CHECKLIST.md").read_text(encoding="utf-8")

    assert "pace-helper-panel" in plan
    assert "convertPoolTime" in plan
    assert "BUILDER_TEMPLATE_KEY" in plan
    assert "saveCurrentBuilderTemplate" in plan
    assert "set-detail-grid" in plan
    assert "loadTrainingFeedbackLoop" in plan
    assert "generateCoachPlanDraft" in coach_page
    assert "plan_meta" in coach_api
    assert "## P1 — 완료" in checklist


def test_plan_p2_improvements_are_kept():
    plan = (ROOT / "frontend" / "plan.html").read_text(encoding="utf-8")
    log = (ROOT / "frontend" / "training_log.html").read_text(encoding="utf-8")
    report_page = (ROOT / "frontend" / "report.html").read_text(encoding="utf-8")
    report_api = (ROOT / "api" / "routers" / "report.py").read_text(encoding="utf-8")
    health_import = (ROOT / "api" / "routers" / "health_import.py").read_text(encoding="utf-8")
    checklist = (ROOT / "FEATURE_CHECKLIST.md").read_text(encoding="utf-8")

    assert 'data-tab="analysis"' in plan
    assert "ANALYSIS_ISSUES" in plan
    assert "generateAnalysisRecommendationPlan" in plan
    assert "교정 포인트 기반 플랜 추천" in plan
    assert "영상 분석에서 확인한 교정 포인트" not in plan
    assert "AI 분석 결과 기반 플랜 추천" not in plan
    assert 'data-tab="race"' in plan
    assert "RACE_EVENT_PROFILES" in plan
    assert "generateRacePreparationPlan" in plan
    assert "mobile-add-day" in plan
    assert "moveCardInDay" in plan
    assert 'id="btn-open-import"' in log and "validateImportFile" in log
    assert 'disabled aria-disabled="true"' in log
    assert 'data-feature-state="disabled"' in log
    assert "워치 데이터 가져오기 (준비 중)" in log
    assert "if (_importBtn && !_importBtn.disabled)" in log
    assert "#btn-open-import[disabled][aria-disabled='true'][data-feature-state='disabled']" in (
        ROOT / "scripts" / "qa_ui_crawler.py"
    ).read_text(encoding="utf-8")
    assert "_validate_preview_upload" in health_import
    assert '"customer_id": cid' in health_import
    assert "plan_performance" in report_api
    assert "renderPlanPerformance" in report_page
    assert "## P2 — 완료" in checklist


def test_monthly_report_uses_training_log_identity_and_average_distance():
    report_api = (ROOT / "api" / "routers" / "report.py").read_text(encoding="utf-8")
    report_page = (ROOT / "frontend" / "report.html").read_text(encoding="utf-8")

    assert "from routers.auth import decode_token" in report_api
    assert "def _get_customer_id" in report_api
    assert "customer_id = _get_customer_id(request)" in report_api
    assert "_calc_monthly_stats(customer_id, year, month)" in report_api
    assert '"avg_distance"' in report_api
    assert "LIKE '%@%'" not in report_api
    assert "POSITION('@' IN COALESCE(tl.memo, ''))" in report_api
    assert "stat-avg" in report_page
    assert "평균 거리 (m)" in report_page
    assert "const initialMonth = new Date();" in report_page
    assert "let curYear = initialMonth.getFullYear();" in report_page
    assert "let curMonth = initialMonth.getMonth() + 1;" in report_page
    assert "max-width: 1540px" in report_page
    assert "grid-template-columns: minmax(340px, 380px) minmax(0,1fr)" in report_page
    assert "@media (max-width: 1180px)" in report_page
    assert ".stat-value" in report_page and "white-space: nowrap" in report_page
    assert "grid-template-columns: auto minmax(118px, 1fr) minmax(92px, auto)" in report_page


def test_training_logs_persist_structured_set_execution_data():
    api = (ROOT / "api" / "routers" / "training_log.py").read_text(encoding="utf-8")
    plan = (ROOT / "frontend" / "plan.html").read_text(encoding="utf-8")
    log = (ROOT / "frontend" / "training_log.html").read_text(encoding="utf-8")
    report_api = (ROOT / "api" / "routers" / "report.py").read_text(encoding="utf-8")
    report_page = (ROOT / "frontend" / "report.html").read_text(encoding="utf-8")
    api_qa = (ROOT / "scripts" / "qa_runner.py").read_text(encoding="utf-8")

    assert "class TrainingSetRequest(BaseModel)" in api
    assert '@router.get("/{log_id}/sets")' in api
    assert '@router.put("/{log_id}/sets")' in api
    assert "_replace_training_sets" in api and "_fetch_training_sets" in api
    assert "DELETE FROM training_log_sets WHERE training_log_id" in api
    assert "buildTrainingSets" in plan and "target_cycle_seconds" in plan
    assert "pendingTrainingSets" in log and "set_summary" in log
    assert '"planned_sets"' in report_api and '"set_completion_rate"' in report_api
    assert "plan-set-rate" in report_page and "plan-set-fill" in report_page
    assert "/sets" in api_qa and "세트 단위 기록 조회·수행 갱신" in api_qa


def test_poolside_workout_executes_and_saves_one_set_at_a_time():
    api = (ROOT / "api" / "routers" / "training_log.py").read_text(encoding="utf-8")
    main = (ROOT / "api" / "main.py").read_text(encoding="utf-8")
    log = (ROOT / "frontend" / "training_log.html").read_text(encoding="utf-8")
    workout = (ROOT / "frontend" / "workout.html").read_text(encoding="utf-8")
    api_qa = (ROOT / "scripts" / "qa_runner.py").read_text(encoding="utf-8")
    ui_qa = (ROOT / "scripts" / "qa_ui_crawler.py").read_text(encoding="utf-8")

    assert 'class TrainingSetExecutionRequest(BaseModel)' in api
    assert '@router.patch("/{log_id}/sets/{set_id}")' in api
    assert "SELECT customer_id FROM training_logs WHERE id = %s FOR UPDATE" in api
    assert "completed_distance_m" in api and "actual_cycle_seconds" in api and "rpe" in api
    assert '@app.get("/workout")' in main and '_serve("workout.html")' in main
    assert 'href="/workout?log=${l.id}"' in log
    assert 'id="timer-value"' in workout
    assert "navigator.wakeLock.request('screen')" in workout
    assert "completeRep" in workout and "saveExecution" in workout and "openExecutionSheet" in workout
    assert (ROOT / "docs" / "screenshots" / "poolside-workout.png").exists()
    assert "풀사이드 단일 세트 수행 저장" in api_qa and ".patch(" in api_qa
    assert '("/workout", "풀사이드 훈련")' in ui_qa
    assert '"#timer-value"' in ui_qa and '"#wake-lock-btn"' in ui_qa


def test_club_class_and_scoped_roles_are_connected_end_to_end():
    api = (ROOT / "api" / "routers" / "clubs.py").read_text(encoding="utf-8")
    main = (ROOT / "api" / "main.py").read_text(encoding="utf-8")
    page = (ROOT / "frontend" / "clubs.html").read_text(encoding="utf-8")
    landing = (ROOT / "frontend" / "landing.html").read_text(encoding="utf-8")
    coach_page = (ROOT / "frontend" / "coach.html").read_text(encoding="utf-8")
    activity_log = (ROOT / "api" / "activity_log.py").read_text(encoding="utf-8")
    api_qa = (ROOT / "scripts" / "qa_runner.py").read_text(encoding="utf-8")
    ui_qa = (ROOT / "scripts" / "qa_ui_crawler.py").read_text(encoding="utf-8")

    assert "_registered_coach_id" in api
    assert '@router.post("")' in api
    assert '@router.get("/mine")' in api
    assert '@router.post("/{club_id}/classes")' in api
    assert '@router.post("/classes/join")' in api
    assert '@router.put("/{club_id}/members/{member_customer_id}/role")' in api
    assert '@router.put("/{club_id}/classes/{class_id}/members/{member_customer_id}/role")' in api
    assert "등록 코치만 클럽과 반을 만들 수 있습니다." in api
    assert "담당 코치는 학생이나 보조 코치로 변경할 수 없습니다." in api
    assert "담당 중인 반이 있어 클럽에서 나갈 수 없습니다." in api
    assert 'or class_role == "coach"' in api
    assert "is_active_member" in api
    assert "UPDATE swim_class_members class_member\n                SET role = 'student'" not in api
    assert "include_router(clubs.router" in main
    assert '@app.get("/clubs")' in main and '_serve("clubs.html")' in main
    for selector in ["clubs-grid", "join-class-form", "join-code", "club-create-card", "club-modal", "class-modal"]:
        assert f'id="{selector}"' in page
    assert "GROUP OPERATIONS" in page and "개인 운동 · 훈련 플랜" in page
    assert 'href="/clubs"' in landing and 'href="/clubs"' in coach_page
    assert '"/clubs":          "클럽·반"' in activity_log
    assert (ROOT / "docs" / "screenshots" / "clubs-classes.png").exists()
    assert "클럽 생성→반 코드 참여→역할 권한 경계" in api_qa
    assert 'student_sess.post(f"{BASE}/api/clubs/classes/join"' in api_qa
    assert '("/clubs", "클럽·반")' in ui_qa
    assert '"#clubs-grid"' in ui_qa and '"#class-modal"' in ui_qa


def test_class_schedule_attendance_and_notices_are_connected_end_to_end():
    api = (ROOT / "api" / "routers" / "club_operations.py").read_text(encoding="utf-8")
    main = (ROOT / "api" / "main.py").read_text(encoding="utf-8")
    page = (ROOT / "frontend" / "clubs.html").read_text(encoding="utf-8")
    admin_api = (ROOT / "api" / "routers" / "admin.py").read_text(encoding="utf-8")
    admin_page = (ROOT / "frontend" / "admin.html").read_text(encoding="utf-8")
    api_qa = (ROOT / "scripts" / "qa_runner.py").read_text(encoding="utf-8")
    ui_qa = (ROOT / "scripts" / "qa_ui_crawler.py").read_text(encoding="utf-8")

    assert "include_router(club_operations.router" in main
    assert '@router.get("/operations/mine")' in api
    assert '@router.post("/{club_id}/classes/{class_id}/sessions")' in api
    assert '@router.put("/{club_id}/classes/{class_id}/sessions/{session_id}/attendance")' in api
    assert '@router.post("/{club_id}/notices")' in api
    assert '@router.post("/{club_id}/notices/{notice_id}/read")' in api
    assert '@router.get("/{club_id}/classes/{class_id}/analytics")' in api
    assert 'or class_role == "coach"' in api
    assert "현재 반 학생만 출석 처리할 수 있습니다." in api
    assert "개인 훈련량은 학생이 현재 코치 코드로 별도 연동한 경우에만 표시됩니다." in api
    for selector in ["operations-overview", "upcoming-sessions", "recent-notices", "attendance-modal"]:
        assert f'id="{selector}"' in page
    assert "createSession" in page and "saveAttendance" in page and "markNoticeRead" in page
    assert 'id="class-analytics"' in page and "renderClassAnalytics" in page
    for metric in ["active_clubs", "active_classes", "class_sessions_30d", "attendance_rate_30d", "active_notices"]:
        assert f'"{metric}"' in admin_api
    for selector in ["h-active-clubs", "h-active-classes", "h-class-sessions", "h-attendance-rate", "h-active-notices"]:
        assert f'id="{selector}"' in admin_page
    assert "반 일정→출석→공지·읽음 권한 경계" in api_qa
    assert "코치 반 수행·출석 분석과 개인훈련 동의 경계" in api_qa
    assert '"#operations-overview"' in ui_qa and '"#attendance-modal"' in ui_qa


def test_timed_test_sets_and_course_specific_personal_bests_are_connected_end_to_end():
    api = (ROOT / "api" / "routers" / "benchmarks.py").read_text(encoding="utf-8")
    main = (ROOT / "api" / "main.py").read_text(encoding="utf-8")
    log_page = (ROOT / "frontend" / "training_log.html").read_text(encoding="utf-8")
    report_api = (ROOT / "api" / "routers" / "report.py").read_text(encoding="utf-8")
    report_page = (ROOT / "frontend" / "report.html").read_text(encoding="utf-8")
    admin_api = (ROOT / "api" / "routers" / "admin.py").read_text(encoding="utf-8")
    admin_page = (ROOT / "frontend" / "admin.html").read_text(encoding="utf-8")
    api_qa = (ROOT / "scripts" / "qa_runner.py").read_text(encoding="utf-8")
    ui_qa = (ROOT / "scripts" / "qa_ui_crawler.py").read_text(encoding="utf-8")

    assert "include_router(benchmarks.router" in main
    assert '@router.post("")' in api and '@router.get("")' in api and '@router.delete("/{result_id}")' in api
    assert "stroke_type, distance_m, pool_length" in api
    assert "previous_best_ms" in api and "improvement_ms" in api
    assert "DELETE FROM swim_test_results WHERE id = %s AND customer_id = %s" in api
    for selector in ["benchmark-section", "btn-open-benchmark", "benchmark-modal-backdrop"]:
        assert f'id="{selector}"' in log_page
    assert "benchmark_performance" in report_api and 'id="benchmark-performance"' in report_page
    for metric in ["test_results_30d", "test_users_30d", "personal_bests_30d"]:
        assert f'"{metric}"' in admin_api
    for selector in ["h-test-results", "h-test-users", "h-personal-bests"]:
        assert f'id="{selector}"' in admin_page
    assert "테스트 세트 저장→코스별 PB 판정" in api_qa
    assert '"#benchmark-section"' in ui_qa and '"#benchmark-performance"' in ui_qa


def test_qa_scripts_cover_training_report_and_advisor_flows():
    api_qa = (ROOT / "scripts" / "qa_runner.py").read_text(encoding="utf-8")
    ui_qa = (ROOT / "scripts" / "qa_ui_crawler.py").read_text(encoding="utf-8")
    qa_workflow = (ROOT / ".github" / "workflows" / "qa.yml").read_text(encoding="utf-8")
    credential_validator = (ROOT / "scripts" / "validate_qa_credentials.py").read_text(encoding="utf-8")
    admin_page = (ROOT / "frontend" / "admin.html").read_text(encoding="utf-8")
    admin_api = (ROOT / "api" / "routers" / "admin.py").read_text(encoding="utf-8")
    checklist = (ROOT / "FEATURE_CHECKLIST.md").read_text(encoding="utf-8")

    assert "/api/training-log/goal" in api_qa
    assert "/api/report/monthly" in api_qa
    assert "/api/dashboard/training-advisor" in api_qa
    assert "/api/admin/training-health" in api_qa
    assert "/auth/demo" in api_qa
    assert "Portfolio demo mode" in api_qa
    assert "월간 리포트↔훈련 일지 데이터 연동" in api_qa
    assert "관리자 훈련 운영 API" in api_qa
    assert "plan_completion" in api_qa
    assert "avg_distance" in api_qa
    assert "PAGE_EXPECTATIONS" in ui_qa
    assert "#demo-btn" in ui_qa
    assert "check_public_demo_entry" in ui_qa
    assert ".advisor-card" in ui_qa
    assert "#stat-avg" in ui_qa
    assert "[data-tab='training-health']" in ui_qa
    assert "P3 Training Advisor" in ui_qa
    assert "pip install playwright requests" in qa_workflow
    for secret_name in [
        "QA_USERNAME", "QA_PASSWORD", "QA_EMAIL",
        "QA_STUDENT_USERNAME", "QA_STUDENT_PASSWORD", "QA_STUDENT_EMAIL",
        "ADMIN_ID", "ADMIN_PW",
    ]:
        assert secret_name in qa_workflow
        assert secret_name in credential_validator
    assert "Unified Quality Gate" in qa_workflow
    assert "needs: [core, production-api]" in qa_workflow
    assert "validate_qa_credentials.py" in qa_workflow
    assert "잘못된 비밀번호 거부" in api_qa
    assert "인증 쿠키 보안 속성" in api_qa
    assert "make_fallback_account" not in api_qa
    assert "fallback_username" not in ui_qa
    assert "python scripts/qa_runner.py --no-admin" not in qa_workflow
    assert not (ROOT / ".github" / "workflows" / "ci.yml").exists()
    assert not (ROOT / "tests" / "run_tests.bat").exists()
    assert '@router.get("/training-health")' in admin_api
    assert "훈련 운영" in admin_page
    assert "새 기능 / 새 화면 / 새 API는 반드시" in checklist


def test_portfolio_demo_mode_contract():
    auth_api = (ROOT / "api" / "routers" / "auth.py").read_text(encoding="utf-8")
    login_page = (ROOT / "frontend" / "login.html").read_text(encoding="utf-8")
    dashboard_page = (ROOT / "frontend" / "dashboard.html").read_text(encoding="utf-8")
    api_qa = (ROOT / "scripts" / "qa_runner.py").read_text(encoding="utf-8")
    ui_qa = (ROOT / "scripts" / "qa_ui_crawler.py").read_text(encoding="utf-8")
    checklist = (ROOT / "FEATURE_CHECKLIST.md").read_text(encoding="utf-8")

    assert '@router.post("/demo")' in auth_api
    assert "DEMO_USERNAME" in auth_api
    assert "portfolio_demo" in auth_api
    assert "_ensure_demo_user_and_seed" in auth_api
    assert "create_token(DEMO_USERNAME, customer_id, is_demo=True, auth_version=auth_version)" in auth_api
    assert "create_refresh_token(DEMO_USERNAME, customer_id, is_demo=True, auth_version=auth_version)" in auth_api
    assert "training_logs" in auth_api
    assert "training_goals" in auth_api
    assert "plan_completions" in auth_api
    assert "training_readiness" in auth_api
    assert "user_badges" in auth_api
    assert '"is_demo":         is_demo' in auth_api
    assert 'payload.get("is_demo")' in auth_api
    assert "demo-btn" in login_page
    assert "startDemo" in login_page
    assert "/auth/demo" in login_page
    assert "loginData.redirect" in login_page
    assert "loginData.is_admin ? '/admin'" in login_page
    assert "safeNextPath() || loginData.redirect || '/landing'" in login_page
    assert "onboarding_done" not in login_page
    assert '@router.get("/onboarding")' in auth_api
    assert '@router.put("/onboarding")' in auth_api
    assert "preferred_pool_length" in auth_api
    onboarding_page = (ROOT / "frontend" / "onboarding.html").read_text(encoding="utf-8")
    assert '/static/icons/logo.svg' in onboarding_page
    assert '/static/logo.svg' not in onboarding_page
    assert "demo-banner" in dashboard_page
    assert "me.is_demo" in dashboard_page
    assert "/auth/demo" in api_qa
    assert "Portfolio demo mode" in api_qa
    assert "#demo-btn" in ui_qa
    assert "check_public_demo_entry" in ui_qa
    assert "포트폴리오 비회원 체험 모드" in checklist


def test_login_form_submits_with_enter_key():
    login_page = (ROOT / "frontend" / "login.html").read_text(encoding="utf-8")
    ui_qa = (ROOT / "scripts" / "qa_ui_crawler.py").read_text(encoding="utf-8")

    assert '<form id="login-form" novalidate>' in login_page
    assert 'id="username" name="username"' in login_page
    assert 'id="password" name="password"' in login_page
    assert 'id="login-btn" type="submit"' in login_page
    assert "document.getElementById('login-form').addEventListener('submit'" in login_page
    assert "event.preventDefault();" in login_page
    assert "if (btn.disabled) return;" in login_page
    assert "onkeydown=" not in login_page
    assert 'page.keyboard.press("Enter")' in ui_qa


def test_personal_data_export_and_account_security_are_qa_mapped():
    main = (ROOT / "api" / "main.py").read_text(encoding="utf-8")
    auth_api = (ROOT / "api" / "routers" / "auth.py").read_text(encoding="utf-8")
    account_api = (ROOT / "api" / "routers" / "account.py").read_text(encoding="utf-8")
    profile = (ROOT / "frontend" / "profile.html").read_text(encoding="utf-8")
    privacy = (ROOT / "frontend" / "privacy.html").read_text(encoding="utf-8")
    api_qa = (ROOT / "scripts" / "qa_runner.py").read_text(encoding="utf-8")
    ui_qa = (ROOT / "scripts" / "qa_ui_crawler.py").read_text(encoding="utf-8")

    assert "include_router(account.router" in main
    for route in ['@router.post("/export")', '@router.post("/password")', '@router.post("/logout-all")']:
        assert route in account_api
    assert '"export_format": "swimmate-personal-data"' in account_api
    assert "비밀번호 해시, JWT" in account_api
    assert "_verify_sensitive_action" in account_api
    assert "auth_version = COALESCE(auth_version, 0) + 1" in account_api
    assert "_session_payload_is_current" in auth_api
    assert 'payload.get("auth_version")' in auth_api
    assert 'RuntimeError("SECRET_KEY is required in the Render environment")' in auth_api
    assert 'ADMIN_ID = os.getenv("ADMIN_ID", "").strip()' in auth_api
    assert 'ADMIN_PW = os.getenv("ADMIN_PW", "")' in auth_api
    assert '"swimtech1234"' not in auth_api
    assert "DeleteAccountRequest" in auth_api
    assert 'body.confirmation.strip() != "탈퇴"' in auth_api
    for selector in [
        "data-export-panel", "data-export-btn", "password-panel", "password-save-btn",
        "session-security-panel", "logout-all-btn",
    ]:
        assert f'id="{selector}"' in profile
    assert "내 데이터 내보내기" in privacy and "전체 로그아웃" in privacy
    assert "개인 데이터 JSON 내보내기 + 비밀번호 재확인" in api_qa
    assert "계정 보안 변경의 현재 비밀번호 경계" in api_qa
    assert '"/profile": {' in ui_qa and '"#data-export-btn"' in ui_qa


def test_personal_swim_data_dashboard_is_connected_and_qa_mapped():
    main = (ROOT / "api" / "main.py").read_text(encoding="utf-8")
    account_api = (ROOT / "api" / "routers" / "account.py").read_text(encoding="utf-8")
    activity_log = (ROOT / "api" / "activity_log.py").read_text(encoding="utf-8")
    page = (ROOT / "frontend" / "my-data.html").read_text(encoding="utf-8")
    landing = (ROOT / "frontend" / "landing.html").read_text(encoding="utf-8")
    dashboard = (ROOT / "frontend" / "dashboard.html").read_text(encoding="utf-8")
    profile = (ROOT / "frontend" / "profile.html").read_text(encoding="utf-8")
    api_qa = (ROOT / "scripts" / "qa_runner.py").read_text(encoding="utf-8")
    ui_qa = (ROOT / "scripts" / "qa_ui_crawler.py").read_text(encoding="utf-8")

    assert '@router.get("/insights")' in account_api
    for key in [
        '"lifetime"', '"recent_90_days"', '"monthly_trend"',
        '"stroke_distribution"', '"pool_distribution"', '"recording_habits"',
        '"personal_bests"', '"insight_cards"',
    ]:
        assert key in account_api
    assert '"privacy_scope": "authenticated_customer_only"' in account_api
    assert '@app.get("/my-data")' in main and 'return _serve("my-data.html")' in main
    assert '"/my-data":        "내 수영 데이터"' in activity_log
    for selector in [
        "data-content", "lifetime-distance", "monthly-trend-chart",
        "stroke-distribution", "recording-habits", "insight-grid",
        "personal-best-panel", "pb-body",
    ]:
        assert f'id="{selector}"' in page
    assert "/api/account/insights" in page
    assert "JSON은 원본 보관·이동용" in page
    assert 'href="/my-data"' in landing
    assert 'href="/my-data"' in dashboard
    assert 'id="my-data-dashboard-link" href="/my-data"' in profile
    assert "내 수영 데이터 장기 대시보드 연동" in api_qa
    assert '("/my-data", "내 수영 데이터")' in ui_qa
    assert '"/my-data": {' in ui_qa
    assert '"wait_for_any_text"' in ui_qa


def test_feature_tutorial_is_split_by_purpose_and_qa_mapped():
    main = (ROOT / "api" / "main.py").read_text(encoding="utf-8")
    activity_log = (ROOT / "api" / "activity_log.py").read_text(encoding="utf-8")
    landing = (ROOT / "frontend" / "landing.html").read_text(encoding="utf-8")
    tutorial = (ROOT / "frontend" / "tutorial.html").read_text(encoding="utf-8")
    ui_qa = (ROOT / "scripts" / "qa_ui_crawler.py").read_text(encoding="utf-8")
    screenshot_dir = ROOT / "frontend" / "static" / "tutorial"
    frontend_vercel = json.loads((ROOT / "frontend" / "vercel.json").read_text(encoding="utf-8"))
    guide_files = {
        "personal": "tutorial_personal.html",
        "record": "tutorial_record.html",
        "data": "tutorial_data.html",
        "coach": "tutorial_coach.html",
        "help": "tutorial_help.html",
    }
    guides = {
        slug: (ROOT / "frontend" / filename).read_text(encoding="utf-8")
        for slug, filename in guide_files.items()
    }

    assert '@app.get("/tutorial")' in main
    assert 'return _serve("tutorial.html")' in main
    assert '@app.get("/tutorial/{guide_name}")' in main
    assert '"/tutorial":      "기능 가이드"' in activity_log
    assert 'id="tutorial-guide-card"' in landing and 'href="/tutorial"' in landing
    assert 'id="tutorial-hero"' in tutorial
    assert 'id="guide-categories"' in tutorial
    assert 'id="quick-start"' in tutorial
    for slug, filename in guide_files.items():
        guide_path = f"/tutorial/{slug}"
        assert f'"{slug}": "{filename}"' in main
        assert f'href="{guide_path}"' in tutorial
        assert f'("{guide_path}", "가이드' in ui_qa
        assert f'"{guide_path}": {{' in ui_qa
        assert f'"{guide_path}":' in activity_log
        assert f"'{guide_path}'" in (ROOT / "frontend" / "static" / "theme.js").read_text(encoding="utf-8")
        assert f"'{guide_path}'" in (ROOT / "frontend" / "theme.js").read_text(encoding="utf-8")
        assert f'"{guide_path}"' in ui_qa
        rewrite = {"source": guide_path, "destination": f"/tutorial_{slug}"}
        assert rewrite in frontend_vercel["rewrites"]
    all_guides = "\n".join(guides.values())
    assert all_guides.count("data-tutorial-shot=") >= 12
    assert all_guides.count('src="/static/tutorial/') >= 12
    assert len(list(screenshot_dir.glob("*"))) >= 12
    assert "운동 스크린샷 등록 순서" in guides["record"]
    assert "실제로 한 운동이 맞나요?" in guides["record"]
    assert "원본 이미지와 비용·사용량 안내" in guides["record"]
    assert "무료 AI 사용량이 소진되면" in guides["record"]
    assert "워치 직접 연동과 건강 전체 파일 가져오기는 아직 지원하지 않습니다" in guides["record"]
    assert "AI 스크린샷에서 확인한 영법별 거리" in guides["data"]
    assert "영상 영법 분석은 제공하지 않음" in guides["help"]
    assert "tutorialDetail" in (ROOT / "frontend" / "static" / "service-nav.js").read_text(encoding="utf-8")
    assert 'expected_active_route = "/tutorial" if route.startswith("/tutorial/") else route' in ui_qa
    assert '("/tutorial", "기능 가이드")' in ui_qa
    assert '"/tutorial": {' in ui_qa


def test_landing_url_and_editable_onboarding_are_qa_mapped():
    auth_api = (ROOT / "api" / "routers" / "auth.py").read_text(encoding="utf-8")
    api_main = (ROOT / "api" / "main.py").read_text(encoding="utf-8")
    login = (ROOT / "frontend" / "login.html").read_text(encoding="utf-8")
    landing = (ROOT / "frontend" / "landing.html").read_text(encoding="utf-8")
    onboarding = (ROOT / "frontend" / "onboarding.html").read_text(encoding="utf-8")
    profile = (ROOT / "frontend" / "profile.html").read_text(encoding="utf-8")
    frontend_vercel = json.loads((ROOT / "frontend" / "vercel.json").read_text(encoding="utf-8"))
    api_qa = (ROOT / "scripts" / "qa_runner.py").read_text(encoding="utf-8")
    ui_qa = (ROOT / "scripts" / "qa_ui_crawler.py").read_text(encoding="utf-8")

    assert "window.location.href = loginData.is_admin ? '/admin'" in login
    assert "safeNextPath() || loginData.redirect || '/landing'" in login
    assert '"redirect": "/admin" if is_admin else "/landing"' in auth_api
    assert auth_api.count('"redirect": "/landing"') >= 2
    assert auth_api.count('else "/landing"') >= 2
    assert 'RedirectResponse(url="/landing", status_code=307)' in api_main
    assert {
        "source": "/",
        "destination": "/landing",
        "permanent": False,
    } in frontend_vercel["redirects"]
    assert {
        "source": "/app",
        "destination": "/landing",
        "permanent": False,
    } in frontend_vercel["redirects"]
    assert not any(rule.get("source") in {"/", "/app"} for rule in frontend_vercel["rewrites"])

    for html_path in (ROOT / "frontend").glob("*.html"):
        html = html_path.read_text(encoding="utf-8")
        assert 'href="/"' not in html, f"{html_path.name} 홈 링크가 /landing이 아님"

    for selector in [
        "training-profile-panel", "p-training-level", "p-training-goal",
        "p-training-weekly", "p-training-pool", "onboarding-edit-link",
    ]:
        assert f'id="{selector}"' in profile
    assert 'href="/onboarding?mode=edit"' in profile
    assert "isEditMode" in onboarding
    assert "맞춤 훈련 설정을 수정해요" in onboarding
    assert "isEditMode ? '/profile'" in onboarding
    assert "color: #edfaff;" in onboarding
    assert "onboarding-reminder" in landing and "me.needs_onboarding" in landing
    assert "대표 홈 리다이렉트" in api_qa
    assert "check_home_link_targets" in ui_qa
    assert '"property": "color", "value": "rgb(237, 250, 255)"' in ui_qa
    assert '("/onboarding?mode=edit", "맞춤 훈련 설정 수정")' in ui_qa


def test_plan_p3_improvements_are_kept():
    dashboard_page = (ROOT / "frontend" / "dashboard.html").read_text(encoding="utf-8")
    dashboard_api = (ROOT / "api" / "routers" / "dashboard.py").read_text(encoding="utf-8")
    checklist = (ROOT / "FEATURE_CHECKLIST.md").read_text(encoding="utf-8")

    assert '@router.get("/training-advisor")' in dashboard_api
    assert "_build_training_advisor" in dashboard_api
    assert '"training_level": level' in dashboard_api
    assert '"training_goal": goal' in dashboard_api
    assert "preferred_pool_length" in dashboard_api
    assert "plan_completions" in dashboard_api
    assert "advisor-card" in dashboard_page
    assert "이번 주 훈련 추천" in dashboard_page
    assert "P3 Training Advisor" not in dashboard_page
    assert "renderTrainingAdvisor" in dashboard_page
    assert "loadTrainingAdvisor" in dashboard_page
    assert "/api/dashboard/training-advisor" in dashboard_page
    assert "## P3 — 완료" in checklist


def test_plan_p4_admin_quality_gate_is_kept():
    checklist = (ROOT / "FEATURE_CHECKLIST.md").read_text(encoding="utf-8")
    admin_api = (ROOT / "api" / "routers" / "admin.py").read_text(encoding="utf-8")
    admin_page = (ROOT / "frontend" / "admin.html").read_text(encoding="utf-8")
    qa_api = (ROOT / "scripts" / "qa_runner.py").read_text(encoding="utf-8")
    qa_ui = (ROOT / "scripts" / "qa_ui_crawler.py").read_text(encoding="utf-8")
    claude = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")

    assert "## P4 — 완료" in checklist
    assert "슈퍼 관리자 훈련 운영 대시보드 추가" in checklist
    assert "기능 추가 시 QA 스크립트 업데이트 의무화" in checklist
    assert '@router.get("/training-health")' in admin_api
    assert "training_logs" in admin_api
    assert "training_goals" in admin_api
    assert "custom_plans" in admin_api
    assert "plan_completions" in admin_api
    assert 'data-tab="training-health"' in admin_page
    assert "30일 훈련 일지" in admin_page
    assert "운영 체크포인트" in admin_page
    assert "/api/admin/training-health" in admin_page
    assert "/api/admin/training-health" in qa_api
    assert "[data-tab='training-health']" in qa_ui
    assert "운영 QA 스크립트 갱신 규칙" in claude


def test_plan_p5_readiness_advisor_is_fully_connected():
    dashboard_api = (ROOT / "api" / "routers" / "dashboard.py").read_text(encoding="utf-8")
    dashboard_page = (ROOT / "frontend" / "dashboard.html").read_text(encoding="utf-8")
    admin_api = (ROOT / "api" / "routers" / "admin.py").read_text(encoding="utf-8")
    admin_page = (ROOT / "frontend" / "admin.html").read_text(encoding="utf-8")
    api_qa = (ROOT / "scripts" / "qa_runner.py").read_text(encoding="utf-8")
    ui_qa = (ROOT / "scripts" / "qa_ui_crawler.py").read_text(encoding="utf-8")
    checklist = (ROOT / "FEATURE_CHECKLIST.md").read_text(encoding="utf-8")

    assert "## P5 — 완료" in checklist
    assert "오늘의 훈련 준비도 체크인 추가" in checklist
    assert "CREATE TABLE IF NOT EXISTS training_readiness" in dashboard_api
    assert "def _readiness_score" in dashboard_api
    assert '@router.get("/readiness")' in dashboard_api
    assert '@router.post("/readiness")' in dashboard_api
    assert '@router.delete("/readiness")' in dashboard_api
    assert "readiness_applied" in dashboard_api
    assert "회복 우선 세션" in dashboard_api
    assert 'id="readiness-form"' in dashboard_page
    assert 'id="readiness-score"' in dashboard_page
    assert 'id="advisor-readiness"' in dashboard_page
    assert "loadReadiness" in dashboard_page
    assert "/api/dashboard/readiness" in dashboard_page
    assert "readiness_checkins_7d" in admin_api
    assert "readiness_avg_score_7d" in admin_api
    assert 'id="h-readiness-checkins"' in admin_page
    assert 'id="h-readiness-score"' in admin_page
    assert "/api/dashboard/readiness" in api_qa
    assert "준비도 체크인→훈련 추천 연동" in api_qa
    assert "#readiness-form" in ui_qa
    assert "#h-readiness-checkins" in ui_qa


def test_admin_header_does_not_link_to_member_dashboard():
    admin_page = (ROOT / "frontend" / "admin.html").read_text(encoding="utf-8")

    assert '<a href="/dashboard" class="back-btn">' not in admin_page
    assert "← 대시보드" not in admin_page


def test_admin_navigation_uses_non_overlapping_responsive_sidebar():
    admin_page = (ROOT / "frontend" / "admin.html").read_text(encoding="utf-8")
    qa_ui = (ROOT / "scripts" / "qa_ui_crawler.py").read_text(encoding="utf-8")
    quality = (ROOT / "docs" / "QUALITY_GATE.md").read_text(encoding="utf-8")

    assert 'class="admin-shell"' in admin_page
    assert 'id="admin-sidebar"' in admin_page
    assert 'id="admin-menu-toggle"' in admin_page
    assert 'id="admin-nav-backdrop"' in admin_page
    assert '<nav class="admin-tabs" role="tablist"' in admin_page
    assert admin_page.count('role="tab"') == 8
    assert "grid-template-columns: 248px minmax(0, 1fr)" in admin_page
    assert "flex: 0 0 auto" in admin_page
    assert "@media (max-width: 900px)" in admin_page
    assert "setAdminNavOpen" in admin_page
    assert "activateAdminTab" in admin_page
    assert "관리자 모바일 드로어 8개 메뉴 비겹침" in qa_ui
    assert "admin_sidebar_mobile_layout" in qa_ui
    assert "관리자 전용 사이드 메뉴" in quality


def test_plan_p6_coach_code_ai_class_operations_are_connected():
    main = (ROOT / "api" / "main.py").read_text(encoding="utf-8")
    coach_api = (ROOT / "api" / "routers" / "coach.py").read_text(encoding="utf-8")
    coach_ai = (ROOT / "api" / "routers" / "coach_ai.py").read_text(encoding="utf-8")
    admin_api = (ROOT / "api" / "routers" / "admin.py").read_text(encoding="utf-8")
    coach_page = (ROOT / "frontend" / "coach.html").read_text(encoding="utf-8")
    admin_page = (ROOT / "frontend" / "admin.html").read_text(encoding="utf-8")
    api_qa = (ROOT / "scripts" / "qa_runner.py").read_text(encoding="utf-8")
    ui_qa = (ROOT / "scripts" / "qa_ui_crawler.py").read_text(encoding="utf-8")
    checklist = (ROOT / "FEATURE_CHECKLIST.md").read_text(encoding="utf-8")

    assert "## P6 — 완료" in checklist
    assert "AI 단체 강습 훈련표·강의 일정표 제작" in checklist
    assert "coach_ai.router" in main
    assert "verification_status" in coach_api
    assert "credential_number" in coach_api
    assert "_require_coach" in coach_api
    assert "_require_verified_coach" not in coach_api
    assert '@router.put("/verification")' in coach_api
    assert '"invite_code": invite_code' in coach_api
    assert 'verification_status = "pending" if all(credential_values) else "unverified"' in coach_api
    assert "_require_verified_coach" not in coach_ai
    assert "COALESCE(co.verification_status, 'pending') = 'verified'" not in coach_ai
    assert '@router.post("/ai/documents/generate")' in coach_ai
    assert '@router.post("/ai/documents/{document_id}/publish")' in coach_ai
    assert '@router.get("/class-documents")' in coach_ai
    assert '@router.post("/ai/class-insight")' in coach_ai
    assert "response_schema=ClassDocumentResult" in coach_ai
    assert "member_ref" in coach_ai and "roster_map" in coach_ai
    assert "generation_mode" in coach_ai and "template" in coach_ai
    assert '@router.get("/coaches")' in admin_api
    assert '@router.patch("/coaches/{coach_id}/verification")' in admin_api
    assert "coach_verification_events" in admin_api
    assert 'id="coach-verification-card"' in coach_page
    assert 'id="my-invite-code"' in coach_page
    assert '@router.delete("/my-coach")' in coach_api
    assert 'id="disconnect-coach-btn"' in coach_page
    assert "shareInviteCode" in coach_page
    assert 'id="coach-ai-studio"' in coach_page
    assert ".student-actions { display:grid; width:100%; grid-template-columns:repeat(4,minmax(0,1fr));" in coach_page
    assert 'id="coach-ai-insight"' in coach_page
    assert 'id="my-class-documents"' in coach_page
    assert 'data-tab="coaches"' in admin_page
    assert 'id="c-page-size"' in admin_page
    assert 'id="c-documents"' in admin_page
    assert "코치 등록→코드 즉시 발급" in api_qa
    assert "코드 연동→AI 강습안 생성·선택 배포·익명 브리핑" in api_qa
    assert "학생의 코치 연동 직접 해제" in api_qa
    assert "#coach-ai-studio" in ui_qa
    assert "#tab-coaches" in ui_qa


def test_admin_feedback_shows_author_nickname_contract():
    feedback_api = (ROOT / "api" / "routers" / "feedback.py").read_text(encoding="utf-8")
    admin_page = (ROOT / "frontend" / "admin.html").read_text(encoding="utf-8")
    qa_api = (ROOT / "scripts" / "qa_runner.py").read_text(encoding="utf-8")
    qa_ui = (ROOT / "scripts" / "qa_ui_crawler.py").read_text(encoding="utf-8")

    assert "ALTER TABLE feedback ADD COLUMN IF NOT EXISTS customer_id" in feedback_api
    assert "ALTER TABLE feedback ADD COLUMN IF NOT EXISTS username" in feedback_api
    assert "decode_token" in feedback_api
    assert "LEFT JOIN customers c" in feedback_api
    assert "author_nickname" in feedback_api
    assert "author_display" in feedback_api
    assert "renderFeedbackAuthor" in admin_page
    assert "<th>작성자</th>" in admin_page
    assert "author_nickname" in admin_page
    assert "author_display" in admin_page
    assert "/api/feedback" in qa_api
    assert "author_display" in qa_api
    assert "[data-tab='feedback']" in qa_ui
    assert "#f-body" in qa_ui


def test_admin_lists_support_page_size_and_page_view_filter():
    admin_api = (ROOT / "api" / "routers" / "admin.py").read_text(encoding="utf-8")
    feedback_api = (ROOT / "api" / "routers" / "feedback.py").read_text(encoding="utf-8")
    admin_page = (ROOT / "frontend" / "admin.html").read_text(encoding="utf-8")
    qa_api = (ROOT / "scripts" / "qa_runner.py").read_text(encoding="utf-8")
    qa_ui = (ROOT / "scripts" / "qa_ui_crawler.py").read_text(encoding="utf-8")

    assert "_normalize_page_size" in admin_api
    assert "_normalize_page_size" in feedback_api
    assert '"total": total' in admin_api
    assert "event_type = %s" in admin_api
    assert 'id="u-page-size"' in admin_page
    assert 'id="l-page-size"' in admin_page
    assert 'id="q-page-size"' in admin_page
    assert 'id="f-page-size"' in admin_page
    assert 'data-type="page_view"' in admin_page
    assert "페이지 조회" in admin_page
    assert "listState" in admin_page
    assert "updatePager" in admin_page
    assert "renderPageNumbers" in admin_page
    assert "pager-action" in admin_page
    assert 'id="u-page-numbers"' in admin_page
    assert 'id="l-page-numbers"' in admin_page
    assert 'id="q-page-numbers"' in admin_page
    assert 'id="f-page-numbers"' in admin_page
    assert 'data-target="first"' in admin_page
    assert 'data-target="last"' in admin_page
    assert "page_size" in admin_page
    assert "page_size=100" in qa_api
    assert "page=2&page_size=20" in qa_api
    assert "event_type=page_view" in qa_api
    assert "#u-page-size" in qa_ui
    assert "#l-page-size" in qa_ui
    assert "#q-page-size" in qa_ui
    assert "#f-page-size" in qa_ui
    assert "#u-page-numbers" in qa_ui
    assert "#l-page-numbers" in qa_ui
    assert "#q-page-numbers" in qa_ui
    assert "#f-page-numbers" in qa_ui
    admin_expectation = qa_ui.split('"/admin": {', 1)[1].split("    },", 1)[0]
    assert '"texts": ["SUPER ADMIN", "코치 운영", "훈련 운영", "QA 검증 로그", "피드백"]' in admin_expectation
    assert "7일 준비도 체크인" not in admin_expectation
    assert "페이지 조회" not in admin_expectation


def test_admin_regular_and_qa_operation_logs_are_separated():
    admin_api = (ROOT / "api" / "routers" / "admin.py").read_text(encoding="utf-8")
    admin_page = (ROOT / "frontend" / "admin.html").read_text(encoding="utf-8")
    qa_api = (ROOT / "scripts" / "qa_runner.py").read_text(encoding="utf-8")
    qa_ui = (ROOT / "scripts" / "qa_ui_crawler.py").read_text(encoding="utf-8")
    qa_audit = (ROOT / "scripts" / "qa_account_audit.py").read_text(encoding="utf-8")
    qa_workflow = (ROOT / ".github" / "workflows" / "qa-account-classification.yml").read_text(encoding="utf-8")

    assert 'account_scope: str = "regular"' in admin_api
    assert 'value in ("regular", "qa", "all")' in admin_api
    assert "qa.id = {alias}.customer_id" in admin_api
    assert "LOWER(qa.username) = LOWER({alias}.username)" in admin_api
    assert "metadata ->> 'qa_automation'" in admin_api
    assert "qa_anchor.ip_address = {alias}.ip_address" in admin_api
    assert "qa_anchor.user_agent = {alias}.user_agent" in admin_api
    assert "INTERVAL '15 minutes'" in admin_api
    assert 'request.headers.get(QA_AUTOMATION_HEADER' in admin_api
    assert 'swimmate_qa_run: str = Cookie(default=None)' in admin_api
    assert "_qa_candidate_evidence" in admin_api
    assert 'account_scope: str = "all"' in admin_api
    assert '@router.put("/qa-accounts")' in admin_api
    assert "is_qa_account" in admin_api
    assert 'data-tab="qa-logs"' in admin_page
    assert 'id="tab-qa-logs"' in admin_page
    assert "일반 사용자 운영 로그" in admin_page
    assert "QA 자동 검증 전용 운영 로그" in admin_page
    assert "account_scope: 'regular'" in admin_page
    assert "account_scope: 'qa'" in admin_page
    assert "loadQALogs" in admin_page
    assert 'id="u-account-scope"' in admin_page
    assert 'value="candidate"' in admin_page
    assert "setQAAccount" in admin_page
    assert "qa_evidence" in admin_page
    assert "/api/admin/qa-accounts" in qa_api
    assert "qa_log_split_ok" in qa_api
    assert '"qaLogs", "qa-logs", "q", "path", "/api/admin/logs", "qa"' in qa_ui
    assert '"name": "swimmate_qa_run"' in qa_ui
    assert "context.add_cookies" in qa_ui
    assert "classification_policy" in qa_audit
    assert "candidate_accounts" in qa_audit
    assert "QA Account Classification" in qa_workflow

    import sys
    sys.path.insert(0, str(ROOT / "api"))
    from routers.admin import _log_scope_filter, _normalize_account_scope, _qa_candidate_evidence

    assert _normalize_account_scope("unknown") == "regular"
    assert _log_scope_filter("all") == ""
    assert _log_scope_filter("qa").startswith("(")
    assert _log_scope_filter("regular").startswith("NOT (")
    evidence = _qa_candidate_evidence({
        "username": "qa_test_01", "email": "qa_test_01@example.com",
        "name": "테스트", "nickname": "", "activity_count": 30,
        "training_log_count": 0, "is_qa_account": False,
    })
    assert evidence["is_candidate"] is True
    assert evidence["confidence"] == "high"
    assert evidence["score"] >= 75


def test_admin_category_search_and_traffic_charts_are_fully_mapped():
    admin_api = (ROOT / "api" / "routers" / "admin.py").read_text(encoding="utf-8")
    feedback_api = (ROOT / "api" / "routers" / "feedback.py").read_text(encoding="utf-8")
    admin_page = (ROOT / "frontend" / "admin.html").read_text(encoding="utf-8")
    qa_api = (ROOT / "scripts" / "qa_runner.py").read_text(encoding="utf-8")
    qa_ui = (ROOT / "scripts" / "qa_ui_crawler.py").read_text(encoding="utf-8")
    postman = (ROOT / "tests" / "postman" / "SwimMate.postman_collection.json").read_text(encoding="utf-8")

    assert "def _build_search_filter" in admin_api
    assert 'category = search_by if search_by in field_map else "all"' in admin_api
    assert 'search_by: str = "all"' in admin_api
    assert 'search_by: str = "all"' in feedback_api
    assert '"traffic_summary"' in admin_api
    assert '"traffic_trend"' in admin_api
    assert "generate_series" in admin_api
    assert "customer:" in admin_api and "ip:" in admin_api

    for selector in [
        "d-chart-days", "d-page-views", "d-visitors", "d-active-users",
        "d-traffic-chart", "d-provider-chart", "u-search-by", "u-search",
        "c-search-by", "c-search", "l-search-by", "l-search",
        "f-search-by", "f-search",
    ]:
        assert f'id="{selector}"' in admin_page
    assert "renderDashboardCharts" in admin_page
    assert "new Chart" in admin_page
    assert "list-search-btn" in admin_page and "list-search-reset" in admin_page
    assert "search_by: listState.users.searchBy" in admin_page
    assert "search_by:listState.coaches.searchBy" in admin_page
    assert "search_by: listState.logs.searchBy" in admin_page
    assert "search_by: listState.feedback.searchBy" in admin_page

    assert "admin_search_ok" in qa_api and "admin_chart_ok" in qa_api
    assert "check_admin_search_and_charts" in qa_ui
    assert "admin_category_search_contract" in qa_ui
    assert "admin_chart_render_failed" in qa_ui
    assert "search_by=username" in postman
    assert "30일 방문·가입 그래프 데이터" in postman

    import sys
    sys.path.insert(0, str(ROOT / "api"))
    from routers.admin import _build_search_filter

    field_map = {"all": ("username", "email"), "username": ("username",)}
    clause, params, category, term = _build_search_filter(
        "qa-user", "username; DROP TABLE customers", field_map
    )
    assert category == "all"
    assert "DROP TABLE" not in clause
    assert clause == "(username ILIKE %s OR email ILIKE %s)"
    assert params == ["%qa-user%", "%qa-user%"]
    assert term == "qa-user"


def test_badge_progression_content_is_kept():
    badge_api = (ROOT / "api" / "routers" / "badge.py").read_text(encoding="utf-8")
    badge_page = (ROOT / "frontend" / "badge.html").read_text(encoding="utf-8")
    qa_api = (ROOT / "scripts" / "qa_runner.py").read_text(encoding="utf-8")
    qa_ui = (ROOT / "scripts" / "qa_ui_crawler.py").read_text(encoding="utf-8")
    checklist = (ROOT / "FEATURE_CHECKLIST.md").read_text(encoding="utf-8")

    assert "BADGE_SERIES" in badge_api
    assert "log_count_100" in badge_api
    assert "log_dist_500km" in badge_api
    assert "plan_runner_12" in badge_api
    assert "monthly_goal_achiever" in badge_api
    assert "pool_dual" in badge_api
    assert "series_groups" in badge_api
    assert "next_badges" in badge_api
    assert "다음으로 노릴 뱃지" in badge_page
    assert "단계별 뱃지 여정" in badge_page
    assert "badge-stage-card" in badge_page
    assert "/api/badges" in qa_api
    assert "단계형 뱃지 API" in qa_api
    assert "#series-grid" in qa_ui
    assert "단계형 뱃지 콘텐츠 확장" in checklist


def test_swimtech_branding_is_training_helper_focused():
    login = (ROOT / "frontend" / "login.html").read_text(encoding="utf-8")
    register = (ROOT / "frontend" / "register.html").read_text(encoding="utf-8")
    landing = (ROOT / "frontend" / "landing.html").read_text(encoding="utf-8")
    dashboard = (ROOT / "frontend" / "dashboard.html").read_text(encoding="utf-8")
    logo = (ROOT / "frontend" / "static" / "icons" / "logo.svg").read_text(encoding="utf-8")
    style = (ROOT / "frontend" / "style.css").read_text(encoding="utf-8")
    api_main = (ROOT / "api" / "main.py").read_text(encoding="utf-8")

    visible_brand_sources = login + register + landing + dashboard + logo + api_main
    assert "SwimMate" in visible_brand_sources
    assert "SwimTech" not in visible_brand_sources
    assert "나만의 수영 훈련 도우미" in login
    assert "수영 훈련을 함께 설계해볼까요?" in register
    assert "수영 훈련 도우미" in logo
    assert "수영 훈련 도우미 플랫폼 백엔드" in api_main
    assert "수영 영법 분석 플랫폼" not in login + logo + api_main
    assert ".logo-img { height: 42px" in style
    assert ".logo { font-size: clamp(22px" in style


def test_frontend_visible_branding_uses_swimmate():
    checked = []
    for path in (ROOT / "frontend").rglob("*"):
        if path.suffix.lower() not in {".html", ".svg"}:
            continue
        text = path.read_text(encoding="utf-8-sig")
        checked.append(path.name)
        assert "SwimTech" not in text, f"old visible brand remains in {path}"
    assert "SwimMate" in (ROOT / "frontend" / "landing.html").read_text(encoding="utf-8")
    assert "SwimMate" in (ROOT / "frontend" / "static" / "icons" / "logo.svg").read_text(encoding="utf-8")
    manifest = (ROOT / "frontend" / "manifest.json").read_text(encoding="utf-8")
    assert '"name": "SwimMate' in manifest
    assert '"short_name": "SwimMate"' in manifest
    assert "SwimTech" not in manifest
    assert "영상을 업로드" not in manifest
    assert checked


def test_quality_gate_documentation_is_kept_current():
    quality_doc = (ROOT / "docs" / "QUALITY_GATE.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    checklist = (ROOT / "FEATURE_CHECKLIST.md").read_text(encoding="utf-8")
    claude = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    pytest_ini = (ROOT / "tests" / "pytest.ini").read_text(encoding="utf-8")
    privacy = (ROOT / "frontend" / "privacy.html").read_text(encoding="utf-8")
    terms = (ROOT / "frontend" / "terms.html").read_text(encoding="utf-8")

    assert "SwimMate 품질 검증 게이트" in quality_doc
    assert "단위·계약·지식 검색·Jira 통합·Postman 자산 계약 122개" in quality_doc
    assert "53개 API 시나리오" in quality_doc
    assert "30076991403" in quality_doc
    assert "역할별 35개 화면" in quality_doc
    assert "내 수영 데이터 대시보드" in quality_doc
    assert "목적별 사용 가이드" in quality_doc
    assert "DB 스키마 변경" in quality_doc
    assert "PostgreSQL · Neon · Alembic" in readme
    assert "Playwright E2E 정의 108개" in quality_doc
    assert "유일한 필수 품질 게이트" in quality_doc
    assert "QA_STUDENT_USERNAME" in quality_doc
    for required in [
        "풀사이드 훈련 실행",
        "준비도·주간 어드바이저",
        "헬스 데이터 가져오기",
        "코치 AI 강습 운영",
        "클럽·반·범위별 역할",
        "Jira 운영판",
        "슈퍼 관리자",
        "공개 메타데이터·정책",
        "릴리즈·문서",
        "영상 분석 재활성화",
        "실행 가능한 Postman API 문서",
    ]:
        assert required in quality_doc
    assert "[품질 검증 게이트](./docs/QUALITY_GATE.md)" in readme
    assert "[기능 지도](./docs/FEATURE_MAP.md)" in readme
    assert "[기술 구조](./docs/ARCHITECTURE.md)" in readme
    assert "[배포 가이드](./docs/DEPLOYMENT.md)" in readme
    assert "docs/QUALITY_GATE.md" in checklist
    assert "품질 검증 게이트 문서화" in checklist
    assert "docs/QUALITY_GATE.md" in claude
    assert "section25:" in pytest_ini
    assert "현재 신규 가져오기 UI는 비활성화" in privacy
    assert "Google Gemini" in privacy and "Atlassian Jira" in privacy
    assert "개인화 질문 시 훈련 설정" in privacy
    assert "이름·이메일·자유 입력 메모" in privacy
    assert "AI 코치 지식·개인화" in quality_doc
    assert "swimtech_token" in privacy and "swimtech_refresh_token" in privacy
    assert "영상 업로드 기반 영법 분석" in terms
    assert "현재 공개 서비스에서 제공하지 않습니다" in terms
    assert "건강 앱 내보내기 파일 가져오기는 현재 비활성 상태" in terms
    assert "월간 결과 카드 스냅샷·공개 토큰" in privacy
    assert "생성일부터 180일" in privacy
    assert "거리 합산은 회원별 기본 미동의" in privacy
    assert "공개 링크를 다른 서비스에 게시하면" in terms
    assert "style=\"display:none\"" not in terms


def test_ai_workout_screenshot_import_requires_review_and_keeps_original_image_ephemeral():
    page = (ROOT / "frontend" / "training_log.html").read_text(encoding="utf-8")
    api = (ROOT / "api" / "routers" / "workout_screenshot.py").read_text(encoding="utf-8")
    report = (ROOT / "api" / "routers" / "report.py").read_text(encoding="utf-8")
    admin_api = (ROOT / "api" / "routers" / "admin.py").read_text(encoding="utf-8")
    admin_page = (ROOT / "frontend" / "admin.html").read_text(encoding="utf-8")
    faq_page = (ROOT / "frontend" / "faq.html").read_text(encoding="utf-8")
    videos_page = (ROOT / "frontend" / "videos.html").read_text(encoding="utf-8")
    main = (ROOT / "api" / "main.py").read_text(encoding="utf-8")
    crawler = (ROOT / "scripts" / "qa_ui_crawler.py").read_text(encoding="utf-8")
    qa_api = (ROOT / "scripts" / "qa_runner.py").read_text(encoding="utf-8")

    assert 'id="btn-open-screenshot"' in page
    assert 'id="screenshot-modal-backdrop"' in page
    assert 'id="screenshot-file-input"' in page and " multiple>" in page
    assert "MAX_SCREENSHOT_BATCH = 5" in page
    assert 'id="screenshot-batch-list"' in page
    assert "for (let order = 0; order < targets.length; order += 1)" in page
    assert "원본 이미지를 저장하지 않으며" in page
    assert "저장 후 다음 운동 확인" in page
    assert 'class="report-toast-message"' in page
    assert "word-break: keep-all" in page
    assert "def check_responsive_layout" in crawler
    assert "check_responsive_layout(page, path)" in crawler
    for viewport_label in ("ultrawide-2560", "wide-1440", "desktop-1280", "laptop-1024", "tablet-768", "mobile-390"):
        assert viewport_label in crawler
    assert "compactWrap" in crawler
    assert "reportLayout" in crawler
    assert "wrappedValues" in crawler
    assert "overlaps" in crawler
    assert "insideHorizontalScroller" in crawler
    assert "element.closest('#map')" in crawler
    assert "grid-template-columns: minmax(0,1fr)" in faq_page
    assert "grid-template-columns: minmax(0,1fr)" in videos_page
    assert "실제로 한 운동이 맞나요" in page
    assert "확인하고 일지에 저장" in page
    assert "원본 이미지를 저장하지" in page
    assert "/api/training-log/screenshot/preview" in page
    assert "/api/training-log/screenshot/confirm" in page
    assert '@router.post("/preview")' in api
    assert '@router.post("/confirm")' in api
    assert "del data" in api
    assert '"original_image_stored": False' in api
    assert "_replace_training_sets" in api
    assert "ON CONFLICT (customer_id, provider, external_id) DO NOTHING" in api
    assert "workout_screenshot.router" in main
    assert "structured_strokes" in report
    assert "#btn-open-screenshot" in crawler
    assert '"screenshot_imports_30d"' in admin_api
    assert 'id="h-screenshot-imports"' in admin_page
    assert "screenshot_imports_30d" in qa_api
    assert "#h-screenshot-imports" in crawler


def test_promotion_result_cards_and_club_campaigns_are_privacy_scoped_and_qa_mapped():
    api = (ROOT / "api" / "routers" / "promotion.py").read_text(encoding="utf-8")
    main = (ROOT / "api" / "main.py").read_text(encoding="utf-8")
    report = (ROOT / "frontend" / "report.html").read_text(encoding="utf-8")
    result_page = (ROOT / "frontend" / "result_card.html").read_text(encoding="utf-8")
    clubs = (ROOT / "frontend" / "clubs.html").read_text(encoding="utf-8")
    club_public = (ROOT / "frontend" / "club_public.html").read_text(encoding="utf-8")
    admin_api = (ROOT / "api" / "routers" / "admin.py").read_text(encoding="utf-8")
    admin_page = (ROOT / "frontend" / "admin.html").read_text(encoding="utf-8")
    qa_api = (ROOT / "scripts" / "qa_runner.py").read_text(encoding="utf-8")
    qa_ui = (ROOT / "scripts" / "qa_ui_crawler.py").read_text(encoding="utf-8")
    vercel = (ROOT / "frontend" / "vercel.json").read_text(encoding="utf-8")

    assert "include_router(promotion.router" in main
    assert '@router.post("/result-shares/monthly")' in api
    assert '@router.get("/public/results/{token}")' in api
    assert '@router.delete("/result-shares/{token}")' in api
    assert '"location"' not in api.split("def _result_snapshot", 1)[1].split("@router.post", 1)[0]
    assert "show_nickname: bool = False" in api
    assert "promotion_result_shares" in api and "club_promotion_campaigns" in api
    assert '@router.put("/clubs/{club_id}/campaign")' in api
    assert '@router.get("/public/clubs/{token}")' in api
    assert '@router.get("/public/clubs/{token}/qr.svg")' in api
    assert '@router.put("/clubs/{club_id}/campaign/consent")' in api
    assert "promotion_distance_opt_in IS TRUE" in api
    assert '_club_role(cur, club_id, customer_id, {"owner", "coach"})' in api
    assert 'id="result-share-panel"' in report
    assert 'id="share-nickname"' in report
    assert "/api/promotion/result-shares/monthly" in report
    assert "navigator.canShare" in result_page and "share-canvas" in result_page
    assert "위치 · 심박 · 메모" in result_page
    assert "renderPromotionPanel" in clubs
    assert "renderPromotionConsent" in clubs
    assert "/api/promotion/clubs/${clubId}/campaign" in clubs
    assert "직접 동의한 회원의 거리만 익명 합산" in api
    assert "login?next=" in club_public
    assert '"source": "/result/:token"' in vercel
    assert '"source": "/club/:token"' in vercel
    for key in ("result_shares_30d", "result_share_views_30d", "public_club_campaigns", "club_campaign_views"):
        assert f'"{key}"' in admin_api
        assert key in qa_api
    for selector in ("h-result-shares", "h-result-share-views", "h-public-campaigns", "h-campaign-views"):
        assert f'id="{selector}"' in admin_page
        assert f"#{selector}" in qa_ui
    assert 'rec("17b"' in qa_api and 'rec("18j"' in qa_api
    assert "def check_public_promotion_pages" in qa_ui
    assert "def json_fixture(payload)" in qa_ui
    assert "def fulfill(route, _request=None)" in qa_ui
    assert "lambda route, body=json.dumps" not in qa_ui
    assert 'service_workers="block"' in qa_ui
    assert "makeCanvas().toDataURL('image/png')" in qa_ui
    assert '"/result/qa-ui-contract"' in qa_ui and '"/club/qa-ui-contract"' in qa_ui
    assert '@limiter.limit("60/minute")' in api
