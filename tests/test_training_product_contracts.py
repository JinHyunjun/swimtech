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
