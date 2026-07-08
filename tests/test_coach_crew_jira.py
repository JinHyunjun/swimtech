from datetime import date, timedelta
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


def test_coach_page_connects_dashboard_and_jira_action_modal():
    page = (ROOT / "frontend" / "coach.html").read_text(encoding="utf-8")

    assert 'id="crew-operations-card"' in page
    assert 'id="modal-action-item"' in page
    assert "/api/coach/crew-dashboard" in page
    assert "/api/coach/action-items" in page
    assert "/api/jira/status" in page
    assert "openActionItemFromButton" in page
    assert "submitActionItem" in page

