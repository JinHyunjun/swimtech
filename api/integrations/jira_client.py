"""Small Jira Cloud REST client for coach action items.

Credentials are read from environment variables only.  They must never be
returned by an API response or written to logs.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any

import httpx


class JiraConfigurationError(RuntimeError):
    """Raised when the Jira environment variables are incomplete or invalid."""


class JiraApiError(RuntimeError):
    """Raised when Jira rejects or cannot complete a request."""

    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class JiraSettings:
    base_url: str
    email: str
    api_token: str
    project_key: str

    @classmethod
    def from_env(cls) -> "JiraSettings":
        values = {
            "base_url": os.getenv("JIRA_BASE_URL", "").strip().rstrip("/"),
            "email": os.getenv("JIRA_EMAIL", "").strip(),
            "api_token": os.getenv("JIRA_API_TOKEN", "").strip(),
            "project_key": os.getenv("JIRA_PROJECT_KEY", "").strip().upper(),
        }
        missing = [name for name, value in values.items() if not value]
        if missing:
            raise JiraConfigurationError(
                "Jira integration is not configured: " + ", ".join(missing)
            )
        if not values["base_url"].startswith("https://"):
            raise JiraConfigurationError("JIRA_BASE_URL must use HTTPS")
        if "@" not in values["email"]:
            raise JiraConfigurationError("JIRA_EMAIL is invalid")
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", values["project_key"]):
            raise JiraConfigurationError("JIRA_PROJECT_KEY is invalid")
        return cls(**values)


def _adf_text(text: str) -> dict[str, Any]:
    """Convert plain text into Atlassian Document Format."""
    lines = text.splitlines() or [""]
    content = []
    for line in lines:
        paragraph: dict[str, Any] = {"type": "paragraph", "content": []}
        if line:
            paragraph["content"].append({"type": "text", "text": line})
        content.append(paragraph)
    return {"type": "doc", "version": 1, "content": content}


class JiraClient:
    def __init__(
        self,
        settings: JiraSettings | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.settings = settings or JiraSettings.from_env()
        self._transport = transport

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        url = f"{self.settings.base_url}{path}"
        try:
            with httpx.Client(
                auth=(self.settings.email, self.settings.api_token),
                timeout=20.0,
                transport=self._transport,
                headers={"Accept": "application/json"},
            ) as client:
                response = client.request(method, url, **kwargs)
        except httpx.RequestError as exc:
            raise JiraApiError("Jira에 연결할 수 없습니다.") from exc

        if response.is_error:
            if response.status_code in (401, 403):
                message = "Jira 인증 또는 프로젝트 권한을 확인해주세요."
            elif response.status_code == 404:
                message = "Jira 사이트 주소 또는 프로젝트 키를 확인해주세요."
            else:
                message = "Jira 요청을 처리하지 못했습니다."
            raise JiraApiError(message, response.status_code)

        if response.status_code == 204 or not response.content:
            return None
        return response.json()

    def connection_status(self) -> dict[str, Any]:
        account = self._request("GET", "/rest/api/3/myself")
        project = self._request(
            "GET", f"/rest/api/3/project/{self.settings.project_key}"
        )
        return {
            "connected": True,
            "account_name": account.get("displayName"),
            "project_key": project.get("key"),
            "project_name": project.get("name"),
        }

    def _default_issue_type_id(self) -> str:
        data = self._request(
            "GET",
            f"/rest/api/3/issue/createmeta/{self.settings.project_key}/issuetypes",
        )
        issue_types = data.get("issueTypes", [])
        candidates = [item for item in issue_types if not item.get("subtask")]
        for preferred in ("작업", "Task"):
            match = next((item for item in candidates if item.get("name") == preferred), None)
            if match:
                return str(match["id"])
        if candidates:
            return str(candidates[0]["id"])
        raise JiraApiError("Jira 프로젝트에서 생성 가능한 업무 유형을 찾지 못했습니다.", 400)

    def create_issue(
        self,
        *,
        summary: str,
        description: str,
        labels: list[str] | None = None,
    ) -> dict[str, Any]:
        issue_type_id = self._default_issue_type_id()
        fields: dict[str, Any] = {
            "project": {"key": self.settings.project_key},
            "issuetype": {"id": issue_type_id},
            "summary": summary,
            "description": _adf_text(description),
        }
        clean_labels = [label.strip() for label in (labels or []) if label.strip()]
        if clean_labels:
            fields["labels"] = clean_labels
        result = self._request(
            "POST",
            "/rest/api/3/issue",
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            json={"fields": fields},
        )
        key = result["key"]
        return {
            "key": key,
            "id": result.get("id"),
            "url": f"{self.settings.base_url}/browse/{key}",
        }

