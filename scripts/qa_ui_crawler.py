#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SwimTech 자동 QA 검증 스크립트 (UI 레벨 — 실제 브라우저 클릭)
─────────────────────────────────────────────────────────
qa_runner.py(API 레벨 체크)와는 별개로, 로그인한 사용자가 보는 모든 메뉴 페이지에
실제로 들어가서 버튼·탭·칩·아코디언·모달 등 클릭 가능한 요소를 전부 눌러보고,
그 과정에서 발생하는 브라우저 콘솔 에러 / 처리되지 않은 예외 / 실패한 API 응답을
"개발자도구" 관점에서 수집해 어떤 동작에서 무엇이 깨졌는지 리포트로 남긴다.

회원 탈퇴·로그아웃 등 되돌릴 수 없는 동작은 클릭하지 않고 건너뛴다(존재 여부만 기록).

사용법:
    pip install playwright
    playwright install --with-deps chromium
    python scripts/qa_ui_crawler.py
    python scripts/qa_ui_crawler.py --base https://swimtech.vercel.app --headed

환경변수 (qa_runner.py와 동일한 고정 QA 계정을 재사용):
    QA_USERNAME (기본 qabot)
    QA_PASSWORD (기본 QaTest1234)

출력:
    qa_ui_report.json           — 페이지별/액션별 상세 결과
    qa_ui_screenshots/*.png     — 에러 발생 시점 + 각 페이지 최초 진입 스크린샷
"""
import os
import re
import sys
import json
import time
import argparse
from pathlib import Path
from datetime import datetime

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass  # Python<3.7 또는 콘솔이 reconfigure를 지원하지 않는 환경

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
except ImportError:
    print("playwright 필요: pip install playwright && playwright install --with-deps chromium")
    sys.exit(1)

BASE = os.getenv("QA_BASE_URL", "https://swimtech.vercel.app")
USERNAME = os.getenv("QA_USERNAME", "qabot")
PASSWORD = os.getenv("QA_PASSWORD", "QaTest1234")

SHOT_DIR = Path("qa_ui_screenshots")
REPORT_PATH = Path("qa_ui_report.json")
MAX_ACTIONS_PER_PAGE = 60
ACTION_TIMEOUT_MS = 5000

# 로그인 후 둘러볼 메뉴 (api/main.py에 등록된 실제 라우트 기준)
PAGES = [
    ("/landing", "랜딩"),
    ("/dashboard", "대시보드"),
    ("/plan", "훈련 플랜"),
    ("/training-log", "훈련 일지"),
    ("/report", "월간 리포트"),
    ("/pool", "수영장 지도"),
    ("/drill", "드릴 가이드"),
    ("/faq", "FAQ"),
    ("/glossary", "용어집"),
    ("/badges", "뱃지"),
    ("/changelog", "변경 이력"),
    ("/community", "커뮤니티"),
    ("/challenge", "챌린지"),
    ("/equipment", "장비"),
    ("/feedback", "피드백"),
    ("/chat", "AI 코치 챗봇"),
    ("/videos", "영상 라이브러리"),
    ("/profile", "프로필"),
    ("/injury", "부상 예방"),
]

# 되돌릴 수 없는 동작 — 클릭하지 않고 "존재 확인"만 한다
DESTRUCTIVE_PATTERN = re.compile(
    r"탈퇴|회원\s*탈퇴|로그아웃|log\s*out|logout|delete\s*account|withdraw|결제|구독\s*취소",
    re.I,
)
DESTRUCTIVE_ID_PATTERN = re.compile(r"deleteBtn|withdraw|logout", re.I)

# 앱 코드와 무관한 서드파티/브라우저 노이즈는 에러로 치지 않음
IGNORE_CONSOLE_PATTERNS = [re.compile(p, re.I) for p in [
    r"ResizeObserver loop",
    r"kakao", r"daumcdn", r"kakaocdn",
    r"Download the React DevTools",
    r"X-Frame-Options",
    r"favicon\.ico",
]]

CLICKABLE_SELECTOR = (
    "button:not([disabled]), [role='button'], .tab-btn, .chip, .pool-filter-btn, "
    "[data-tab], [data-filter], [data-pool-length], [data-cycle-level], [data-type-filter], "
    "summary, .accordion-q, .faq-q, "
    "a[href^='/']"
)

RESULTS = []  # 페이지별 결과 dict 리스트


def slug(text, n=40):
    s = re.sub(r"[^\w가-힣]+", "_", (text or "")[:n]).strip("_")
    return s or "el"


def is_destructive(text, el_id):
    if el_id and DESTRUCTIVE_ID_PATTERN.search(el_id):
        return True
    if text and DESTRUCTIVE_PATTERN.search(text):
        return True
    return False


def is_ignored_console(text):
    return any(p.search(text) for p in IGNORE_CONSOLE_PATTERNS)


def login(page):
    page.goto(f"{BASE}/login", wait_until="domcontentloaded", timeout=30000)
    page.fill("#username", USERNAME)
    page.fill("#password", PASSWORD)
    page.click("#login-btn")
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except PWTimeout:
        pass
    if "/login" in page.url:
        raise RuntimeError(
            f"로그인 실패 — QA_USERNAME/QA_PASSWORD 확인 필요 (계정: {USERNAME})"
        )


def try_close_modal(page):
    """모달이 열려 있으면 닫고 기본 화면으로 복귀시킨다."""
    try:
        close_btn = page.locator(".modal-close:visible, [aria-label='닫기']:visible").first
        if close_btn.count() and close_btn.is_visible():
            close_btn.click(timeout=2000)
            page.wait_for_timeout(200)
            return
    except Exception:
        pass
    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(150)
    except Exception:
        pass


def collect_candidates(page):
    """클릭 후보 요소의 메타데이터(텍스트/id/태그)를 미리 수집한다."""
    try:
        handles = page.locator(CLICKABLE_SELECTOR).all()
    except Exception:
        return []
    candidates = []
    for i, h in enumerate(handles[:MAX_ACTIONS_PER_PAGE]):
        try:
            if not h.is_visible():
                continue
            text = (h.inner_text(timeout=1000) or "").strip().replace("\n", " ")[:60]
            el_id = h.get_attribute("id") or ""
            href = h.get_attribute("href") or ""
            label = text or el_id or href or f"요소#{i}"
            candidates.append({"index": i, "label": label, "text": text, "id": el_id, "href": href})
        except Exception:
            continue
    return candidates


def crawl_page(page, path, label):
    console_errors = []
    network_errors = []

    def on_console(msg):
        if msg.type == "error":
            text = msg.text
            if not is_ignored_console(text):
                console_errors.append({"text": text[:300], "location": str(msg.location)})

    def on_pageerror(exc):
        console_errors.append({"text": str(exc)[:300], "type": "uncaught_exception"})

    def on_response(resp):
        try:
            if resp.status >= 400 and resp.url.startswith(BASE) and "/static/" not in resp.url:
                network_errors.append({"url": resp.url, "status": resp.status})
        except Exception:
            pass

    page.on("console", on_console)
    page.on("pageerror", on_pageerror)
    page.on("response", on_response)

    entry = {"page": path, "label": label, "actions": [], "page_errors": []}
    SHOT_DIR.mkdir(parents=True, exist_ok=True)

    try:
        resp = page.goto(f"{BASE}{path}", wait_until="domcontentloaded", timeout=30000)
        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except PWTimeout:
            pass
        if resp and resp.status >= 400:
            entry["page_errors"].append({"phase": "load", "status": resp.status})
    except Exception as e:
        entry["page_errors"].append({"phase": "load", "error": str(e)[:200]})
        page.remove_listener("console", on_console)
        page.remove_listener("pageerror", on_pageerror)
        page.remove_listener("response", on_response)
        return entry

    page.screenshot(path=str(SHOT_DIR / f"{slug(path)}_00_load.png"))

    if console_errors or network_errors:
        entry["page_errors"].append({
            "phase": "load",
            "console": console_errors.copy(),
            "network": network_errors.copy(),
        })
    console_errors.clear()
    network_errors.clear()

    candidates = collect_candidates(page)
    for cand in candidates:
        action_label = cand["label"]
        if is_destructive(cand["text"], cand["id"]):
            entry["actions"].append({
                "action": action_label, "status": "skipped",
                "reason": "되돌릴 수 없는 동작으로 판단되어 클릭하지 않음(존재만 확인)",
            })
            continue

        try:
            el = page.locator(CLICKABLE_SELECTOR).nth(cand["index"])
            if not el.is_visible():
                continue
            console_errors.clear()
            network_errors.clear()
            before_url = page.url
            try:
                el.scroll_into_view_if_needed(timeout=2000)
            except Exception:
                pass
            try:
                el.click(timeout=ACTION_TIMEOUT_MS)
            except Exception as first_err:
                # 클릭이 페이지 이동을 유발하면 컨텍스트가 사라지며 예외가 날 수 있다.
                # 실제로 이동했다면 정상 동작이므로 무시하고 계속 진행한다.
                if page.url != before_url:
                    pass
                else:
                    # 다른 오버레이/요소가 가려서 클릭이 막히는 경우 — force 클릭으로 재시도.
                    try:
                        el.click(timeout=2000, force=True)
                    except Exception:
                        entry["actions"].append({
                            "action": action_label, "status": "blocked",
                            "reason": "요소가 다른 요소에 가려져 있거나 클릭 가능한 상태가 아님",
                            "error": str(first_err)[:200],
                        })
                        continue
            page.wait_for_timeout(400)
            try:
                page.wait_for_load_state("networkidle", timeout=4000)
            except PWTimeout:
                pass

            navigated = page.url != before_url
            action_result = {"action": action_label, "status": "ok"}
            if console_errors or network_errors:
                action_result["status"] = "error"
                action_result["console"] = console_errors.copy()
                action_result["network"] = network_errors.copy()
                shot_name = f"{slug(path)}_{cand['index']:02d}_{slug(action_label)}.png"
                try:
                    page.screenshot(path=str(SHOT_DIR / shot_name))
                    action_result["screenshot"] = shot_name
                except Exception:
                    pass
            entry["actions"].append(action_result)

            try_close_modal(page)
            if navigated:
                page.goto(f"{BASE}{path}", wait_until="domcontentloaded", timeout=15000)
                try:
                    page.wait_for_load_state("networkidle", timeout=6000)
                except PWTimeout:
                    pass
                console_errors.clear()
                network_errors.clear()
        except PWTimeout as e:
            entry["actions"].append({"action": action_label, "status": "timeout", "error": str(e)[:200]})
        except Exception as e:
            entry["actions"].append({"action": action_label, "status": "click_failed", "error": str(e)[:200]})

    page.remove_listener("console", on_console)
    page.remove_listener("pageerror", on_pageerror)
    page.remove_listener("response", on_response)
    return entry


def main():
    global BASE
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=BASE)
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--only", default="", help="콤마로 구분된 경로만 실행 (예: /plan,/chat)")
    args = ap.parse_args()
    BASE = args.base.rstrip("/")

    pages = PAGES
    if args.only:
        wanted = set(args.only.split(","))
        pages = [p for p in PAGES if p[0] in wanted]

    print(f"\n=== SwimTech UI QA 크롤 시작 ===\n대상: {BASE}\n계정: {USERNAME}\n페이지 수: {len(pages)}\n")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not args.headed)
        context = browser.new_context(ignore_https_errors=True, viewport={"width": 1280, "height": 900})
        page = context.new_page()

        try:
            login(page)
            print("✅ 로그인 성공\n")
        except Exception as e:
            print(f"❌ {e}")
            browser.close()
            sys.exit(2)

        for path, label in pages:
            print(f"[{label}] {path} 검사 중...")
            entry = crawl_page(page, path, label)
            RESULTS.append(entry)
            n_err = sum(1 for a in entry["actions"] if a["status"] in ("error", "click_failed", "timeout", "blocked"))
            n_skip = sum(1 for a in entry["actions"] if a["status"] == "skipped")
            mark = "❌" if (entry["page_errors"] or n_err) else "✅"
            print(f"  {mark} 액션 {len(entry['actions'])}개 (에러 {n_err}, 건너뜀 {n_skip})")

        browser.close()

    # ── 리포트 저장 ──────────────────────────────────────
    summary = {
        "base": BASE, "username": USERNAME, "ran_at": datetime.now().isoformat(),
        "pages": RESULTS,
    }
    REPORT_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n" + "=" * 60)
    total_errors = []
    for entry in RESULTS:
        if entry["page_errors"]:
            total_errors.append((entry["page"], "페이지 로드 오류", entry["page_errors"]))
        for a in entry["actions"]:
            if a["status"] in ("error", "click_failed", "timeout", "blocked"):
                total_errors.append((entry["page"], a["action"], a))

    print(f"  검사한 페이지: {len(RESULTS)}  /  발견된 문제: {len(total_errors)}")
    print("=" * 60)
    if total_errors:
        print("\n❌ 문제 상세:")
        for page_path, action, detail in total_errors:
            print(f"  [{page_path}] {action}")
            if isinstance(detail, dict):
                for c in detail.get("console", []):
                    print(f"      console: {c['text']}")
                for n in detail.get("network", []):
                    print(f"      network: {n['status']} {n['url']}")
                if "reason" in detail:
                    print(f"      reason: {detail['reason']}")
                if "error" in detail:
                    print(f"      error: {detail['error']}")
    print(f"\n  → {REPORT_PATH} / {SHOT_DIR}/ 저장됨")
    sys.exit(1 if total_errors else 0)


if __name__ == "__main__":
    main()
