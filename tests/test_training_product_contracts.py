"""영상 분석 비활성화와 훈련 중심 제품 흐름을 지키는 정적 계약 테스트."""
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_analysis_routers_are_not_publicly_registered():
    main = (ROOT / "api" / "main.py").read_text(encoding="utf-8")
    assert "include_router(videos.router" not in main
    assert "include_router(analysis.router" not in main
    assert "include_router(stream.router" not in main


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
    assert "훈련 대시보드" in landing
    assert "#icon-dashboard" in landing
    assert 'id="icon-dashboard"' in icons


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
    assert 'data-tab="race"' in plan
    assert "RACE_EVENT_PROFILES" in plan
    assert "generateRacePreparationPlan" in plan
    assert "mobile-add-day" in plan
    assert "moveCardInDay" in plan
    assert "btn-open-import" in log and "validateImportFile" in log
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


def test_qa_scripts_cover_training_report_and_advisor_flows():
    api_qa = (ROOT / "scripts" / "qa_runner.py").read_text(encoding="utf-8")
    ui_qa = (ROOT / "scripts" / "qa_ui_crawler.py").read_text(encoding="utf-8")
    qa_workflow = (ROOT / ".github" / "workflows" / "qa.yml").read_text(encoding="utf-8")
    admin_page = (ROOT / "frontend" / "admin.html").read_text(encoding="utf-8")
    admin_api = (ROOT / "api" / "routers" / "admin.py").read_text(encoding="utf-8")
    checklist = (ROOT / "FEATURE_CHECKLIST.md").read_text(encoding="utf-8")

    assert "/api/training-log/goal" in api_qa
    assert "/api/report/monthly" in api_qa
    assert "/api/dashboard/training-advisor" in api_qa
    assert "/api/admin/training-health" in api_qa
    assert "월간 리포트↔훈련 일지 데이터 연동" in api_qa
    assert "관리자 훈련 운영 API" in api_qa
    assert "plan_completion" in api_qa
    assert "avg_distance" in api_qa
    assert "PAGE_EXPECTATIONS" in ui_qa
    assert ".advisor-card" in ui_qa
    assert "#stat-avg" in ui_qa
    assert "[data-tab='training-health']" in ui_qa
    assert "P3 Training Advisor" in ui_qa
    assert "pip install playwright requests" in qa_workflow
    assert "ADMIN_ID" in qa_workflow and "ADMIN_PW" in qa_workflow
    assert "python scripts/qa_runner.py --no-admin" not in qa_workflow
    assert '@router.get("/training-health")' in admin_api
    assert "훈련 운영" in admin_page
    assert "새 기능 / 새 화면 / 새 API는 반드시" in checklist


def test_plan_p3_improvements_are_kept():
    dashboard_page = (ROOT / "frontend" / "dashboard.html").read_text(encoding="utf-8")
    dashboard_api = (ROOT / "api" / "routers" / "dashboard.py").read_text(encoding="utf-8")
    checklist = (ROOT / "FEATURE_CHECKLIST.md").read_text(encoding="utf-8")

    assert '@router.get("/training-advisor")' in dashboard_api
    assert "_build_training_advisor" in dashboard_api
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
    assert checked
