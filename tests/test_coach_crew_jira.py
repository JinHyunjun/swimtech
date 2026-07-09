from datetime import date, datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_crew_signal_prioritizes_recovery_and_training_gaps():
    from routers.coach import _crew_member_signal

    recovery = _crew_member_signal(
        last_training_date=date.today(), readiness_score=42, hard_sessions_14d=0
    )
    gap = _crew_member_signal(
        last_training_date=date.today() - timedelta(days=12),
        readiness_score=80,
        hard_sessions_14d=0,
    )
    steady = _crew_member_signal(
        last_training_date=date.today() - timedelta(days=2),
        readiness_score=80,
        hard_sessions_14d=0,
    )

    assert recovery == {"level": "attention", "label": "회복 확인"}
    assert gap == {"level": "watch", "label": "10일 이상 공백"}
    assert steady == {"level": "steady", "label": "안정적"}


def test_coach_router_exposes_crew_dashboard_and_local_first_action_items():
    source = (ROOT / "api" / "routers" / "coach.py").read_text(encoding="utf-8")

    assert '@router.get("/crew-dashboard")' in source
    assert '@router.post("/action-items", status_code=201)' in source
    assert "CREATE TABLE IF NOT EXISTS coach_action_items" in source
    assert source.index("INSERT INTO coach_action_items") < source.index("JiraClient().create_issue")
    assert "cs.status = 'active'" in source


def test_jira_analytics_groups_categories_statuses_and_weekly_flow():
    from routers.coach import _JIRA_ANALYTICS_TTL_SECONDS, _build_jira_analytics

    now = datetime.now(timezone.utc)
    old = now - timedelta(days=9)
    issues = [
        {
            "key": "KAN-10",
            "fields": {
                "summary": "호흡 교정 확인",
                "labels": ["swimmate", "technique"],
                "created": old.strftime("%Y-%m-%dT%H:%M:%S.000+0000"),
                "updated": old.strftime("%Y-%m-%dT%H:%M:%S.000+0000"),
                "resolutiondate": None,
                "status": {"name": "해야 할 일", "statusCategory": {"key": "new"}},
            },
        },
        {
            "key": "KAN-11",
            "fields": {
                "summary": "회복 확인 완료",
                "labels": ["swimmate", "recovery"],
                "created": old.strftime("%Y-%m-%dT%H:%M:%S.000+0000"),
                "updated": now.strftime("%Y-%m-%dT%H:%M:%S.000+0000"),
                "resolutiondate": now.strftime("%Y-%m-%dT%H:%M:%S.000+0000"),
                "status": {"name": "완료", "statusCategory": {"key": "done"}},
            },
        },
    ]

    analytics = _build_jira_analytics(issues, "KAN", "https://example.atlassian.net")
    category_counts = {item["key"]: item["count"] for item in analytics["category_counts"]}

    assert analytics["available"] is True
    assert analytics["open_count"] == 1
    assert analytics["done_count"] == 1
    assert analytics["done_this_week"] == 1
    assert category_counts["technique"] == 1
    assert category_counts["recovery"] == 1
    assert analytics["stale_items"][0]["key"] == "KAN-10"
    assert sum(item["created"] for item in analytics["weekly_flow"]) >= 1
    assert analytics["cache"]["ttl_seconds"] == 60
    assert _JIRA_ANALYTICS_TTL_SECONDS == 60


def test_coach_page_connects_dashboard_and_jira_action_modal():
    page = (ROOT / "frontend" / "coach.html").read_text(encoding="utf-8")

    assert 'id="crew-operations-card"' in page
    assert 'id="crew-jira-analytics"' in page
    assert "jira-category-chart" in page
    assert "jira-weekly-chart" in page
    assert 'id="modal-action-item"' in page
    assert "/api/coach/crew-dashboard" in page
    assert "/api/coach/action-items" in page
    assert "/api/jira/status" in page
    assert "openActionItemFromButton" in page
    assert "submitActionItem" in page
    assert "renderCrewAnalytics" in page
