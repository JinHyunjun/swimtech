#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SwimTech 자동 QA 검증 스크립트 (API 레벨)
─────────────────────────────────────────────────────────
하는 일:
  1) 관리자 슈퍼계정 확인/생성 (ADMIN_ID 로 가입 시도 → 이미 있으면 로그인)
  2) QA용 임시 계정 자동 개설 (qa_<타임스탬프>)
  3) 핵심 API 시나리오 순차 검증 → PASS/FAIL 표 + 종료코드

검증 대상: https://swimtech.vercel.app  (실제 Vercel→Render 프록시 경로)
쿠키 기반 인증을 requests.Session 으로 그대로 따라감.

사용법:
  pip install requests
  # 관리자 계정 생성까지 하려면 (Render에 넣은 값과 동일하게):
  set ADMIN_ID=...        (PowerShell:  $env:ADMIN_ID="..." )
  set ADMIN_PW=...
  python qa_runner.py
  # 옵션:
  python qa_runner.py --base https://swimtech.vercel.app
  python qa_runner.py --no-admin     (관리자 생성 건너뛰기)
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

def make_fallback_account(sess):
    username = f"qa{int(time.time()) % 100000000}{rnd(4)}"
    password = os.getenv("QA_FALLBACK_PASSWORD", "QaTest1234")
    email = f"{username}@example.com"
    reg = sess.post(f"{BASE}/auth/register", json={
        "name": "QA임시봇",
        "email": email,
        "username": username,
        "password": password,
    }, timeout=60)
    login = sess.post(f"{BASE}/auth/login", json={"username": username, "password": password}, timeout=60)
    return username, password, email, reg, login

# ─────────────────────────────────────────────────────────
def main():
    global BASE
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=BASE)
    ap.add_argument("--no-admin", action="store_true")
    args = ap.parse_args()
    BASE = args.base.rstrip("/")
    print(f"\n=== SwimTech QA 검증 시작 ===\n대상: {BASE}\n")

    # ── 0. 배포/기본 접속 확인 ──────────────────────────
    print("[0] 배포/기본 접속")
    try:
        r = requests.get(f"{BASE}/api/health", timeout=90)  # 콜드스타트 대비 90s
        rec(0, "백엔드 health (콜드스타트 깨우기)", r.status_code == 200, f"{r.status_code}")
    except Exception as e:
        rec(0, "백엔드 health", False, str(e)[:60])

    admin_sess = None

    # ── 관리자 슈퍼계정 확인/생성 ───────────────────────
    if not args.no_admin:
        admin_id, admin_pw = os.getenv("ADMIN_ID"), os.getenv("ADMIN_PW")
        if admin_id and admin_pw:
            s = requests.Session()
            reg = s.post(f"{BASE}/auth/register", json={
                "name": "관리자", "email": f"{admin_id}@swimtech.local",
                "username": admin_id, "password": admin_pw}, timeout=60)
            login = s.post(f"{BASE}/auth/login",
                           json={"username": admin_id, "password": admin_pw}, timeout=60)
            ok = login.status_code == 200
            if ok:
                admin_sess = s
            note = "신규 생성" if reg.status_code == 200 else "이미 존재"
            rec("A", f"관리자 슈퍼계정 ({admin_id})", ok, f"{note}, 로그인 {login.status_code}")
        else:
            print("  ⚠ 관리자 API QA 생략: ADMIN_ID/ADMIN_PW 환경변수 없음")

    # ── QA 계정 + 세션 준비 ─────────────────────────────
    sess = requests.Session()
    # 고정 QA 계정 재사용 (DB에 계정이 쌓이지 않도록). cron 반복 안전.
    uname = os.getenv("QA_USERNAME", "qabot")
    pw    = os.getenv("QA_PASSWORD", "QaTest1234")
    email = os.getenv("QA_EMAIL", "qabot@example.com")

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
    logged_in = r.status_code == 200
    has_cookie = "swimtech_token" in sess.cookies.get_dict()
    if not logged_in:
        original_status = r.status_code
        fallback_sess = requests.Session()
        fb_uname, fb_pw, fb_email, fb_reg, fb_login = make_fallback_account(fallback_sess)
        if fb_login.status_code == 200:
            sess = fallback_sess
            uname, pw, email = fb_uname, fb_pw, fb_email
            r = fb_login
            logged_in = True
            has_cookie = "swimtech_token" in sess.cookies.get_dict()
            print(f"  ⚠ 기본 QA 계정 로그인 실패({original_status}) → 임시 계정으로 전환: {uname}")
        else:
            print(f"  ⚠ 임시 QA 계정 생성/로그인 실패: register {fb_reg.status_code}, login {fb_login.status_code}")
    rec(2, "일반 로그인 (+쿠키 발급)", logged_in and has_cookie,
        f"status {r.status_code}, 쿠키 {'있음' if has_cookie else '없음'}")

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

    year, month = this_month()
    baseline_stats = {}
    baseline_report = {}
    try:
        baseline_stats = jget(sess.get(month_url("/api/training-log/stats", year, month), timeout=60))
        baseline_report = jget(sess.get(month_url("/api/report/monthly", year, month), timeout=60))
    except Exception:
        pass
    baseline_distance = max(to_int(baseline_report.get("total_distance")), to_int(baseline_stats.get("total_distance")))
    baseline_count = max(to_int(baseline_report.get("total_count")), to_int(baseline_stats.get("count")))
    baseline_plan_perf = baseline_report.get("plan_performance") or {}
    baseline_plan_completed = to_int(baseline_plan_perf.get("completed_sessions"))
    baseline_plan_distance = to_int(baseline_plan_perf.get("plan_distance"))
    cleanup_ids = []

    # ── 7. 메인 화면/라우팅 ─────────────────────────────
    print("\n[7-8] 화면/라우팅 (정적 페이지 200 확인)")
    pages = {"/landing": "랜딩", "/dashboard": "대시보드", "/plan": "플랜",
             "/training-log": "훈련일지", "/report": "리포트", "/pool": "수영장",
             "/community": "커뮤니티", "/challenge": "챌린지", "/badges": "뱃지"}
    bad = []
    for path, label in pages.items():
        rr = requests.get(f"{BASE}{path}", timeout=60)
        if rr.status_code != 200: bad.append(f"{label}({rr.status_code})")
    rec(7, "메인/주요 페이지 라우팅", not bad, "전부 200" if not bad else "실패: "+", ".join(bad))

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
    rec(9, "훈련 일지 작성", r.status_code in (200, 201), f"{r.status_code}, id={log_id}")

    r = sess.get(f"{BASE}/api/training-log", timeout=60)
    logs = jget(r)
    found = isinstance(logs, (list, dict))
    rec(10, "훈련 일지 조회", r.status_code == 200 and found, f"{r.status_code}")

    # stats/streak도 같이
    rs = sess.get(month_url("/api/training-log/stats", year, month), timeout=60)
    rk = sess.get(f"{BASE}/api/training-log/streak", timeout=60)
    rec("10b", "일지 통계/연속출석", rs.status_code == 200 and rk.status_code == 200,
        f"stats {rs.status_code}, streak {rk.status_code}")

    # 11. 수정/삭제
    if log_id:
        ru = sess.put(f"{BASE}/api/training-log/{log_id}", json={
            "log_date": today, "stroke_type": "배영", "total_distance": 2000,
            "duration_minutes": 70, "intensity": "힘듦", "memo": "QA 수정"}, timeout=60)
        rd = sess.delete(f"{BASE}/api/training-log/{log_id}", timeout=60)
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
        "plan_completion": {"plan_key": plan_key, "week_index": int(time.strftime("%W")), "day_label": "QA"}
    }, timeout=60)
    report_log_id = jget(r).get("id") or jget(r).get("log_id")
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
                      "duration_minutes": 40, "intensity": "보통"}}, timeout=60)
    from_plan_id = jget(r).get("id")
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
    report_ok = (
        r.status_code == 200
        and to_int(report.get("total_distance")) >= baseline_distance + expected_added_distance
        and to_int(report.get("total_count")) >= baseline_count + expected_added_count
        and to_int(report.get("avg_distance")) > 0
        and to_int(perf.get("goal_distance")) == goal_distance
        and to_int(perf.get("completed_sessions")) >= baseline_plan_completed + (1 if report_log_id else 0)
        and to_int(perf.get("plan_distance")) >= baseline_plan_distance + (1200 if report_log_id else 0)
        and bool(report.get("share_token"))
    )
    rec(17, "월간 리포트↔훈련 일지 데이터 연동", report_ok,
        f"{r.status_code}, total={report.get('total_distance')}, count={report.get('total_count')}, "
        f"avg={report.get('avg_distance')}, goal={perf.get('goal_distance')}, plan_sessions={perf.get('completed_sessions')}")

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

    if admin_sess:
        admin_dashboard = admin_sess.get(f"{BASE}/api/admin/dashboard", timeout=60)
        admin_activity = admin_sess.get(f"{BASE}/api/admin/activity", timeout=60)
        admin_health = admin_sess.get(f"{BASE}/api/admin/training-health", timeout=60)
        admin_logs = admin_sess.get(f"{BASE}/api/admin/logs", timeout=60)
        health_json = jget(admin_health)
        health_summary = health_json.get("summary") or {}
        admin_ok = (
            admin_dashboard.status_code == 200
            and admin_activity.status_code == 200
            and admin_health.status_code == 200
            and admin_logs.status_code == 200
            and "logs_30d" in health_summary
            and "plan_completions_30d" in health_summary
            and isinstance(health_json.get("watchlist"), list)
        )
        rec("18b", "관리자 훈련 운영 API", admin_ok,
            f"dashboard {admin_dashboard.status_code}, activity {admin_activity.status_code}, "
            f"training-health {admin_health.status_code}, logs {admin_logs.status_code}, "
            f"logs_30d={health_summary.get('logs_30d')}, plan_completions={health_summary.get('plan_completions_30d')}")

    # ── 19. 모바일(정적이라 동일) — User-Agent만 모바일로 ─
    print("\n[19] 모바일 응답")
    rr = requests.get(f"{BASE}/landing", timeout=60,
                      headers={"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)"})
    rec(19, "모바일 UA 랜딩 응답", rr.status_code == 200,
        f"{rr.status_code} (반응형은 정적이라 200이면 동일 자산 서빙)")

    cleanup_ok, cleanup_detail = cleanup_logs(sess, cleanup_ids)
    rec("C", "QA 생성 일지 정리", cleanup_ok, cleanup_detail or "정리할 일지 없음")

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
