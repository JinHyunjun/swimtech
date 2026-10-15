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
    assert '@router.post("/action-items/{action_item_id}/complete")' in source
    assert "CREATE TABLE IF NOT EXISTS coach_action_items" in source
    assert "'local_only') RETURNING id" in source
    assert "JiraClient().create_issue" not in source
    assert "transition_issue_to_done" not in source
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
    assert 'id="crew-jira-analytics"' not in page
    assert 'id="jira-shortcuts"' not in page
    assert "coach-quick-nav" in page
    assert "coach-panel" in page
    assert "openCoachPanel" in page
    assert 'id="modal-action-item"' in page
    assert "/api/coach/crew-dashboard" in page
    assert "/api/coach/action-items" in page
    assert "/api/coach/action-items/${actionItemId}/complete" in page
    assert "/api/jira/status" not in page
    assert "openActionItemFromButton" in page
    assert "submitActionItem" in page
    assert "completeActionItem" in page
    assert "Jira 완료" not in page
    assert "SwimMate 내부 관리" in page


def test_landing_pwa_banner_stays_hidden_until_install_prompt():
    page = (ROOT / "frontend" / "landing.html").read_text(encoding="utf-8")

    banner_start = page.index('id="pwa-banner"')
    banner_opening_tag = page[banner_start:page.index(">", banner_start)]
    assert "display:none" in banner_opening_tag
    assert "display:flex" not in banner_opening_tag
    assert "beforeinstallprompt" in page

"""Local coaching task regressions; no real DB or external Jira requests."""
from unittest.mock import Mock

import pytest
from fastapi import HTTPException
from routers import coach


@pytest.fixture
def local_db(monkeypatch):
    conn=Mock();cur=conn.cursor.return_value
    monkeypatch.setattr(coach,'_ensure_tables',lambda:None)
    monkeypatch.setattr(coach,'_require_user',lambda request:'coach')
    monkeypatch.setattr(coach,'_get_db',lambda:conn)
    monkeypatch.setattr(coach,'_get_customer_id',lambda *args:11)
    monkeypatch.setattr(coach,'_require_coach',lambda *args:22)
    monkeypatch.setattr(coach,'JiraClient',Mock(side_effect=AssertionError('External Jira must not be called')))
    return conn,cur


def test_create_is_local_even_with_broken_jira(local_db):
    conn,cur=local_db
    cur.fetchone.side_effect=[('Student',),(42,)]
    body=coach.CoachActionItemRequest(student_id=3,category='technique',title='호흡 확인',description='기존 설명')
    result=coach.create_coach_action_item(body,None)
    assert result==dict(id=42,status='open',sync_status='local_only')
    assert conn.commit.call_count==1


@pytest.mark.parametrize('legacy_key',[None,'KAN-42'])
def test_complete_preserves_legacy_references_and_sync_history(local_db,legacy_key):
    conn,cur=local_db
    cur.fetchone.side_effect=[(42,'open',legacy_key,'old-url'),(42,legacy_key,'old-url')]
    result=coach.complete_coach_action_item(42,None)
    assert result['status']=='done' and result['local_only']
    assert result['jira_issue_key']==legacy_key
    update=[c for c in cur.execute.call_args_list if 'UPDATE coach_action_items' in c.args[0]][0]
    assert update.args[1]==(42,22)
    sql=update.args[0].split('RETURNING')[0]
    assert 'sync_status =' not in sql and 'jira_issue_key =' not in sql
    assert conn.commit.call_count==1


def test_other_coach_cannot_complete_missing_task(local_db):
    conn,cur=local_db;cur.fetchone.return_value=None
    with pytest.raises(HTTPException) as error:
        coach.complete_coach_action_item(42,None)
    assert error.value.status_code==404
    conn.commit.assert_not_called()


def test_completed_task_is_idempotent(local_db):
    conn,cur=local_db;cur.fetchone.return_value=(42,'done','KAN-42','old-url')
    result=coach.complete_coach_action_item(42,None)
    assert result['already_done']
    assert not any('UPDATE' in c.args[0] for c in cur.execute.call_args_list)
