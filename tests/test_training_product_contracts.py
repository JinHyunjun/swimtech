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
    for config_path in (ROOT / "vercel.json", ROOT / "frontend" / "vercel.json"):
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
