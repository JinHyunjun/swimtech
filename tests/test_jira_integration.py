import json

import httpx
import pytest

from integrations.jira_client import JiraApiError, JiraClient, JiraSettings


SETTINGS = JiraSettings(
    base_url="https://example.atlassian.net",
    email="coach@example.com",
    api_token="secret-token",
    project_key="KAN",
)


def test_connection_status_returns_safe_project_details():
    def handler(request: httpx.Request):
        if request.url.path.endswith("/myself"):
            return httpx.Response(200, json={"displayName": "Coach"})
        return httpx.Response(200, json={"key": "KAN", "name": "Crew Coach"})

    client = JiraClient(SETTINGS, transport=httpx.MockTransport(handler))
    assert client.connection_status() == {
        "connected": True,
        "account_name": "Coach",
        "project_key": "KAN",
        "project_name": "Crew Coach",
    }


def test_create_issue_uses_project_task_type_and_adf_description():
    captured = {}

    def handler(request: httpx.Request):
        if request.method == "GET":
            return httpx.Response(
                200,
                json={"issueTypes": [{"id": "10003", "name": "작업", "subtask": False}]},
            )
        captured.update(json.loads(request.content))
        return httpx.Response(201, json={"id": "10100", "key": "KAN-1"})

    client = JiraClient(SETTINGS, transport=httpx.MockTransport(handler))
    result = client.create_issue(
        summary="자유형 호흡 교정",
        description="회원의 호흡 타이밍을 확인합니다.",
        labels=["technique"],
    )

    fields = captured["fields"]
    assert fields["project"] == {"key": "KAN"}
    assert fields["issuetype"] == {"id": "10003"}
    assert fields["description"]["type"] == "doc"
    assert result["key"] == "KAN-1"
    assert result["url"].endswith("/browse/KAN-1")


def test_search_issues_uses_enhanced_jql_endpoint_with_narrow_fields():
    captured = {}

    def handler(request: httpx.Request):
        captured["path"] = request.url.path
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"issues": [{"key": "KAN-1"}], "isLast": True})

    client = JiraClient(SETTINGS, transport=httpx.MockTransport(handler))
    result = client.search_issues(
        jql="project = KAN AND labels = swimmate ORDER BY created DESC",
        fields=["summary", "status", "labels"],
        max_results=500,
    )

    assert captured["path"] == "/rest/api/3/search/jql"
    assert captured["body"]["fields"] == ["summary", "status", "labels"]
    assert captured["body"]["maxResults"] == 100
    assert result["issues"][0]["key"] == "KAN-1"


def test_api_error_never_exposes_token_or_response_body():
    def handler(_request: httpx.Request):
        return httpx.Response(401, json={"error": "secret-token"})

    client = JiraClient(SETTINGS, transport=httpx.MockTransport(handler))
    with pytest.raises(JiraApiError) as caught:
        client.connection_status()
    assert "secret-token" not in str(caught.value)
