#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SwimMate 자동 QA 검증 스크립트 (UI 레벨 — 실제 브라우저 클릭)
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

환경변수:
    QA_USERNAME, QA_PASSWORD             — qa_runner.py와 동일한 고정 QA 계정 (기본 qabot/QaTest1234)
    QA_STUDENT_USERNAME, QA_STUDENT_PASSWORD
                                          — /coach 검증용 보조 학생 계정 (없으면 자동 생성, 기본 qabotstudent)
    ADMIN_ID, ADMIN_PW                   — 있을 때만 /admin을 읽기 전용(탭 전환만)으로 추가 검사

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

try:
    import requests
except ImportError:
    requests = None  # 코치 사전 연동 단계만 건너뛰고 나머지는 정상 동작

BASE = os.getenv("QA_BASE_URL", "https://swimtech.vercel.app")
USERNAME = os.getenv("QA_USERNAME", "qabot")
PASSWORD = os.getenv("QA_PASSWORD", "QaTest1234")
EMAIL = os.getenv("QA_EMAIL", f"{USERNAME}@example.com")

# /coach 검증용 — qabot을 코치로, 이 계정을 수강생으로 등록해 실제 연동 상태를 만든다
STUDENT_USERNAME = os.getenv("QA_STUDENT_USERNAME", "qabotstudent")
STUDENT_PASSWORD = os.getenv("QA_STUDENT_PASSWORD", PASSWORD)
STUDENT_EMAIL = os.getenv("QA_STUDENT_EMAIL", f"{STUDENT_USERNAME}@example.com")

# /admin — 둘 다 있을 때만 검사 대상에 포함 (운영 계정이므로 기본은 비활성)
ADMIN_ID = os.getenv("ADMIN_ID", "")
ADMIN_PW = os.getenv("ADMIN_PW", "")

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
    ("/coach", "코치 연동"),
]

PROTECTED_PATHS = {
    "/dashboard", "/plan", "/training-log", "/report", "/pool", "/badges",
    "/community", "/challenge", "/equipment", "/chat", "/videos",
    "/profile", "/injury", "/coach",
}

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

# /admin은 실제 운영 데이터를 다루는 관리자 패널이라 탭·필터 전환만 검사하고
# (현재 백엔드에 삭제/차단류 엔드포인트가 없긴 하지만) 향후 추가될 액션 버튼은 건드리지 않는다.
ADMIN_CLICKABLE_SELECTOR = ".admin-tab, .log-filter-btn, [data-tab], [data-type], #u-search-btn"

RESULTS = []  # 페이지별 결과 dict 리스트

PAGE_EXPECTATIONS = {
    "/login": {
        "selectors": ["#login-btn", "#demo-btn"],
    },
    "/dashboard": {
        "selectors": [".advisor-card", "#advisor-session", "#advisor-week", "#advisor-pool"],
        "texts": ["이번 주 훈련 추천"],
        "absent_texts": ["P3 Training Advisor"],
    },
    "/training-log": {
        "selectors": ["#goal-section", "#stat-total", "#stat-avg", "#cal-body", "#btn-set-goal"],
        "texts": ["이번 달 목표 거리"],
    },
    "/report": {
        "selectors": ["#stat-distance", "#stat-count", "#stat-avg", "#plan-performance", "#plan-goal-rate"],
        "texts": ["평균 거리 (m)", "플랜 수행률"],
    },
    "/plan": {
        "selectors": ["[data-pool-length]", "[data-cycle-level]", "[data-type-filter]", "[data-tab='myplan']"],
        "texts": ["내 플랜", "직접 구성"],
    },
    "/badges": {
        "selectors": ["#next-badge-panel", "#series-grid", ".badge-stage-card", ".next-badge-card", ".badge-card"],
        "texts": ["다음으로 노릴 뱃지", "단계별 뱃지 여정"],
    },
    "/admin": {
        "selectors": [".admin-badge", "[data-tab='training-health']", "[data-tab='feedback']", "#tab-training-health", "#h-log-count", "#h-recent-body", "#f-body", "#u-page-size", "#l-page-size", "#f-page-size", "#u-page-numbers", "#l-page-numbers", "#f-page-numbers", "#u-last", "#l-last", "#f-last"],
        "texts": ["SUPER ADMIN", "훈련 운영", "피드백", "페이지 조회", "처음", "끝"],
    },
}


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


def ensure_user_account(username=None, password=None, email=None, name="QA봇"):
    username = username or USERNAME
    password = password or PASSWORD
    email = email or EMAIL
    if requests is None:
        return username, password, email
    try:
        s = requests.Session()
        s.post(f"{BASE}/auth/register", json={
            "name": name,
            "email": email,
            "username": username,
            "password": password,
        }, timeout=30)
        r = s.post(f"{BASE}/auth/login", json={"username": username, "password": password}, timeout=30)
        if r.status_code == 200:
            return username, password, email

        suffix = re.sub(r"[^A-Za-z0-9]", "", username)[:4].lower() or "user"
        fallback_username = f"qa{int(time.time()) % 100000000}{suffix}"
        fallback_email = f"{fallback_username}@example.com"
        s2 = requests.Session()
        reg = s2.post(f"{BASE}/auth/register", json={
            "name": "QA임시봇",
            "email": fallback_email,
            "username": fallback_username,
            "password": password,
        }, timeout=30)
        login_res = s2.post(f"{BASE}/auth/login", json={"username": fallback_username, "password": password}, timeout=30)
        if login_res.status_code == 200:
            print(f"⚠ 기본 QA 계정 로그인 실패({r.status_code}) → 임시 계정으로 전환: {fallback_username}")
            return fallback_username, password, fallback_email
        raise RuntimeError(
            f"{username} 로그인 실패({r.status_code}), 임시 계정도 실패(register {reg.status_code}, login {login_res.status_code})"
        )
    except Exception as e:
        raise RuntimeError(f"QA 계정 준비 실패 — {e}")


def login(page, username=None, password=None):
    username = username or USERNAME
    password = password or PASSWORD
    page.goto(f"{BASE}/login", wait_until="domcontentloaded", timeout=30000)
    page.fill("#username", username)
    page.fill("#password", password)
    page.click("#login-btn")
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except PWTimeout:
        pass
    if "/login" in page.url:
        raise RuntimeError(f"로그인 실패 — 계정/비밀번호 확인 필요 (계정: {username})")


def is_auth_redirect(path, page):
    if path == "/admin":
        return False
    current = page.url.split("?", 1)[0].rstrip("/")
    return path in PROTECTED_PATHS and (current.endswith("/login") or current.endswith("/landing"))


def goto_page(page, path, username=None, password=None, timeout=45000):
    resp = page.goto(f"{BASE}{path}", wait_until="domcontentloaded", timeout=timeout)
    try:
        page.wait_for_load_state("networkidle", timeout=8000)
    except PWTimeout:
        pass
    if is_auth_redirect(path, page):
        login(page, username, password)
        resp = page.goto(f"{BASE}{path}", wait_until="domcontentloaded", timeout=timeout)
        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except PWTimeout:
            pass
    return resp


def check_page_expectations(page, path):
    expected = PAGE_EXPECTATIONS.get(path)
    if not expected:
        return []
    errors = []
    for selector in expected.get("selectors", []):
        try:
            page.locator(selector).first.wait_for(state="attached", timeout=5000)
        except Exception:
            errors.append({"type": "missing_selector", "selector": selector})
    body_text = ""
    try:
        body_text = page.locator("body").inner_text(timeout=3000)
    except Exception:
        pass
    for text in expected.get("texts", []):
        if text not in body_text:
            errors.append({"type": "missing_text", "text": text})
    for text in expected.get("absent_texts", []):
        if text in body_text:
            errors.append({"type": "forbidden_text", "text": text})
    return errors


def check_public_demo_entry(context):
    page = context.new_page()
    entry = {"page": "/login", "label": "Portfolio demo entry", "actions": [], "page_errors": []}
    try:
        page.goto(f"{BASE}/login", wait_until="domcontentloaded", timeout=30000)
        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except PWTimeout:
            pass
        expectation_errors = check_page_expectations(page, "/login")
        if expectation_errors:
            entry["page_errors"].append({"phase": "expectations", "errors": expectation_errors})
    except Exception as e:
        entry["page_errors"].append({"phase": "load", "error": str(e)[:200]})
    finally:
        try:
            page.close()
        except Exception:
            pass
    RESULTS.append(entry)
    mark = "FAIL" if entry["page_errors"] else "PASS"
    print(f"[Portfolio demo entry] /login {mark}")


def provision_coach_relationship():
    """qabot을 코치로, 보조 계정을 수강생으로 연동해 /coach가 빈 화면이 아니게 만든다.
    실패해도 전체 크롤을 막지 않고, /coach 검사만 건너뛰도록 False를 반환한다."""
    if requests is None:
        print("⚠ requests 미설치 — /coach 사전 연동을 건너뜁니다 (페이지는 빈 상태로 검사됩니다)")
        return True
    try:
        s = requests.Session()
        r = s.post(f"{BASE}/auth/login", json={"username": USERNAME, "password": PASSWORD}, timeout=30)
        if r.status_code != 200:
            print(f"⚠ qabot 로그인 실패({r.status_code}) — /coach 사전 연동 건너뜀")
            return True
        r = s.post(f"{BASE}/api/coach/register", json={"specialty": "QA", "career": "QA", "intro": "QA"}, timeout=30)
        if r.status_code != 200:
            print(f"⚠ qabot 코치 등록 실패({r.status_code}) — /coach 사전 연동 건너뜀")
            return True
        invite_code = r.json().get("invite_code")

        s2 = requests.Session()
        s2.post(f"{BASE}/auth/register", json={
            "name": "QA수강생", "email": STUDENT_EMAIL,
            "username": STUDENT_USERNAME, "password": STUDENT_PASSWORD,
        }, timeout=30)  # 이미 있으면 400 — 무시하고 로그인 시도
        r = s2.post(f"{BASE}/auth/login", json={"username": STUDENT_USERNAME, "password": STUDENT_PASSWORD}, timeout=30)
        if r.status_code != 200:
            print(f"⚠ 보조 학생 계정 로그인 실패({r.status_code}) — /coach 사전 연동 건너뜀")
            return True
        if invite_code:
            s2.post(f"{BASE}/api/coach/join", json={"invite_code": invite_code}, timeout=30)
        return True
    except Exception as e:
        print(f"⚠ /coach 사전 연동 중 오류({e}) — 페이지는 그대로 검사합니다")
        return True


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


def collect_candidates(page, selector=CLICKABLE_SELECTOR):
    """클릭 후보 요소의 메타데이터(텍스트/id/태그)를 미리 수집한다."""
    try:
        handles = page.locator(selector).all()
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


def crawl_page(page, path, label, selector=CLICKABLE_SELECTOR, username=None, password=None):
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
            if resp.status == 401 and "/auth/refresh" in resp.url:
                return
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
        resp = goto_page(page, path, username=username, password=password)
        if resp and resp.status >= 400:
            entry["page_errors"].append({"phase": "load", "status": resp.status})
    except Exception as e:
        entry["page_errors"].append({"phase": "load", "error": str(e)[:200]})
        page.remove_listener("console", on_console)
        page.remove_listener("pageerror", on_pageerror)
        page.remove_listener("response", on_response)
        return entry

    page.screenshot(path=str(SHOT_DIR / f"{slug(path)}_00_load.png"))

    expectation_errors = check_page_expectations(page, path)
    if expectation_errors:
        entry["page_errors"].append({
            "phase": "expectations",
            "errors": expectation_errors,
        })

    if console_errors or network_errors:
        entry["page_errors"].append({
            "phase": "load",
            "console": console_errors.copy(),
            "network": network_errors.copy(),
        })
    console_errors.clear()
    network_errors.clear()

    candidates = collect_candidates(page, selector)
    for cand in candidates:
        action_label = cand["label"]
        if is_destructive(cand["text"], cand["id"]):
            entry["actions"].append({
                "action": action_label, "status": "skipped",
                "reason": "되돌릴 수 없는 동작으로 판단되어 클릭하지 않음(존재만 확인)",
            })
            continue

        try:
            el = page.locator(selector).nth(cand["index"])
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

            try_close_modal(page)
            if navigated:
                try:
                    goto_page(page, path, username=username, password=password, timeout=30000)
                except Exception as nav_err:
                    action_result["status"] = "error"
                    action_result["error"] = f"원래 페이지 복귀 실패: {str(nav_err)[:160]}"
                console_errors.clear()
                network_errors.clear()
            entry["actions"].append(action_result)
        except PWTimeout as e:
            entry["actions"].append({"action": action_label, "status": "timeout", "error": str(e)[:200]})
        except Exception as e:
            entry["actions"].append({"action": action_label, "status": "click_failed", "error": str(e)[:200]})

    page.remove_listener("console", on_console)
    page.remove_listener("pageerror", on_pageerror)
    page.remove_listener("response", on_response)
    return entry


def main():
    global BASE, USERNAME, PASSWORD, EMAIL
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

    try:
        USERNAME, PASSWORD, EMAIL = ensure_user_account()
        print(f"✅ QA 계정 준비 완료: {USERNAME}")
    except Exception as e:
        print(f"❌ {e}")
        sys.exit(2)

    do_admin = bool(ADMIN_ID and ADMIN_PW) and (not args.only or "/admin" in args.only.split(","))
    if any(p[0] == "/coach" for p in pages):
        print("코치-수강생 연동 사전 준비 중...")
        provision_coach_relationship()

    print(f"\n=== SwimMate UI QA 크롤 시작 ===\n대상: {BASE}\n계정: {USERNAME}\n페이지 수: {len(pages)}"
          f"{' (+/admin)' if do_admin else ''}\n")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not args.headed)
        context = browser.new_context(ignore_https_errors=True, viewport={"width": 1280, "height": 900})
        check_public_demo_entry(context)
        login_page = context.new_page()

        try:
            login(login_page)
            print("✅ 로그인 성공\n")
        except Exception as e:
            print(f"❌ {e}")
            browser.close()
            sys.exit(2)
        finally:
            try:
                login_page.close()
            except Exception:
                pass

        for path, label in pages:
            print(f"[{label}] {path} 검사 중...")
            page = context.new_page()
            entry = crawl_page(page, path, label)
            RESULTS.append(entry)
            n_err = sum(1 for a in entry["actions"] if a["status"] in ("error", "click_failed", "timeout", "blocked"))
            n_skip = sum(1 for a in entry["actions"] if a["status"] == "skipped")
            mark = "❌" if (entry["page_errors"] or n_err) else "✅"
            print(f"  {mark} 액션 {len(entry['actions'])}개 (에러 {n_err}, 건너뜀 {n_skip})")
            try:
                page.close()
            except Exception:
                pass

        if do_admin:
            print("\n[관리자] /admin 검사 중... (탭/필터 전환만 — 읽기 전용)")
            admin_context = browser.new_context(ignore_https_errors=True, viewport={"width": 1280, "height": 900})
            admin_page = admin_context.new_page()
            try:
                login(admin_page, ADMIN_ID, ADMIN_PW)
                entry = crawl_page(admin_page, "/admin", "관리자", selector=ADMIN_CLICKABLE_SELECTOR,
                                   username=ADMIN_ID, password=ADMIN_PW)
                if "/landing" in admin_page.url or admin_page.url.rstrip("/").endswith("/landing"):
                    entry["page_errors"].append({"phase": "load", "error": "관리자 권한으로 인식되지 않아 /landing으로 리다이렉트됨"})
                RESULTS.append(entry)
                n_err = sum(1 for a in entry["actions"] if a["status"] in ("error", "click_failed", "timeout", "blocked"))
                mark = "❌" if (entry["page_errors"] or n_err) else "✅"
                print(f"  {mark} 액션 {len(entry['actions'])}개 (에러 {n_err})")
            except Exception as e:
                print(f"  ❌ 관리자 로그인/검사 실패: {e}")
                RESULTS.append({"page": "/admin", "label": "관리자", "actions": [],
                                 "page_errors": [{"phase": "login", "error": str(e)[:200]}]})
            admin_context.close()

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
            details = detail if isinstance(detail, list) else [detail]
            for item in details:
                if not isinstance(item, dict):
                    continue
                if "phase" in item:
                    print(f"      phase: {item['phase']}")
                for e in item.get("errors", []):
                    print(f"      expectation: {e}")
                for c in item.get("console", []):
                    print(f"      console: {c['text']}")
                for n in item.get("network", []):
                    print(f"      network: {n['status']} {n['url']}")
                if "reason" in item:
                    print(f"      reason: {item['reason']}")
                if "error" in item:
                    print(f"      error: {item['error']}")
    print(f"\n  → {REPORT_PATH} / {SHOT_DIR}/ 저장됨")
    sys.exit(1 if total_errors else 0)


if __name__ == "__main__":
    main()
