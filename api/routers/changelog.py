# -*- coding: utf-8 -*-
# NOTE: .env 파일에 NOTION_TOKEN=secret_xxx 를 추가해야 합니다.
#       Notion 통합(Integration) 토큰을 생성하고, 해당 페이지에 통합을 연결하세요.
import os
import re
import time
import httpx
from fastapi import APIRouter, HTTPException
from typing import Any

router = APIRouter()

_NOTION_PAGE_ID = "36bcb889-5490-81f3-b3c4-dff4dbba018f"
_API_VER = "2022-06-28"
_CACHE_TTL = 300  # 5분

_cache: dict[str, Any] = {"data": None, "ts": 0.0}

_DATE_RE = re.compile(r"\d{4}[-./]\d{1,2}[-./]\d{1,2}")


def _auth_headers() -> dict:
    token = os.getenv("NOTION_TOKEN", "")
    if not token:
        raise HTTPException(503, "NOTION_TOKEN 환경변수가 설정되지 않았습니다. .env 파일을 확인하세요.")
    return {"Authorization": f"Bearer {token}", "Notion-Version": _API_VER}


def _rich_text(items: list) -> str:
    return "".join(item.get("plain_text", "") for item in items)


def _fetch_blocks(block_id: str) -> list:
    url = f"https://api.notion.com/v1/blocks/{block_id}/children"
    blocks, cursor = [], None
    with httpx.Client(timeout=15) as client:
        while True:
            params = {"start_cursor": cursor} if cursor else {}
            r = client.get(url, headers=_auth_headers(), params=params)
            if r.status_code != 200:
                raise HTTPException(502, f"Notion API 오류: {r.status_code}")
            body = r.json()
            blocks.extend(body.get("results", []))
            if not body.get("has_more"):
                break
            cursor = body.get("next_cursor")
    return blocks


def _parse_versions(blocks: list) -> list:
    versions: list[dict] = []
    cur: dict | None = None
    cur_section: str | None = None

    for b in blocks:
        t = b.get("type", "")

        # heading_1/2만 새 버전 시작, heading_3은 서브섹션 레이블
        if t in ("heading_1", "heading_2"):
            text = _rich_text(b[t]["rich_text"]).strip()
            if not text:
                continue
            cur = {"version": text, "date": None, "changes": []}
            cur_section = None
            versions.append(cur)

        elif t == "heading_3":
            if cur is not None:
                cur_section = _rich_text(b["heading_3"]["rich_text"]).strip() or None

        elif t == "paragraph" and cur is not None:
            text = _rich_text(b["paragraph"]["rich_text"]).strip()
            if not text:
                continue
            if cur["date"] is None and _DATE_RE.search(text) and len(text) < 40:
                cur["date"] = text
            else:
                cur["changes"].append({"type": "text", "text": text, "section": cur_section})

        elif t == "bulleted_list_item" and cur is not None:
            text = _rich_text(b["bulleted_list_item"]["rich_text"]).strip()
            if text:
                cur["changes"].append({"type": "bullet", "text": text, "section": cur_section})

        elif t == "numbered_list_item" and cur is not None:
            text = _rich_text(b["numbered_list_item"]["rich_text"]).strip()
            if text:
                cur["changes"].append({"type": "numbered", "text": text, "section": cur_section})

        elif t == "callout" and cur is not None:
            text = _rich_text(b["callout"]["rich_text"]).strip()
            if text:
                cur["changes"].append({"type": "callout", "text": text, "section": cur_section})

        elif t == "toggle" and cur is not None:
            text = _rich_text(b["toggle"]["rich_text"]).strip()
            if text:
                cur["changes"].append({"type": "toggle", "text": text, "section": cur_section})

        elif t == "code" and cur is not None:
            text = _rich_text(b["code"]["rich_text"]).strip()
            if text and cur["date"] is None and _DATE_RE.search(text) and len(text) < 40:
                cur["date"] = text

        elif t == "divider":
            cur_section = None

    return versions


@router.get("")
def get_changelog():
    now = time.time()
    if _cache["data"] is not None and now - _cache["ts"] < _CACHE_TTL:
        return _cache["data"]

    blocks = _fetch_blocks(_NOTION_PAGE_ID)
    versions = _parse_versions(blocks)
    result = {"versions": versions, "total": len(versions), "cached_at": int(now)}
    _cache["data"] = result
    _cache["ts"] = now
    return result
