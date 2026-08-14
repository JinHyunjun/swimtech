#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SwimMate 자동 QA 검증 스크립트 (API 레벨)
─────────────────────────────────────────────────────────
하는 일:
  1) GitHub Actions Secrets의 일반·학생·관리자 QA 계정 확인
  2) 고정 QA 계정으로 인증·권한 경계 검증
  3) 핵심 API 시나리오 순차 검증 → PASS/FAIL 표 + 종료코드

검증 대상: https://swimtech.vercel.app  (실제 Vercel→Render 프록시 경로)
쿠키 기반 인증을 requests.Session 으로 그대로 따라감.

사용법:
  pip install requests
  # 로그인 정보는 GitHub Actions Secrets 또는 동일 이름의 환경변수로만 전달한다.
  python qa_runner.py
  # 옵션:
  python qa_runner.py --base https://swimtech.vercel.app
"""
import os, sys, time, json, argparse, random, string

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass  # Python<3.7 또는 콘솔이 reconfigure를 지원하지 않는 환경

try:
    import requests
except ImportError:
    print("requests 필요: pip install requests"); sys.exit(1)

BASE = os.getenv("QA_BASE_URL", "https://swimtech.vercel.app")
RESULTS = []   # (no, name, status, detail)

def rec(no, name, ok, detail=""):
    RESULTS.append((no, name, "PASS" if ok else "FAIL", detail))
    mark = "✅" if ok else "❌"
    print(f"  {mark} [{no:>2}] {name}" + (f"  → {detail}" if detail else ""))
    return ok

def rnd(n=6):
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=n))

def jget(r):
    try: return r.json()
    except Exception: return {}

def status_code(r):
    return r.status_code if r is not None else "-"

def to_int(value, default=0):
    try:
        return int(float(value or 0))
    except Exception:
        return default

def this_month():
    return int(time.strftime("%Y")), int(time.strftime("%m"))

def month_url(path, year, month):
    return f"{BASE}{path}?year={year}&month={month}"

def cleanup_logs(sess, log_ids):
    ok = True
    details = []
    for log_id in [x for x in log_ids if x]:
        try:
            r = sess.delete(f"{BASE}/api/training-log/{log_id}", timeout=60)
            details.append(f"{log_id}:{r.status_code}")
            ok = ok and r.status_code in (200, 404)
        except Exception as e:
            details.append(f"{log_id}:ERR {str(e)[:30]}")
            ok = False
    return ok, ", ".join(details)

# ─────────────────────────────────────────────────────────
def main():
    global BASE
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=BASE)
    args = ap.parse_args()
    BASE = args.base.rstrip("/")

    from validate_qa_credentials import missing_credentials

    missing = missing_credentials()
    if missing:
        print("❌ QA 계정 환경변수가 없습니다: " + ", ".join(missing))
        sys.exit(2)
    print(f"\n=== SwimMate QA 검증 시작 ===\n대상: {BASE}\n")

    # ── 0. 배포/기본 접속 확인 ──────────────────────────
    print("[0] 배포/기본 접속")
    try:
        r = requests.get(f"{BASE}/api/health", timeout=90)  # 콜드스타트 대비 90s
        health = jget(r)
        rec(
            0,
            "백엔드 health + DB migration revision (콜드스타트 깨우기)",
            r.status_code == 200 and health.get("schema_revision") == "20260723_10",
            f"{r.status_code}, revision={health.get('schema_revision')}",
        )
    except Exception as e:
        rec(0, "백엔드 health", False, str(e)[:60])

    admin_sess = None

    # ── 관리자 슈퍼계정 로그인 ──────────────────────────
    # QA가 관리자 계정을 임의 생성하지 않는다. DB에서 role='admin'인 전용 계정을 사용한다.
    admin_id, admin_pw = os.environ["ADMIN_ID"], os.environ["ADMIN_PW"]
    s = requests.Session()
    admin_login = s.post(
        f"{BASE}/auth/login",
        json={"username": admin_id, "password": admin_pw},
        timeout=60,
    )
    admin_login_json = jget(admin_login)
    admin_ok = admin_login.status_code == 200 and admin_login_json.get("redirect") == "/admin"
    if admin_ok:
        admin_sess = s
    rec(
        "A",
        "관리자 전용 계정 로그인",
        admin_ok,
        f"status {admin_login.status_code}, redirect={admin_login_json.get('redirect')}",
    )

    # ── QA 계정 + 세션 준비 ─────────────────────────────
    sess = requests.Session()
    # 고정 QA 계정 재사용 (DB에 계정이 쌓이지 않도록). cron 반복 안전.
    uname = os.environ["QA_USERNAME"]
    pw = os.environ["QA_PASSWORD"]
    email = os.environ["QA_EMAIL"]

    anonymous = requests.Session()
    anonymous_me = anonymous.get(f"{BASE}/auth/me", timeout=60)
    anonymous_dashboard = anonymous.get(f"{BASE}/api/dashboard/summary", timeout=60)
    anonymous_my_data = anonymous.get(f"{BASE}/api/account/insights", timeout=60)
    anonymous_onboarding = anonymous.get(f"{BASE}/auth/onboarding", timeout=60)
    anonymous_chat_context = anonymous.post(
        f"{BASE}/api/chat/context-preview",
        json={"content": "내 최근 훈련을 분석해줘"},
        timeout=60,
    )
    rec(
        "A1",
        "비로그인 보호 경계",
        anonymous_me.status_code == 401 and anonymous_dashboard.status_code == 401
        and anonymous_my_data.status_code == 401
        and anonymous_onboarding.status_code == 401
        and anonymous_chat_context.status_code == 401,
        f"me {anonymous_me.status_code}, dashboard {anonymous_dashboard.status_code}, "
        f"my-data {anonymous_my_data.status_code}, onboarding {anonymous_onboarding.status_code}, "
        f"chat-context {anonymous_chat_context.status_code}",
    )

    wrong_login = anonymous.post(
        f"{BASE}/auth/login",
        json={"username": uname, "password": f"{pw}-invalid"},
        timeout=60,
    )
    rec("A2", "잘못된 비밀번호 거부", wrong_login.status_code == 401, f"status {wrong_login.status_code}")

    # 1. 일반 회원가입 (이미 있으면 "이미 사용 중" 400도 정상으로 간주)
    print("\n[1-6] 계정/인증")
    r = sess.post(f"{BASE}/auth/register", json={
        "name": "QA봇", "email": email, "username": uname, "password": pw}, timeout=60)
    # ?? QA ??? ?? ?? ? ?? ??? ? ??. ??? ???? ?? ?? ???? ???.
    already = (r.status_code == 400)
    rec(1, "일반 회원가입(또는 기존계정)", (r.status_code == 200 and jget(r).get("status")=="ok") or already,
        "신규 생성" if r.status_code == 200 else f"기존 계정 재사용({r.status_code})")

    # 2. 일반 로그인
    r = sess.post(f"{BASE}/auth/login", json={"username": uname, "password": pw}, timeout=60)
    login_json = jget(r)
    logged_in = r.status_code == 200 and login_json.get("redirect") == "/landing"
    has_cookie = "swimtech_token" in sess.cookies.get_dict()
    rec(2, "일반 로그인 (+쿠키 발급)", logged_in and has_cookie,
        f"status {r.status_code}, redirect={login_json.get('redirect')}, "
        f"쿠키 {'있음' if has_cookie else '없음'}")

    cookie_header = r.headers.get("set-cookie", "").lower()
    cookie_secure = all(flag in cookie_header for flag in ("httponly", "secure", "samesite=lax"))
    rec("2a", "인증 쿠키 보안 속성", logged_in and cookie_secure,
        "HttpOnly/Secure/SameSite=Lax" if cookie_secure else "필수 속성 누락")

    if not logged_in:
        with open("qa_report.json", "w", encoding="utf-8") as fp:
            json.dump([{"no": str(n), "name": nm, "status": st, "detail": d}
                       for n, nm, st, d in RESULTS], fp, ensure_ascii=False, indent=2)
        print("❌ 고정 QA 계정 로그인에 실패해 인증 이후 시나리오를 중단합니다.")
        sys.exit(2)

    # 3. 새로고침 후 로그인 유지 (=같은 쿠키로 /me 200)
    r = sess.get(f"{BASE}/auth/me", timeout=60)
    rec(3, "로그인 유지 (/auth/me)", r.status_code == 200, f"{r.status_code}")

    # 4. 로그아웃
    r = sess.post(f"{BASE}/auth/logout", timeout=60)
    after = sess.get(f"{BASE}/auth/me", timeout=60)
    rec(4, "로그아웃 (이후 /me 401)", r.status_code == 200 and after.status_code == 401,
        f"logout {r.status_code}, me {after.status_code}")

    # 5. 다시 로그인
    r = sess.post(f"{BASE}/auth/login", json={"username": uname, "password": pw}, timeout=60)
    rec(5, "재로그인", r.status_code == 200, f"{r.status_code}")

    # 6. 닉네임 설정 (일반계정은 소셜 전용이라 400이 정상 동작)
    r = sess.post(f"{BASE}/auth/nickname", json={"nickname": "큐에이"+rnd(2)}, timeout=60)
    expected = r.status_code in (200, 400)
    note = "일반계정은 소셜전용(400) — 의도된 동작" if r.status_code == 400 else "설정됨"
    rec(6, "닉네임 설정", expected, f"{r.status_code} ({note})")

    screenshot_unknown = sess.post(
        f"{BASE}/api/training-log/screenshot/confirm",
        json={
            "preview_token": "qa-invalid-screenshot-preview",
            "log_date": time.strftime("%Y-%m-%d"),
            "total_distance": 1000,
            "duration_minutes": 40,
            "pool_length": 25,
            "stroke_type": "자유수영",
            "intensity": "보통",
            "stroke_distances": [],
        },
        timeout=60,
    )
    screenshot_unknown_body = jget(screenshot_unknown)
    rec(
        "6f",
        "운동 스크린샷 확인 토큰 경계",
        screenshot_unknown.status_code == 404
        and "다시 분석" in str(screenshot_unknown_body.get("detail") or ""),
        f"status {screenshot_unknown.status_code}, detail={screenshot_unknown_body.get('detail')}",
    )

    export_wrong = sess.post(
        f"{BASE}/api/account/export",
        json={"current_password": f"{pw}-invalid"},
        timeout=60,
    )
    export_ok = sess.post(
        f"{BASE}/api/account/export",
        json={"current_password": pw},
        timeout=90,
    )
    export_doc = jget(export_ok)
    export_account = export_doc.get("account") or {}
    rec(
        "6d",
        "개인 데이터 JSON 내보내기 + 비밀번호 재확인",
        export_wrong.status_code == 401
        and export_ok.status_code == 200
        and export_doc.get("export_format") == "swimmate-personal-data"
        and export_doc.get("export_schema_version") == 1
        and export_account.get("username") == uname
        and "password_hash" not in export_account
        and "social_id" not in export_account
        and "attachment" in export_ok.headers.get("content-disposition", "").lower()
        and export_ok.headers.get("cache-control") == "no-store",
        f"wrong {export_wrong.status_code}, export {export_ok.status_code}, "
        f"sections={len(export_doc.get('records') or {})}",
    )

    password_wrong = sess.post(
        f"{BASE}/api/account/password",
        json={"current_password": f"{pw}-invalid", "new_password": f"QaNew{rnd(8)}1"},
        timeout=60,
    )
    logout_all_wrong = sess.post(
        f"{BASE}/api/account/logout-all",
        json={"current_password": f"{pw}-invalid"},
        timeout=60,
    )
    delete_account_wrong = sess.delete(
        f"{BASE}/auth/me",
        json={"confirmation": "탈퇴", "current_password": f"{pw}-invalid"},
        timeout=60,
    )
    session_still_valid = sess.get(f"{BASE}/auth/me", timeout=60)
    rec(
        "6e",
        "계정 보안 변경의 현재 비밀번호 경계",
        password_wrong.status_code == 401
        and logout_all_wrong.status_code == 401
        and delete_account_wrong.status_code == 401
        and session_still_valid.status_code == 200,
        f"password {password_wrong.status_code}, logout-all {logout_all_wrong.status_code}, "
        f"withdraw {delete_account_wrong.status_code}, session {session_still_valid.status_code}",
    )

    onboarding_before_res = sess.get(f"{BASE}/auth/onboarding", timeout=60)
    onboarding_before = jget(onboarding_before_res)
    level_aliases = {"beginner": "입문", "intermediate": "중급", "advanced": "고급"}
    valid_levels = ["입문", "초급", "중급", "고급"]
    valid_goals = ["기록단축", "건강", "영법교정", "취미"]
    original_level = level_aliases.get(onboarding_before.get("level"), onboarding_before.get("level"))
    if original_level not in valid_levels:
        original_level = "초급"
    original_goal = onboarding_before.get("goal")
    if original_goal not in valid_goals:
        original_goal = "건강"
    original_weekly = min(7, max(1, to_int(onboarding_before.get("weekly_goal"), 3)))
    original_pool = 50 if to_int(onboarding_before.get("preferred_pool_length")) == 50 else 25
    probe = {
        "level": "중급" if original_level != "중급" else "초급",
        "goal": "영법교정" if original_goal != "영법교정" else "건강",
        "weekly_goal": 4 if original_weekly != 4 else 3,
        "preferred_pool_length": 50 if original_pool == 25 else 25,
    }
    onboarding_save = sess.put(f"{BASE}/auth/onboarding", json=probe, timeout=60)
    onboarding_after = sess.get(f"{BASE}/auth/onboarding", timeout=60)
    onboarding_me = sess.get(f"{BASE}/auth/me", timeout=60)
    onboarding_advisor = sess.get(f"{BASE}/api/dashboard/training-advisor", timeout=60)
    after_json = jget(onboarding_after)
    me_profile = jget(onboarding_me).get("training_profile") or {}
    advisor_profile = jget(onboarding_advisor)
    onboarding_ok = (
        onboarding_before_res.status_code == 200
        and onboarding_save.status_code == 200
        and onboarding_after.status_code == 200
        and onboarding_me.status_code == 200
        and onboarding_advisor.status_code == 200
        and jget(onboarding_save).get("redirect") == "/landing"
        and all(after_json.get(key) == value for key, value in probe.items())
        and me_profile.get("preferred_pool_length") == probe["preferred_pool_length"]
        and advisor_profile.get("preferred_pool_length") == probe["preferred_pool_length"]
        and advisor_profile.get("training_level") == probe["level"]
        and advisor_profile.get("training_goal") == probe["goal"]
    )
    rec("6a", "개인화 온보딩→내 정보·훈련 추천 연동", onboarding_ok,
        f"get {onboarding_before_res.status_code}, save {onboarding_save.status_code}/"
        f"redirect={jget(onboarding_save).get('redirect')}, "
        f"me {onboarding_me.status_code}, advisor {onboarding_advisor.status_code}/"
        f"pool={advisor_profile.get('preferred_pool_length')}/level={advisor_profile.get('training_level')}/"
        f"goal={advisor_profile.get('training_goal')}")
    try:
        sess.put(f"{BASE}/auth/onboarding", json={
            "level": original_level,
            "goal": original_goal,
            "weekly_goal": original_weekly,
            "preferred_pool_length": original_pool,
        }, timeout=60)
    except Exception:
        pass

    knowledge_preview = sess.post(
        f"{BASE}/api/chat/context-preview",
        json={"content": "25m 풀 경기의 사이클과 실격 규정을 알려줘"},
        timeout=60,
    )
    personal_preview = sess.post(
        f"{BASE}/api/chat/context-preview",
        json={"content": "내 최근 훈련과 컨디션을 바탕으로 맞춤 세션을 추천해줘"},
        timeout=60,
    )
    knowledge_grounding = jget(knowledge_preview).get("grounding") or {}
    personal_grounding = jget(personal_preview).get("grounding") or {}
    knowledge_keys = {
        item.get("key") for item in knowledge_grounding.get("topics") or []
    }
    official_organizations = {
        item.get("organization") for item in knowledge_grounding.get("sources") or []
    }
    personal_meta = personal_grounding.get("personalization") or {}
    chat_grounding_ok = (
        knowledge_preview.status_code == 200
        and personal_preview.status_code == 200
        and {"pool_length", "training_cycle", "competition_rules"} <= knowledge_keys
        and "World Aquatics" in official_organizations
        and personal_meta.get("available") is True
        and personal_meta.get("applied") is True
        and "훈련 설정" in (personal_meta.get("categories") or [])
        and personal_meta.get("privacy_scope") == "authenticated_customer_only"
    )
    rec(
        "6c",
        "AI 코치 지식 근거·본인 기록 개인화 매핑",
        chat_grounding_ok,
        f"knowledge {knowledge_preview.status_code}/{sorted(knowledge_keys)}, "
        f"personal {personal_preview.status_code}/"
        f"applied={personal_meta.get('applied')}/"
        f"categories={len(personal_meta.get('categories') or [])}",
    )

    year, month = this_month()

    demo_sess = requests.Session()
    demo_login = demo_sess.post(f"{BASE}/auth/demo", timeout=60)
    demo_me = demo_sess.get(f"{BASE}/auth/me", timeout=60)
    demo_summary = demo_sess.get(f"{BASE}/api/dashboard/summary", timeout=60)
    demo_report = demo_sess.get(month_url("/api/report/monthly", year, month), timeout=60)
    demo_my_data = demo_sess.get(f"{BASE}/api/account/insights", timeout=60)
    demo_me_json = jget(demo_me)
    demo_summary_json = jget(demo_summary)
    demo_report_json = jget(demo_report)
    demo_my_data_json = jget(demo_my_data)
    demo_ok = (
        demo_login.status_code == 200
        and jget(demo_login).get("redirect") == "/landing"
        and demo_me.status_code == 200
        and demo_me_json.get("is_demo") is True
        and demo_summary.status_code == 200
        and to_int(demo_summary_json.get("total_logs")) >= 6
        and to_int(demo_summary_json.get("total_distance")) > 0
        and demo_report.status_code == 200
        and to_int(demo_report_json.get("total_distance")) > 0
        and demo_my_data.status_code == 200
        and demo_my_data_json.get("is_demo") is True
        and demo_my_data_json.get("has_data") is True
        and len(demo_my_data_json.get("monthly_trend") or []) == 12
    )
    rec("6b", "Portfolio demo mode (/auth/demo)", demo_ok,
        f"login {demo_login.status_code}/redirect={jget(demo_login).get('redirect')}, "
        f"me {demo_me.status_code}/demo={demo_me_json.get('is_demo')}, "
        f"summary {demo_summary.status_code}/logs={demo_summary_json.get('total_logs')}/distance={demo_summary_json.get('total_distance')}, "
        f"report {demo_report.status_code}/distance={demo_report_json.get('total_distance')}, "
        f"my-data {demo_my_data.status_code}/months={len(demo_my_data_json.get('monthly_trend') or [])}")

    baseline_stats = {}
    baseline_report = {}
    baseline_my_data = {}
    baseline_goal_distance = 0
    try:
        baseline_stats = jget(sess.get(month_url("/api/training-log/stats", year, month), timeout=60))
        baseline_report = jget(sess.get(month_url("/api/report/monthly", year, month), timeout=60))
        baseline_my_data = jget(sess.get(f"{BASE}/api/account/insights", timeout=60))
        baseline_goal = jget(sess.get(month_url("/api/training-log/goal", year, month), timeout=60))
        baseline_goal_distance = to_int(baseline_goal.get("goal_distance"))
    except Exception:
        pass
    baseline_distance = max(to_int(baseline_report.get("total_distance")), to_int(baseline_stats.get("total_distance")))
    baseline_count = max(to_int(baseline_report.get("total_count")), to_int(baseline_stats.get("count")))
    baseline_plan_perf = baseline_report.get("plan_performance") or {}
    baseline_plan_completed = to_int(baseline_plan_perf.get("completed_sessions"))
    baseline_plan_distance = to_int(baseline_plan_perf.get("plan_distance"))
    baseline_planned_sets = to_int(baseline_plan_perf.get("planned_sets"))
    baseline_completed_sets = to_int(baseline_plan_perf.get("completed_sets"))
    baseline_lifetime = baseline_my_data.get("lifetime") or {}
    baseline_habits = baseline_my_data.get("recording_habits") or {}
    baseline_lifetime_distance = to_int(baseline_lifetime.get("total_distance"))
    baseline_lifetime_sessions = to_int(baseline_lifetime.get("total_sessions"))
    baseline_structured_sessions = to_int(baseline_habits.get("structured_sessions"))
    baseline_test_attempts = to_int(baseline_habits.get("test_attempts"))
    cleanup_ids = []
    benchmark_ids = []
    readiness_before = None

    # ── 7. 메인 화면/라우팅 ─────────────────────────────
    print("\n[7-8] 화면/라우팅 (정적 페이지 200 확인)")
    pages = {"/landing": "랜딩", "/dashboard": "대시보드", "/my-data": "내 수영 데이터", "/plan": "플랜",
             "/training-log": "훈련일지", "/workout": "풀사이드 훈련", "/report": "리포트", "/pool": "수영장", "/clubs": "클럽·반",
             "/community": "커뮤니티", "/challenge": "챌린지", "/badges": "뱃지"}
    bad = []
    for path, label in pages.items():
        rr = requests.get(f"{BASE}{path}", timeout=60)
        if rr.status_code != 200: bad.append(f"{label}({rr.status_code})")
    root_redirect = requests.get(f"{BASE}/", allow_redirects=False, timeout=60)
    app_redirect = requests.get(f"{BASE}/app", allow_redirects=False, timeout=60)
    landing_redirects_ok = (
        root_redirect.status_code in (301, 302, 307, 308)
        and root_redirect.headers.get("location") == "/landing"
        and app_redirect.status_code in (301, 302, 307, 308)
        and app_redirect.headers.get("location") == "/landing"
    )
    rec(
        7,
        "메인/주요 페이지 라우팅",
        not bad and landing_redirects_ok,
        (
            f"전부 200, /=/landing({root_redirect.status_code}), "
            f"/app=/landing({app_redirect.status_code})"
            if not bad and landing_redirects_ok
            else "실패: " + ", ".join(bad or ["대표 홈 리다이렉트 불일치"])
        ),
    )

    # 8. 수영장 지도 (페이지 200 + 카카오 SDK appkey 박혀있는지)
    rr = requests.get(f"{BASE}/pool", timeout=60)
    has_key = "appkey=" in rr.text and "{{" not in rr.text
    utf8_ok = "수영장" in rr.text
    rec(8, "수영장 지도 (SDK 키+한글)", rr.status_code == 200 and has_key and utf8_ok,
        f"page {rr.status_code}, key {'O' if has_key else 'X'}, 한글 {'O' if utf8_ok else 'X(인코딩)'}")

    # ── 9-11. 훈련 일지 ─────────────────────────────────
    print("\n[9-11] 훈련 일지")
    today = time.strftime("%Y-%m-%d")
    r = sess.post(f"{BASE}/api/training-log", json={
        "log_date": today, "stroke_type": "자유형", "total_distance": 1500,
        "duration_minutes": 60, "intensity": "보통", "memo": "QA 자동 기록"}, timeout=60)
    log_id = jget(r).get("id") or jget(r).get("log_id")
    initial_set_save = sess.put(f"{BASE}/api/training-log/{log_id}/sets", json={
        "sync_total_distance": False,
        "sets": [
            {"phase": "warmup", "description": "QA warmup", "target_reps": 1,
             "target_distance_m": 500, "completed_reps": 1, "status": "completed"},
            {"phase": "main", "description": "QA main", "target_reps": 5,
             "target_distance_m": 200, "target_cycle_seconds": 210,
             "completed_reps": 5, "status": "completed"},
        ],
    }, timeout=60) if log_id else None
    rec(9, "훈련 일지 작성", r.status_code in (200, 201), f"{r.status_code}, id={log_id}")

    r = sess.get(f"{BASE}/api/training-log", timeout=60)
    logs = jget(r)
    found = isinstance(logs, (list, dict))
    rec(10, "훈련 일지 조회", r.status_code == 200 and found, f"{r.status_code}")

    # stats/streak도 같이
    rs = sess.get(month_url("/api/training-log/stats", year, month), timeout=60)
    rk = sess.get(f"{BASE}/api/training-log/streak", timeout=60)
    set_get = sess.get(f"{BASE}/api/training-log/{log_id}/sets", timeout=60) if log_id else None
    set_json = jget(set_get) if set_get else {}
    set_items = set_json.get("sets") or []
    execution_set_id = set_items[1].get("id") if len(set_items) > 1 else None
    set_execution = sess.patch(f"{BASE}/api/training-log/{log_id}/sets/{execution_set_id}", json={
        "completed_reps": 3,
        "completed_distance_m": 600,
        "actual_cycle_seconds": 205,
        "rpe": 7,
        "status": "modified",
        "notes": "QA 풀사이드 수행",
        "sync_total_distance": True,
    }, timeout=60) if log_id and execution_set_id else None
    execution_json = jget(set_execution) if set_execution else {}
    execution_item = execution_json.get("set") or {}
    execution_ok = (
        bool(set_execution) and set_execution.status_code == 200
        and to_int(execution_item.get("completed_reps")) == 3
        and to_int(execution_item.get("completed_distance_m")) == 600
        and to_int(execution_item.get("actual_cycle_seconds")) == 205
        and to_int(execution_item.get("rpe")) == 7
        and execution_item.get("status") == "modified"
        and to_int((execution_json.get("summary") or {}).get("completed_distance_m")) == 1100
    )
    rec("10d", "풀사이드 단일 세트 수행 저장", execution_ok,
        f"patch {getattr(set_execution, 'status_code', '-')}, set={execution_set_id}, "
        f"reps={execution_item.get('completed_reps')}, distance={execution_item.get('completed_distance_m')}, "
        f"cycle={execution_item.get('actual_cycle_seconds')}, rpe={execution_item.get('rpe')}")
    set_replace = sess.put(f"{BASE}/api/training-log/{log_id}/sets", json={
        "sync_total_distance": True,
        "sets": [
            {"phase": "warmup", "description": "QA warmup", "target_reps": 1,
             "target_distance_m": 500, "completed_reps": 1, "status": "completed"},
            {"phase": "main", "description": "QA main", "target_reps": 5,
             "target_distance_m": 200, "target_cycle_seconds": 210,
             "completed_reps": 4, "status": "modified"},
        ],
    }, timeout=60) if log_id else None
    replace_json = jget(set_replace) if set_replace else {}
    set_flow_ok = (
        bool(initial_set_save) and initial_set_save.status_code == 200
        and bool(set_get) and set_get.status_code == 200
        and len(set_json.get("sets") or []) == 2
        and to_int((set_json.get("summary") or {}).get("completed_distance_m")) == 1500
        and bool(set_replace) and set_replace.status_code == 200
        and to_int((replace_json.get("summary") or {}).get("completed_distance_m")) == 1300
    )
    rec("10c", "세트 단위 기록 조회·수행 갱신", set_flow_ok,
        f"save {getattr(initial_set_save, 'status_code', '-')}, "
        f"get {getattr(set_get, 'status_code', '-')}/sets={len(set_json.get('sets') or [])}, "
        f"replace {getattr(set_replace, 'status_code', '-')}/distance={(replace_json.get('summary') or {}).get('completed_distance_m')}")
    rec("10b", "일지 통계/연속출석", rs.status_code == 200 and rk.status_code == 200,
        f"stats {rs.status_code}, streak {rk.status_code}")

    # 11. 수정/삭제
    if log_id:
        ru = sess.put(f"{BASE}/api/training-log/{log_id}", json={
            "log_date": today, "stroke_type": "배영", "total_distance": 2000,
            "duration_minutes": 70, "intensity": "힘듦", "memo": "QA 수정"}, timeout=60)
        rd = sess.delete(f"{BASE}/api/training-log/{log_id}", timeout=60)
        cascade = sess.get(f"{BASE}/api/training-log/{log_id}/sets", timeout=60)
        rec("11a", "훈련 일지 삭제 시 세트 기록 연쇄 삭제", cascade.status_code == 404,
            f"sets-after-delete {cascade.status_code}")
        rec(11, "훈련 일지 수정/삭제", ru.status_code == 200 and rd.status_code == 200,
            f"수정 {ru.status_code}, 삭제 {rd.status_code}")
    else:
        rec(11, "훈련 일지 수정/삭제", False, "작성 id 없음 → 스킵")

    # 리포트/대시보드 연동 검증용 기록은 월간 리포트 확인 후 정리한다.
    plan_key = f"qa_{int(time.time())}_{rnd(4)}"
    r = sess.post(f"{BASE}/api/training-log", json={
        "log_date": today,
        "stroke_type": "자유형",
        "pool_length": 25,
        "total_distance": 1200,
        "duration_minutes": 45,
        "intensity": "보통",
        "memo": "QA 리포트 연동 @1:30",
        "plan_completion": {"plan_key": plan_key, "week_index": int(time.strftime("%W")), "day_label": "QA"},
        "sets": [
            {"phase": "warmup", "description": "QA report warmup", "target_reps": 1,
             "target_distance_m": 200, "completed_reps": 1, "status": "completed"},
            {"phase": "main", "description": "QA report main", "target_reps": 10,
             "target_distance_m": 100, "target_cycle_seconds": 90,
             "completed_reps": 10, "status": "completed"},
        ]
    }, timeout=60)
    report_log_id = jget(r).get("id") or jget(r).get("log_id")
    report_set_save = sess.get(
        f"{BASE}/api/training-log/{report_log_id}/sets", timeout=60
    ) if report_log_id else None
    if report_log_id:
        cleanup_ids.append(report_log_id)
    rec("11b", "리포트 연동용 플랜 완료 일지 작성", r.status_code in (200, 201) and bool(report_log_id),
        f"{r.status_code}, id={report_log_id}, plan_key={plan_key}")

    goal_distance = max(baseline_distance + 2200, 2200)
    r = sess.post(f"{BASE}/api/training-log/goal", json={
        "year": year, "month": month, "goal_distance": goal_distance
    }, timeout=60)
    rg = sess.get(month_url("/api/training-log/goal", year, month), timeout=60)
    goal_data = jget(rg)
    rec("11c", "월간 목표 저장/조회", r.status_code == 200 and rg.status_code == 200 and to_int(goal_data.get("goal_distance")) == goal_distance,
        f"save {r.status_code}, get {rg.status_code}, goal={goal_data.get('goal_distance')}")

    benchmark_distance = 25 * random.randint(101, 180)
    benchmark_base = {
        "test_date": today, "stroke_type": "자유형", "distance_m": benchmark_distance,
        "pool_length": 25, "training_log_id": report_log_id, "notes": "QA 테스트 세트",
    }
    benchmark_first = sess.post(f"{BASE}/api/benchmarks", json={**benchmark_base, "duration_ms": 300000}, timeout=60)
    benchmark_first_json = jget(benchmark_first)
    benchmark_second = sess.post(f"{BASE}/api/benchmarks", json={**benchmark_base, "duration_ms": 298000}, timeout=60)
    benchmark_second_json = jget(benchmark_second)
    benchmark_ids = [value for value in [benchmark_first_json.get("id"), benchmark_second_json.get("id")] if value]
    benchmark_list = sess.get(month_url("/api/benchmarks", year, month) + "&limit=100", timeout=60)
    benchmark_list_json = jget(benchmark_list)
    benchmark_invalid = sess.post(f"{BASE}/api/benchmarks", json={
        **benchmark_base, "distance_m": 25, "pool_length": 50, "duration_ms": 30000,
    }, timeout=60)
    benchmark_ok = (
        benchmark_first.status_code == 200 and benchmark_first_json.get("is_personal_best") is True
        and benchmark_second.status_code == 200 and benchmark_second_json.get("is_personal_best") is True
        and to_int(benchmark_second_json.get("improvement_ms")) == 2000
        and benchmark_list.status_code == 200
        and to_int((benchmark_list_json.get("summary") or {}).get("attempts")) >= 2
        and any(to_int(item.get("id")) == to_int(benchmark_second_json.get("id")) for item in benchmark_list_json.get("bests", []))
        and benchmark_invalid.status_code == 400
    )
    rec("11d", "테스트 세트 저장→코스별 PB 판정", benchmark_ok,
        f"first {benchmark_first.status_code}/pb={benchmark_first_json.get('is_personal_best')}, "
        f"second {benchmark_second.status_code}/pb={benchmark_second_json.get('is_personal_best')}/improve={benchmark_second_json.get('improvement_ms')}ms, "
        f"list {benchmark_list.status_code}, invalid {benchmark_invalid.status_code}")

    # ── 12-15. 플랜 ─────────────────────────────────────
    print("\n[12-15] 플랜")
    rr = requests.get(f"{BASE}/plan", timeout=60)
    rec(12, "플랜 페이지", rr.status_code == 200, f"{rr.status_code}")

    # 플랜 생성 (즐겨찾기/공유 테스트용)
    r = sess.post(f"{BASE}/api/plans", json={
        "plan_name": f"QA플랜{rnd(3)}", "goal": "기록단축", "sessions_per_week": 3,
        "session_duration": 60, "focus_stroke": "자유형", "level": "초급",
        "plan_content": {"weeks": []}}, timeout=60)
    plan_id = jget(r).get("id") or jget(r).get("plan_id")
    plan_made = r.status_code in (200, 201) and plan_id

    # 13. 즐겨찾기 토글
    if plan_made:
        r = sess.post(f"{BASE}/api/plans/{plan_id}/favorite", timeout=60)
        rf = sess.get(f"{BASE}/api/plans/favorites", timeout=60)
        rec(13, "플랜 즐겨찾기", r.status_code == 200 and rf.status_code == 200,
            f"toggle {r.status_code}, list {rf.status_code}")
    else:
        rec(13, "플랜 즐겨찾기", False, f"플랜 생성 실패({r.status_code}) → 스킵")

    # 14. 플랜 공유
    if plan_made:
        r = sess.get(f"{BASE}/api/plans/{plan_id}/share", timeout=60)
        rec(14, "플랜 공유 토큰", r.status_code == 200, f"{r.status_code}")
        # 정리: 테스트로 만든 플랜 삭제 (DB 누적 방지)
        try: sess.delete(f"{BASE}/api/plans/{plan_id}", timeout=60)
        except Exception: pass
    else:
        rec(14, "플랜 공유", False, "플랜 없음 → 스킵")

    # 15. 플랜을 훈련 일지에 추가 (from-plan)
    r = sess.post(f"{BASE}/api/training-log/from-plan", json={
        "plan_name": "QA from-plan", "log_date": today,
        "plan_data": {"total_distance": 1000, "stroke_type": "자유형",
                      "duration_minutes": 40, "intensity": "보통",
                      "sets": [
                          {"phase": "main", "description": "QA from-plan set",
                           "target_reps": 10, "target_distance_m": 100,
                           "target_cycle_seconds": 100, "completed_reps": 10,
                           "status": "completed"}
                      ]}}, timeout=60)
    from_plan_id = jget(r).get("id")
    from_plan_set_save = sess.get(
        f"{BASE}/api/training-log/{from_plan_id}/sets", timeout=60
    ) if from_plan_id else None
    if from_plan_id:
        cleanup_ids.append(from_plan_id)
    rec(15, "플랜→훈련일지 추가", r.status_code in (200, 201) and bool(from_plan_id),
        f"{r.status_code}, id={from_plan_id}")

    # ── 16. 리포트/대시보드 ─────────────────────────────
    print("\n[16-18] 리포트/대시보드 연동")
    expected_added_distance = (1200 if report_log_id else 0) + (1000 if from_plan_id else 0)
    expected_added_count = (1 if report_log_id else 0) + (1 if from_plan_id else 0)

    rs = sess.get(month_url("/api/training-log/stats", year, month), timeout=60)
    stats = jget(rs)
    stats_ok = (
        rs.status_code == 200
        and to_int(stats.get("total_distance")) >= baseline_distance + expected_added_distance
        and to_int(stats.get("count")) >= baseline_count + expected_added_count
        and "avg_distance" in stats
    )
    rec(16, "훈련 일지 월간 통계 반영", stats_ok,
        f"{rs.status_code}, total={stats.get('total_distance')}, count={stats.get('count')}, avg={stats.get('avg_distance')}")

    r = sess.get(month_url("/api/report/monthly", year, month), timeout=60)
    report = jget(r)
    perf = report.get("plan_performance") or {}
    benchmark_perf = report.get("benchmark_performance") or {}
    report_ok = (
        r.status_code == 200
        and to_int(report.get("total_distance")) >= baseline_distance + expected_added_distance
        and to_int(report.get("total_count")) >= baseline_count + expected_added_count
        and to_int(report.get("avg_distance")) > 0
        and to_int(perf.get("goal_distance")) == goal_distance
        and to_int(perf.get("completed_sessions")) >= baseline_plan_completed + (1 if report_log_id else 0)
        and to_int(perf.get("plan_distance")) >= baseline_plan_distance + (1200 if report_log_id else 0)
        and to_int(perf.get("planned_sets")) >= baseline_planned_sets + 3
        and to_int(perf.get("completed_sets")) >= baseline_completed_sets + 3
        and to_int(perf.get("set_completion_rate")) > 0
        and bool(report_set_save) and report_set_save.status_code == 200
        and bool(from_plan_set_save) and from_plan_set_save.status_code == 200
        and to_int(benchmark_perf.get("attempts")) >= 2
        and to_int(benchmark_perf.get("personal_bests")) >= 2
    )
    rec(17, "월간 리포트↔훈련 일지 데이터 연동", report_ok,
        f"{r.status_code}, total={report.get('total_distance')}, count={report.get('total_count')}, "
        f"avg={report.get('avg_distance')}, goal={perf.get('goal_distance')}, plan_sessions={perf.get('completed_sessions')}, "
        f"tests={benchmark_perf.get('attempts')}/pb={benchmark_perf.get('personal_bests')}")

    result_share = sess.post(f"{BASE}/api/promotion/result-shares/monthly", json={
        "year": year, "month": month, "show_nickname": False,
    }, timeout=60)
    result_share_json = jget(result_share)
    result_token = result_share_json.get("token")
    public_result = requests.get(
        f"{BASE}/api/promotion/public/results/{result_token}", timeout=60,
    ) if result_token else None
    my_result_shares = sess.get(f"{BASE}/api/promotion/result-shares/mine", timeout=60)
    revoke_result = sess.delete(
        f"{BASE}/api/promotion/result-shares/{result_token}", timeout=60,
    ) if result_token else None
    revoked_public = requests.get(
        f"{BASE}/api/promotion/public/results/{result_token}", timeout=60,
    ) if result_token else None
    public_result_json = jget(public_result)
    result_share_ok = (
        result_share.status_code == 200 and bool(result_token)
        and public_result is not None and public_result.status_code == 200
        and public_result_json.get("display_name") is None
        and to_int((public_result_json.get("result") or {}).get("total_distance")) >= baseline_distance + expected_added_distance
        and "location" not in json.dumps(public_result_json, ensure_ascii=False).lower()
        and my_result_shares.status_code == 200
        and revoke_result is not None and revoke_result.status_code == 200
        and revoked_public is not None and revoked_public.status_code == 410
    )
    rec("17b", "개인정보 선택형 월간 결과 카드 생성·공개·폐기", result_share_ok,
        f"create {result_share.status_code}, public {status_code(public_result)}, "
        f"mine {my_result_shares.status_code}, revoke {status_code(revoke_result)}, after {status_code(revoked_public)}")

    my_data_res = sess.get(f"{BASE}/api/account/insights", timeout=60)
    my_data = jget(my_data_res)
    my_lifetime = my_data.get("lifetime") or {}
    my_habits = my_data.get("recording_habits") or {}
    my_data_ok = (
        my_data_res.status_code == 200
        and my_data.get("privacy_scope") == "authenticated_customer_only"
        and my_data.get("has_data") is True
        and len(my_data.get("monthly_trend") or []) == 12
        and bool(my_data.get("stroke_distribution"))
        and bool(my_data.get("pool_distribution"))
        and bool(my_data.get("insight_cards"))
        and to_int(my_lifetime.get("total_distance")) >= baseline_lifetime_distance + expected_added_distance
        and to_int(my_lifetime.get("total_sessions")) >= baseline_lifetime_sessions + expected_added_count
        and to_int(my_habits.get("structured_sessions")) >= baseline_structured_sessions + expected_added_count
        and to_int(my_habits.get("test_attempts")) >= baseline_test_attempts + 2
        and len(my_data.get("personal_bests") or []) > 0
    )
    rec("17c", "내 수영 데이터 장기 대시보드 연동", my_data_ok,
        f"{my_data_res.status_code}, lifetime={my_lifetime.get('total_distance')}/{my_lifetime.get('total_sessions')}, "
        f"months={len(my_data.get('monthly_trend') or [])}, structured={my_habits.get('structured_sessions')}, "
        f"tests={my_habits.get('test_attempts')}, pb={len(my_data.get('personal_bests') or [])}")

    benchmark_cleanup = []
    for benchmark_id in benchmark_ids:
        benchmark_cleanup.append(sess.delete(f"{BASE}/api/benchmarks/{benchmark_id}", timeout=60).status_code)
    benchmark_after = sess.get(month_url("/api/benchmarks", year, month) + "&limit=100", timeout=60)
    remaining_ids = {to_int(item.get("id")) for item in jget(benchmark_after).get("results", [])}
    benchmark_cleanup_ok = bool(benchmark_ids) and all(code == 200 for code in benchmark_cleanup) and not any(to_int(value) in remaining_ids for value in benchmark_ids)
    rec("17a", "테스트 세트 QA 데이터 정리", benchmark_cleanup_ok,
        f"delete={benchmark_cleanup}, remaining-own={sum(1 for value in benchmark_ids if to_int(value) in remaining_ids)}")

    summary = sess.get(f"{BASE}/api/dashboard/summary", timeout=60)
    weekly = sess.get(f"{BASE}/api/dashboard/weekly", timeout=60)
    advisor = sess.get(f"{BASE}/api/dashboard/training-advisor", timeout=60)
    advisor_json = jget(advisor)
    dashboard_ok = (
        summary.status_code == 200
        and weekly.status_code == 200
        and advisor.status_code == 200
        and bool(advisor_json.get("focus"))
        and bool(advisor_json.get("recommended_session"))
        and "preferred_pool_length" in advisor_json
        and isinstance(advisor_json.get("actions"), list)
    )
    rec(18, "대시보드 주간 목표/훈련 어드바이저", dashboard_ok,
        f"summary {summary.status_code}, weekly {weekly.status_code}, advisor {advisor.status_code}, focus={advisor_json.get('focus')}")

    readiness_before_res = sess.get(f"{BASE}/api/dashboard/readiness", timeout=60)
    readiness_before = jget(readiness_before_res).get("today") if readiness_before_res.status_code == 200 else None
    readiness_save = sess.post(f"{BASE}/api/dashboard/readiness", json={
        "sleep_quality": 2,
        "fatigue": 5,
        "muscle_soreness": 4,
        "available_minutes": 30,
        "note": "QA 회복 우선 추천 검증",
    }, timeout=60)
    readiness_get = sess.get(f"{BASE}/api/dashboard/readiness", timeout=60)
    readiness_advisor = sess.get(f"{BASE}/api/dashboard/training-advisor", timeout=60)
    readiness_json = jget(readiness_get)
    readiness_today = readiness_json.get("today") or {}
    readiness_advisor_json = jget(readiness_advisor)
    readiness_ok = (
        readiness_save.status_code == 200
        and readiness_get.status_code == 200
        and readiness_advisor.status_code == 200
        and to_int(readiness_today.get("score"), 100) < 50
        and readiness_today.get("status") == "회복 우선"
        and readiness_advisor_json.get("readiness_applied") is True
        and (readiness_advisor_json.get("readiness") or {}).get("score") == readiness_today.get("score")
        and readiness_advisor_json.get("recommended_intensity") == "쉬움"
    )
    rec("18a", "준비도 체크인→훈련 추천 연동", readiness_ok,
        f"save {readiness_save.status_code}, get {readiness_get.status_code}/score={readiness_today.get('score')}, "
        f"advisor {readiness_advisor.status_code}/focus={readiness_advisor_json.get('focus')}")

    # 코치 코드 기반 단체 강습 운영: 즉시 등록→학생 코드 연동→템플릿 생성→선택 배포→익명 브리핑
    coach_register = sess.post(f"{BASE}/api/coach/register", json={
        "specialty": "QA 단체 강습", "career": "자동 QA", "intro": "코치 운영 QA 계정",
    }, timeout=60)
    coach_profile_res = sess.get(f"{BASE}/api/coach/me", timeout=60)
    coach_profile = jget(coach_profile_res)
    verification_status = coach_profile.get("verification_status")
    invite_code = coach_profile.get("invite_code")
    coach_registration_ok = (
        coach_register.status_code == 200
        and coach_profile_res.status_code == 200
        and coach_profile.get("is_coach") is True
        and verification_status in ("unverified", "pending", "verified", "rejected")
        and isinstance(invite_code, str) and invite_code.startswith("SWIM-")
    )
    rec("18d", "코치 등록→코드 즉시 발급", coach_registration_ok,
        f"register {coach_register.status_code}, verification={verification_status}, code={invite_code}")

    student_sess = requests.Session()
    student_username = os.environ["QA_STUDENT_USERNAME"]
    student_password = os.environ["QA_STUDENT_PASSWORD"]
    student_email = os.environ["QA_STUDENT_EMAIL"]
    student_sess.post(f"{BASE}/auth/register", json={
        "name": "QA수강생", "email": student_email,
        "username": student_username, "password": student_password,
    }, timeout=60)
    student_login = student_sess.post(f"{BASE}/auth/login", json={"username": student_username, "password": student_password}, timeout=60)
    join_res = student_sess.post(f"{BASE}/api/coach/join", json={"invite_code": invite_code}, timeout=60) if invite_code else None
    coach_profile = jget(sess.get(f"{BASE}/api/coach/me", timeout=60))
    qa_student = next((s for s in coach_profile.get("students", []) if s.get("username") == student_username), None)

    generated = sess.post(f"{BASE}/api/coach/ai/documents/generate", json={
        "document_type": "lesson_schedule", "title": "QA 2주 단체 강습 일정", "audience_label": "QA 혼합반",
        "objective": "자유형 호흡과 레인 질서", "level": "혼합", "pool_length": 25,
        "duration_minutes": 60, "participant_count": 8, "start_date": today, "weeks": 2,
        "sessions_per_week": 2, "equipment": ["킥판"], "constraints": "2개 레인",
        "generation_mode": "template",
    }, timeout=60)
    generated_json = jget(generated)
    document = generated_json.get("document") or {}
    document_id = document.get("id")
    publish = None
    received = None
    insight = None
    insight_id = None
    if document_id and qa_student:
        publish = sess.post(
            f"{BASE}/api/coach/ai/documents/{document_id}/publish",
            json={"all_students": False, "student_ids": [qa_student.get("student_id")]}, timeout=60,
        )
        received = student_sess.get(f"{BASE}/api/coach/class-documents", timeout=60)
        insight = sess.post(f"{BASE}/api/coach/ai/class-insight", json={
            "generation_mode": "template", "coaching_question": "QA 반 편성 점검",
        }, timeout=60)
        insight_id = jget(insight).get("insight_id") if insight else None
    received_ids = {item.get("id") for item in (jget(received).get("documents", []) if received else [])}
    coach_ai_ok = (
        student_login.status_code == 200
        and join_res is not None and join_res.status_code == 200
        and generated.status_code == 200 and document.get("generation_source") == "template"
        and len((document.get("content") or {}).get("sessions", [])) == 4
        and publish is not None and publish.status_code == 200
        and received is not None and received.status_code == 200 and document_id in received_ids
        and insight is not None and insight.status_code == 200
        and isinstance(jget(insight).get("roster_map"), list)
    )
    rec("18e", "코드 연동→AI 강습안 생성·선택 배포·익명 브리핑", coach_ai_ok,
        f"student_login {student_login.status_code}, join {join_res.status_code if join_res else '-'}, "
        f"generate {generated.status_code}/sessions={len((document.get('content') or {}).get('sessions', []))}, "
        f"publish {publish.status_code if publish else '-'}, receive {received.status_code if received else '-'}, "
        f"insight {insight.status_code if insight else '-'}")
    if insight_id:
        sess.delete(f"{BASE}/api/coach/ai/insights/{insight_id}", timeout=60)
    if document_id:
        sess.delete(f"{BASE}/api/coach/ai/documents/{document_id}", timeout=60)
    disconnect = student_sess.delete(f"{BASE}/api/coach/my-coach", timeout=60)
    disconnected_profile = jget(student_sess.get(f"{BASE}/api/coach/my-coach", timeout=60))
    rec("18f", "학생의 코치 연동 직접 해제", disconnect.status_code == 200 and disconnected_profile.get("has_coach") is False,
        f"disconnect {disconnect.status_code}, has_coach={disconnected_profile.get('has_coach')}")

    club_res = sess.post(f"{BASE}/api/clubs", json={
        "name": f"QA 마스터즈 {rnd(4)}", "description": "자동 QA 클럽", "default_pool_length": 25,
    }, timeout=60)
    club_json = jget(club_res)
    club_id = club_json.get("id")
    class_res = None
    join_class_res = None
    student_clubs = None
    club_detail = None
    forbidden_create = None
    forbidden_staff = None
    class_id = None
    invite_code = None
    student_member = None
    if club_id:
        class_res = sess.post(f"{BASE}/api/clubs/{club_id}/classes", json={
            "name": "QA 화목 중급반", "level": "중급", "goal": "자유형 자세 교정",
            "pool_length": 25, "max_members": 20,
        }, timeout=60)
        class_json = jget(class_res)
        class_id = class_json.get("id")
        invite_code = class_json.get("invite_code")
        if class_id and invite_code:
            join_class_res = student_sess.post(f"{BASE}/api/clubs/classes/join", json={
                "invite_code": invite_code,
            }, timeout=60)
            student_clubs = student_sess.get(f"{BASE}/api/clubs/mine", timeout=60)
            club_detail = sess.get(f"{BASE}/api/clubs/{club_id}", timeout=60)
            forbidden_create = student_sess.post(f"{BASE}/api/clubs/{club_id}/classes", json={
                "name": "권한 없는 반", "level": "혼합", "pool_length": 25, "max_members": 10,
            }, timeout=60)
            student_member = next(
                (item for item in jget(club_detail).get("members", []) if item.get("username") == student_username),
                None,
            )
            if student_member and not student_member.get("is_registered_coach"):
                forbidden_staff = sess.put(
                    f"{BASE}/api/clubs/{club_id}/members/{student_member.get('customer_id')}/role",
                    json={"role": "assistant"}, timeout=60,
                )
    student_club_ids = {item.get("id") for item in (jget(student_clubs).get("clubs", []) if student_clubs else [])}
    club_flow_ok = (
        club_res.status_code == 200 and class_res is not None and class_res.status_code == 200
        and join_class_res is not None and join_class_res.status_code == 200
        and student_clubs is not None and student_clubs.status_code == 200 and club_id in student_club_ids
        and club_detail is not None and club_detail.status_code == 200
        and len(jget(club_detail).get("members", [])) >= 2
        and forbidden_create is not None and forbidden_create.status_code == 403
        and forbidden_staff is not None and forbidden_staff.status_code == 403
    )
    rec("18g", "클럽 생성→반 코드 참여→역할 권한 경계", club_flow_ok,
        f"club {club_res.status_code}, class {status_code(class_res)}, "
        f"join {status_code(join_class_res)}, mine {status_code(student_clubs)}, "
        f"member-create {status_code(forbidden_create)}, "
        f"staff-role {status_code(forbidden_staff)}")

    session_res = sessions_res = attendance_save = attendance_coach = attendance_student = None
    notice_res = notice_student = notice_read = notice_after = None
    forbidden_session = forbidden_notice = cleanup_club = None
    if club_id and class_id and student_member:
        session_res = sess.post(f"{BASE}/api/clubs/{club_id}/classes/{class_id}/sessions", json={
            "title": "QA 정규 강습", "session_date": time.strftime("%Y-%m-%d"),
            "start_time": "09:00", "end_time": "10:00", "location": "QA 수영장 1번 레인",
            "lane_count": 1, "training_focus": "자유형 캐치와 페이스 유지",
        }, timeout=60)
        session_id = jget(session_res).get("id")
        sessions_res = sess.get(f"{BASE}/api/clubs/{club_id}/classes/{class_id}/sessions", timeout=60)
        if session_id:
            attendance_save = sess.put(
                f"{BASE}/api/clubs/{club_id}/classes/{class_id}/sessions/{session_id}/attendance",
                json={"records": [{
                    "customer_id": student_member.get("customer_id"),
                    "status": "present", "note": "자동 QA 출석",
                }]}, timeout=60,
            )
            attendance_coach = sess.get(
                f"{BASE}/api/clubs/{club_id}/classes/{class_id}/sessions/{session_id}/attendance", timeout=60,
            )
            attendance_student = student_sess.get(
                f"{BASE}/api/clubs/{club_id}/classes/{class_id}/sessions/{session_id}/attendance", timeout=60,
            )
        notice_res = sess.post(f"{BASE}/api/clubs/{club_id}/notices", json={
            "class_id": class_id, "title": "QA 강습 공지", "content": "준비물과 집합 시간을 확인해주세요.",
            "is_pinned": True,
        }, timeout=60)
        notice_id = jget(notice_res).get("id")
        notice_student = student_sess.get(f"{BASE}/api/clubs/{club_id}/notices?class_id={class_id}", timeout=60)
        if notice_id:
            notice_read = student_sess.post(f"{BASE}/api/clubs/{club_id}/notices/{notice_id}/read", timeout=60)
            notice_after = student_sess.get(f"{BASE}/api/clubs/{club_id}/notices?class_id={class_id}", timeout=60)
        forbidden_session = student_sess.post(
            f"{BASE}/api/clubs/{club_id}/classes/{class_id}/sessions",
            json={"title": "권한 없는 일정", "session_date": time.strftime("%Y-%m-%d"), "start_time": "11:00"},
            timeout=60,
        )
        forbidden_notice = student_sess.post(f"{BASE}/api/clubs/{club_id}/notices", json={
            "class_id": class_id, "title": "권한 없는 공지", "content": "학생은 게시할 수 없습니다.",
        }, timeout=60)

    coach_attendance_items = jget(attendance_coach).get("members", []) if attendance_coach else []
    student_attendance_items = jget(attendance_student).get("members", []) if attendance_student else []
    notices_before = jget(notice_student).get("notices", []) if notice_student else []
    notices_after = jget(notice_after).get("notices", []) if notice_after else []
    operation_flow_ok = (
        session_res is not None and session_res.status_code == 200
        and sessions_res is not None and sessions_res.status_code == 200
        and attendance_save is not None and attendance_save.status_code == 200
        and attendance_coach is not None and attendance_coach.status_code == 200
        and any(item.get("status") == "present" for item in coach_attendance_items)
        and attendance_student is not None and attendance_student.status_code == 200
        and len(student_attendance_items) == 1 and student_attendance_items[0].get("status") == "present"
        and notice_res is not None and notice_res.status_code == 200
        and notice_student is not None and notice_student.status_code == 200
        and any(item.get("id") == jget(notice_res).get("id") and not item.get("is_read") for item in notices_before)
        and notice_read is not None and notice_read.status_code == 200
        and any(item.get("id") == jget(notice_res).get("id") and item.get("is_read") for item in notices_after)
        and forbidden_session is not None and forbidden_session.status_code == 403
        and forbidden_notice is not None and forbidden_notice.status_code == 403
    )
    rec("18h", "반 일정→출석→공지·읽음 권한 경계", operation_flow_ok,
        f"session {status_code(session_res)}, attendance {status_code(attendance_save)}/student={len(student_attendance_items)}, "
        f"notice {status_code(notice_res)}/read={status_code(notice_read)}, "
        f"forbidden {status_code(forbidden_session)}/{status_code(forbidden_notice)}")

    class_analytics = student_analytics = None
    if club_id and class_id:
        class_analytics = sess.get(f"{BASE}/api/clubs/{club_id}/classes/{class_id}/analytics?days=30", timeout=60)
        student_analytics = student_sess.get(
            f"{BASE}/api/clubs/{club_id}/classes/{class_id}/analytics?days=30", timeout=60,
        )
    analytics_json = jget(class_analytics)
    analytics_summary = analytics_json.get("summary") or {}
    analytics_members = analytics_json.get("members") or []
    analytics_student = next(
        (item for item in analytics_members if item.get("customer_id") == (student_member or {}).get("customer_id")),
        None,
    )
    analytics_ok = (
        class_analytics is not None and class_analytics.status_code == 200
        and analytics_summary.get("student_count", 0) >= 1
        and analytics_summary.get("sessions", 0) >= 1
        and analytics_summary.get("attendance_rate") == 100
        and analytics_summary.get("recording_rate") == 100
        and analytics_student is not None and analytics_student.get("attendance_rate") == 100
        and analytics_student.get("training_access") is False
        and analytics_student.get("private_training") is None
        and student_analytics is not None and student_analytics.status_code == 403
        and "코치 코드" in str(analytics_json.get("privacy_note") or "")
    )
    campaign_save = public_campaign = campaign_qr = forbidden_campaign = campaign_consent = None
    if club_id and class_id:
        campaign_consent = student_sess.put(
            f"{BASE}/api/promotion/clubs/{club_id}/campaign/consent",
            json={"include_my_distance": True}, timeout=60,
        )
        campaign_save = sess.put(f"{BASE}/api/promotion/clubs/{club_id}/campaign", json={
            "headline": "QA 수영 클럽 공개 체험",
            "class_id": class_id,
            "target_distance": 100000,
            "start_date": time.strftime("%Y-%m-%d"),
            "end_date": time.strftime("%Y-%m-%d", time.localtime(time.time() + 30 * 86400)),
            "is_public": True,
            "show_member_count": True,
        }, timeout=60)
        campaign_token = (jget(campaign_save).get("campaign") or {}).get("public_token")
        if campaign_token:
            public_campaign = requests.get(
                f"{BASE}/api/promotion/public/clubs/{campaign_token}", timeout=60,
            )
            campaign_qr = requests.get(
                f"{BASE}/api/promotion/public/clubs/{campaign_token}/qr.svg", timeout=60,
            )
        forbidden_campaign = student_sess.put(f"{BASE}/api/promotion/clubs/{club_id}/campaign", json={
            "headline": "권한 없는 공개 변경",
            "class_id": class_id,
            "target_distance": 100000,
            "start_date": time.strftime("%Y-%m-%d"),
            "end_date": time.strftime("%Y-%m-%d", time.localtime(time.time() + 30 * 86400)),
            "is_public": True,
            "show_member_count": True,
        }, timeout=60)
    public_campaign_json = jget(public_campaign)
    campaign_ok = (
        campaign_save is not None and campaign_save.status_code == 200
        and campaign_consent is not None and campaign_consent.status_code == 200
        and public_campaign is not None and public_campaign.status_code == 200
        and (public_campaign_json.get("class") or {}).get("invite_code") == invite_code
        and (public_campaign_json.get("campaign") or {}).get("target_distance") == 100000
        and "members" not in public_campaign_json
        and "직접 동의한 회원" in str(public_campaign_json.get("privacy") or "")
        and campaign_qr is not None and campaign_qr.status_code == 200
        and "image/svg+xml" in campaign_qr.headers.get("Content-Type", "")
        and forbidden_campaign is not None and forbidden_campaign.status_code == 403
    )
    rec("18j", "클럽 공개 소개·공동 목표·반 초대 QR·권한 경계", campaign_ok,
        f"consent {status_code(campaign_consent)}, save {status_code(campaign_save)}, public {status_code(public_campaign)}, "
        f"qr {status_code(campaign_qr)}, student {status_code(forbidden_campaign)}")

    if club_id:
        cleanup_club = sess.delete(f"{BASE}/api/clubs/{club_id}", timeout=60)
    analytics_ok = analytics_ok and cleanup_club is not None and cleanup_club.status_code == 200
    rec("18i", "코치 반 수행·출석 분석과 개인훈련 동의 경계", analytics_ok,
        f"coach {status_code(class_analytics)}, attendance={analytics_summary.get('attendance_rate')}%, "
        f"recording={analytics_summary.get('recording_rate')}%, private={analytics_student.get('training_access') if analytics_student else '-'}, "
        f"student {status_code(student_analytics)}, cleanup {status_code(cleanup_club)}")

    badges_res = sess.get(f"{BASE}/api/badges", timeout=60)
    badges_json = jget(badges_res)
    badge_ids = {b.get("id") for b in badges_json.get("badges", [])}
    badge_ok = (
        badges_res.status_code == 200
        and "first_log" in badge_ids
        and "log_count_5" in badge_ids
        and "plan_runner_1" in badge_ids
        and "monthly_goal_set" in badge_ids
        and "pool_dual" in badge_ids
        and isinstance(badges_json.get("series_groups"), list)
        and isinstance(badges_json.get("next_badges"), list)
        and badges_json.get("total_count", 0) >= 30
    )
    rec("18c", "단계형 뱃지 API", badge_ok,
        f"{badges_res.status_code}, total={badges_json.get('total_count')}, next={len(badges_json.get('next_badges', []))}")

    if admin_sess:
        qa_account_mark = admin_sess.put(
            f"{BASE}/api/admin/qa-accounts",
            json={"usernames": [uname, student_username], "is_qa_account": True},
            timeout=60,
        )
        qa_account_mark_json = jget(qa_account_mark)
        qa_marker_track = requests.post(
            f"{BASE}/api/admin/track",
            params={"page": "/tutorial/help"},
            headers={"X-SwimMate-QA-Run": "1"},
            timeout=60,
        )
        admin_dashboard = admin_sess.get(f"{BASE}/api/admin/dashboard?days=30", timeout=60)
        admin_users = admin_sess.get(f"{BASE}/api/admin/users?page_size=100", timeout=60)
        admin_qa_users = admin_sess.get(f"{BASE}/api/admin/users?account_scope=qa&page_size=100", timeout=60)
        admin_qa_candidates = admin_sess.get(f"{BASE}/api/admin/users?account_scope=candidate&page_size=100", timeout=60)
        admin_users_page2 = admin_sess.get(f"{BASE}/api/admin/users?page=2&page_size=20", timeout=60)
        admin_activity = admin_sess.get(f"{BASE}/api/admin/activity", timeout=60)
        admin_coaches = admin_sess.get(f"{BASE}/api/admin/coaches?status=all&page_size=100", timeout=60)
        admin_coaches_page2 = admin_sess.get(f"{BASE}/api/admin/coaches?status=all&page=2&page_size=20", timeout=60)
        admin_health = admin_sess.get(f"{BASE}/api/admin/training-health", timeout=60)
        admin_logs = admin_sess.get(f"{BASE}/api/admin/logs?account_scope=regular", timeout=60)
        admin_page_view_logs = admin_sess.get(f"{BASE}/api/admin/logs?account_scope=regular&event_type=page_view&page_size=100", timeout=60)
        admin_page_view_logs_page2 = admin_sess.get(f"{BASE}/api/admin/logs?account_scope=regular&event_type=page_view&page=2&page_size=20", timeout=60)
        admin_qa_logs = admin_sess.get(f"{BASE}/api/admin/logs?account_scope=qa&page_size=100", timeout=60)
        admin_qa_page_views = admin_sess.get(f"{BASE}/api/admin/logs?account_scope=qa&event_type=page_view&page_size=20", timeout=60)
        admin_qa_marker_logs = admin_sess.get(
            f"{BASE}/api/admin/logs",
            params={
                "account_scope": "qa", "event_type": "page_view", "search_by": "path",
                "q": "/tutorial/help", "page": 1, "page_size": 100,
            },
            timeout=60,
        )
        admin_feedback = admin_sess.get(f"{BASE}/api/feedback?page_size=20", timeout=60)
        admin_feedback_page2 = admin_sess.get(f"{BASE}/api/feedback?page=2&page_size=20", timeout=60)
        search_marker = "qa-admin-search-no-match-7f3a"
        admin_users_search = admin_sess.get(
            f"{BASE}/api/admin/users",
            params={"search_by": "username", "q": search_marker, "page": 1, "page_size": 20},
            timeout=60,
        )
        admin_coaches_search = admin_sess.get(
            f"{BASE}/api/admin/coaches",
            params={"status": "all", "search_by": "specialty", "q": search_marker, "page": 1, "page_size": 20},
            timeout=60,
        )
        admin_logs_search = admin_sess.get(
            f"{BASE}/api/admin/logs",
            params={"search_by": "path", "q": search_marker, "page": 1, "page_size": 20},
            timeout=60,
        )
        admin_feedback_search = admin_sess.get(
            f"{BASE}/api/feedback",
            params={"search_by": "title", "q": search_marker, "page": 1, "page_size": 20},
            timeout=60,
        )
        dashboard_json = jget(admin_dashboard)
        users_json = jget(admin_users)
        qa_users_json = jget(admin_qa_users)
        qa_candidates_json = jget(admin_qa_candidates)
        users_page2_json = jget(admin_users_page2)
        coaches_json = jget(admin_coaches)
        coaches_page2_json = jget(admin_coaches_page2)
        health_json = jget(admin_health)
        health_summary = health_json.get("summary") or {}
        logs_json = jget(admin_page_view_logs)
        logs_page2_json = jget(admin_page_view_logs_page2)
        qa_logs_json = jget(admin_qa_logs)
        qa_page_views_json = jget(admin_qa_page_views)
        qa_marker_logs_json = jget(admin_qa_marker_logs)
        feedback_json = jget(admin_feedback)
        feedback_page2_json = jget(admin_feedback_page2)
        feedback_items = feedback_json.get("items") or []
        feedback_author_ok = (
            admin_feedback.status_code == 200
            and isinstance(feedback_items, list)
            and (not feedback_items or "author_display" in feedback_items[0])
        )
        traffic_trend = dashboard_json.get("traffic_trend") or []
        traffic_summary = dashboard_json.get("traffic_summary") or {}
        admin_chart_ok = (
            dashboard_json.get("chart_days") == 30
            and len(traffic_trend) == 30
            and all(
                key in traffic_summary
                for key in ("page_views", "visitors", "active_users", "signups")
            )
            and all(
                key in traffic_trend[0]
                for key in ("date", "page_views", "visitors", "active_users", "signups")
            )
        )
        search_responses = [
            (admin_users_search, "username"),
            (admin_coaches_search, "specialty"),
            (admin_logs_search, "path"),
            (admin_feedback_search, "title"),
        ]
        admin_search_ok = all(
            response.status_code == 200
            and jget(response).get("search_by") == category
            and jget(response).get("q") == search_marker
            and jget(response).get("total") == 0
            for response, category in search_responses
        )
        admin_paging_ok = (
            admin_users.status_code == 200
            and users_json.get("page_size") == 100
            and admin_users_page2.status_code == 200
            and users_page2_json.get("page") == 2
            and admin_coaches.status_code == 200
            and coaches_json.get("page_size") == 100
            and admin_coaches_page2.status_code == 200
            and coaches_page2_json.get("page") == 2
            and "documents_30d" in (coaches_json.get("summary") or {})
            and admin_page_view_logs.status_code == 200
            and logs_json.get("page_size") == 100
            and logs_json.get("page") == 1
            and "total" in logs_json
            and admin_page_view_logs_page2.status_code == 200
            and logs_page2_json.get("page") == 2
            and feedback_json.get("page_size") == 20
            and admin_feedback_page2.status_code == 200
            and feedback_page2_json.get("page") == 2
        )
        marked_usernames = {
            item.get("username") for item in qa_account_mark_json.get("updated", [])
        }
        qa_log_split_ok = (
            qa_account_mark.status_code == 200
            and {uname, student_username}.issubset(marked_usernames)
            and not qa_account_mark_json.get("missing")
            and admin_logs.status_code == 200
            and jget(admin_logs).get("account_scope") == "regular"
            and all(not item.get("is_qa_account") for item in jget(admin_logs).get("logs", []))
            and admin_qa_logs.status_code == 200
            and qa_logs_json.get("account_scope") == "qa"
            and qa_logs_json.get("total", 0) > 0
            and all(item.get("is_qa_account") for item in qa_logs_json.get("logs", []))
            and (qa_logs_json.get("scope_summary") or {}).get("qa_account_count", 0) >= 2
            and admin_qa_page_views.status_code == 200
            and qa_page_views_json.get("event_type") == "page_view"
            and all(
                item.get("is_qa_account") and item.get("event_type") == "page_view"
                for item in qa_page_views_json.get("logs", [])
            )
            and qa_marker_track.status_code == 200
            and admin_qa_marker_logs.status_code == 200
            and any(
                (item.get("metadata") or {}).get("qa_automation") is True
                for item in qa_marker_logs_json.get("logs", [])
            )
            and admin_qa_users.status_code == 200
            and qa_users_json.get("account_scope") == "qa"
            and all(item.get("is_qa_account") for item in qa_users_json.get("users", []))
            and all("qa_evidence" in item for item in qa_users_json.get("users", []))
            and admin_qa_candidates.status_code == 200
            and qa_candidates_json.get("account_scope") == "candidate"
            and all(
                not item.get("is_qa_account") and (item.get("qa_evidence") or {}).get("is_candidate")
                for item in qa_candidates_json.get("users", [])
            )
        )
        admin_ok = (
            admin_dashboard.status_code == 200
            and admin_users.status_code == 200
            and admin_activity.status_code == 200
            and admin_coaches.status_code == 200
            and admin_health.status_code == 200
            and admin_logs.status_code == 200
            and admin_page_view_logs.status_code == 200
            and admin_paging_ok
            and feedback_author_ok
            and admin_chart_ok
            and admin_search_ok
            and qa_log_split_ok
            and "logs_30d" in health_summary
            and "plan_completions_30d" in health_summary
            and "readiness_checkins_7d" in health_summary
            and "readiness_avg_score_7d" in health_summary
            and "active_clubs" in health_summary
            and "active_classes" in health_summary
            and "class_sessions_30d" in health_summary
            and "attendance_rate_30d" in health_summary
            and "active_notices" in health_summary
            and "test_results_30d" in health_summary
            and "test_users_30d" in health_summary
            and "personal_bests_30d" in health_summary
            and "screenshot_imports_30d" in health_summary
            and "screenshot_import_users_30d" in health_summary
            and "result_shares_30d" in health_summary
            and "result_share_views_30d" in health_summary
            and "public_club_campaigns" in health_summary
            and "club_campaign_views" in health_summary
            and isinstance(health_json.get("watchlist"), list)
        )
        rec("18b", "관리자 훈련 운영 API", admin_ok,
            f"dashboard {admin_dashboard.status_code}, activity {admin_activity.status_code}, "
            f"coaches {admin_coaches.status_code}/total={coaches_json.get('total')}/page2={coaches_page2_json.get('page')}, "
            f"training-health {admin_health.status_code}, logs {admin_logs.status_code}, "
            f"qa-log-split={qa_log_split_ok}/qa_total={qa_logs_json.get('total')}/qa_views={qa_page_views_json.get('total')}, "
            f"users {admin_users.status_code}/page_size={users_json.get('page_size')}/page2={users_page2_json.get('page')}, "
            f"page_view_logs {admin_page_view_logs.status_code}/page_size={logs_json.get('page_size')}/page2={logs_page2_json.get('page')}, "
            f"feedback {admin_feedback.status_code}/author={feedback_author_ok}/page_size={feedback_json.get('page_size')}/page2={feedback_page2_json.get('page')}, "
            f"category_search={admin_search_ok}, traffic_chart={admin_chart_ok}/{len(traffic_trend)}일, "
            f"logs_30d={health_summary.get('logs_30d')}, plan_completions={health_summary.get('plan_completions_30d')}, "
            f"readiness={health_summary.get('readiness_checkins_7d')}/{health_summary.get('readiness_avg_score_7d')}점, "
            f"clubs={health_summary.get('active_clubs')}/classes={health_summary.get('active_classes')}/"
            f"attendance={health_summary.get('attendance_rate_30d')}%, "
            f"tests={health_summary.get('test_results_30d')}/pb={health_summary.get('personal_bests_30d')}, "
            f"screenshots={health_summary.get('screenshot_imports_30d')}/users={health_summary.get('screenshot_import_users_30d')}, "
            f"shares={health_summary.get('result_shares_30d')}/campaigns={health_summary.get('public_club_campaigns')}")

    # ── 19. 모바일(정적이라 동일) — User-Agent만 모바일로 ─
    print("\n[19] 모바일 응답")
    rr = requests.get(f"{BASE}/landing", timeout=60,
                      headers={"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)"})
    rec(19, "모바일 UA 랜딩 응답", rr.status_code == 200,
        f"{rr.status_code} (반응형은 정적이라 200이면 동일 자산 서빙)")

    cleanup_ok, cleanup_detail = cleanup_logs(sess, cleanup_ids)
    rec("C", "QA 생성 일지 정리", cleanup_ok, cleanup_detail or "정리할 일지 없음")
    goal_cleanup = sess.post(f"{BASE}/api/training-log/goal", json={
        "year": year,
        "month": month,
        "goal_distance": baseline_goal_distance,
    }, timeout=60)
    rec("C1", "QA 월간 목표 복원", goal_cleanup.status_code == 200,
        f"{goal_cleanup.status_code}, goal={baseline_goal_distance}")
    if readiness_before:
        readiness_cleanup = sess.post(f"{BASE}/api/dashboard/readiness", json={
            "sleep_quality": readiness_before.get("sleep_quality"),
            "fatigue": readiness_before.get("fatigue"),
            "muscle_soreness": readiness_before.get("muscle_soreness"),
            "available_minutes": readiness_before.get("available_minutes"),
            "note": readiness_before.get("note"),
        }, timeout=60)
    else:
        readiness_cleanup = sess.delete(f"{BASE}/api/dashboard/readiness", timeout=60)
    rec("C2", "QA 준비도 체크인 복원", readiness_cleanup.status_code == 200,
        f"{readiness_cleanup.status_code}, {'기존 값 복원' if readiness_before else '테스트 값 삭제'}")

    # ── 결과 요약 ───────────────────────────────────────
    print("\n" + "="*60)
    p = sum(1 for x in RESULTS if x[2] == "PASS")
    f = sum(1 for x in RESULTS if x[2] == "FAIL")
    print(f"  결과: PASS {p}  /  FAIL {f}  /  총 {len(RESULTS)}")
    print("="*60)
    if f:
        print("  ❌ 실패 항목:")
        for no, name, st, det in RESULTS:
            if st == "FAIL":
                print(f"     [{no}] {name}  → {det}")
    # JSON 리포트도 저장
    with open("qa_report.json", "w", encoding="utf-8") as fp:
        json.dump([{"no": str(n), "name": nm, "status": st, "detail": d}
                   for n, nm, st, d in RESULTS], fp, ensure_ascii=False, indent=2)
    print("\n  → qa_report.json 저장됨")
    sys.exit(1 if f else 0)

if __name__ == "__main__":
    main()
