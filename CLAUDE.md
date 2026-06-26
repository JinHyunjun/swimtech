# SwimTech — Claude Code Guide

## Project Overview

SwimTech is a swimming technique analysis web app. It uses AI/ML to analyze swimmer video, provides coaching via chat, and helps users find nearby pools.

**Stack**: Python (FastAPI backend), HTML/CSS/JS frontend (multi-page), pytest-playwright for E2E tests.

---

## Mandatory Rule: Tests Must Accompany New Features

> **Every new page or API endpoint requires test coverage.**

When you add or modify any of the following, you **must** also add test cases to `tests/test_swimtech.py`:

| What you add | What to test |
|---|---|
| New frontend page (`/newpage`) | Load test + primary interactions |
| New API route (`/api/v1/...`) | Response status + payload shape |
| New UI component (modal, tab, card) | Visibility + interaction |
| Modified selector or element ID | Update existing tests to match |

---

## Verification Workflow

After every feature change, run the test suite from the project root:

```bat
tests\run_tests.bat
```

This will:
1. Run `pytest tests/test_swimtech.py`
2. Save a full HTML report to `tests/report.html`
3. Print a summary of any failed tests to the console

Open `tests/report.html` in a browser for screenshots and detailed failure output.

---

## Adding Tests — Quick Reference

Test file: `tests/test_swimtech.py`

```python
# Minimum test for a new page /example
def test_example_load(page: Page):
    goto(page, "/example")
    expect(page.locator("#main-element")).to_be_visible()
    shot(page, "XX_example_load")

def test_example_interaction(page: Page):
    goto(page, "/example")
    page.click("#action-btn")
    page.wait_for_timeout(500)
    expect(page.locator("#result")).to_be_visible()
    shot(page, "XX_example_action")
```

Screenshots are saved to `tests/screenshots/` automatically.

---

## Project Structure

```
C:\swim\
├── api/                  # FastAPI backend
│   ├── worker.py         # Main app entry + ML inference
│   └── routers/
│       └── customers.py  # User/auth routes
├── analysis/             # ML model training & inference
│   └── train/
├── tests/
│   ├── test_swimtech.py  # E2E test suite (ADD TESTS HERE)
│   ├── run_tests.bat     # One-command test runner
│   ├── conftest.py       # pytest fixtures
│   ├── pytest.ini        # pytest config
│   ├── report.html       # Last test run report
│   └── screenshots/      # Auto-captured test screenshots
├── video/                # Sample swimmer videos
├── CLAUDE.md             # This file
└── README.md
```

---

## Key Conventions

- **Base URL**: `https://localhost` (SSL cert errors are suppressed in tests)
- **Test credentials**: `admin` / `swimtech1234`
- **Selectors**: Use `#id` selectors where possible for stability
- **Screenshots**: Call `shot(page, "NN_pagename_action")` at end of each test
- **Waits**: Use `page.wait_for_timeout(ms)` only when waiting for animations or async API calls; prefer `expect(...).to_be_visible()` otherwise

## ML Model Notes

- Model file: `analysis/pose_landmarker.task`
- Classifies 4 strokes: freestyle, backstroke, breaststroke, butterfly
- Retraining pipeline: see recent commits for automated ML retraining setup

---

## 모든 기능 추가/개선 시 필수 검증 절차

### 1. 구현 완료 후 자동 검증 순서

```powershell
# 1) API·Worker 컨테이너 재생성 (새 코드 반영)
docker compose up -d --force-recreate api worker

# 2) 전체 테스트 실행 + HTML 리포트 생성
pytest tests/test_swimtech.py --html=tests/report.html --self-contained-html

# 3) 새 기능 스크린샷 저장 (Playwright가 자동 저장)
#    경로: tests/screenshots/{페이지명}.png
```

> `tests/report.html`을 브라우저에서 열어 스크린샷과 실패 원인을 확인한다.

### 2. 테스트 케이스 작성 규칙

| 추가 항목 | 필수 테스트 | 최소 개수 |
|---|---|---|
| 새 페이지 (`/newpage`) | `test_{페이지명}_load` + `test_{페이지명}_ui` | 2개 |
| 새 API 엔드포인트 | `test_{기능명}_api` | 1개 |
| 모달 / 인터랙션 | `test_{기능명}_interaction` | 1개 |
| 운영 QA 대상 기능 | `scripts/qa_runner.py` 또는 `scripts/qa_ui_crawler.py` 매핑 갱신 | 1개 |

### 2-1. 운영 QA 스크립트 갱신 규칙

- 새 기능 / 새 화면 / 새 API를 추가하면 반드시 `scripts/qa_runner.py` 또는 `scripts/qa_ui_crawler.py`에 검증 매핑을 추가한다.
- 훈련 일지, 월간 리포트, 대시보드, 플랜, 관리자 화면처럼 서로 연동되는 기능은 단순 200 응답이 아니라 실제 데이터 반영값까지 확인한다.
- 슈퍼계정(`administrator`/`ADMIN_ID`)에서 확인해야 하는 운영 지표가 늘어나면 `/admin` 화면과 관리자 QA 검증도 함께 갱신한다.
- 관리자 QA는 운영 데이터 보호를 위해 읽기 전용 탭/필터/조회 액션만 수행한다.

### 3. Caddyfile 라우트 확인

- 새 페이지를 추가할 때마다 `caddy/Caddyfile`에 `handle` 블록을 추가한다.
- 추가 후 반드시 아래 명령으로 Caddy를 재시작한다.

```powershell
docker compose restart caddy
```

### 4. 스크린샷 증적 규칙

- 저장 위치: `tests/screenshots/`
- 파일명 형식: `{기능명}_{YYYYMMDD}.png`
- `shot(page, "NN_pagename_action")` 호출이 각 테스트의 마지막 줄이어야 한다.

---

## Branch Strategy

### 단일 브랜치 (`main`)

- 모든 작업은 `main`에 직접 진행한다. 별도의 `dev` 브랜치 워크플로우는 더 이상 사용하지 않는다.
- `dev` 브랜치는 2026-06-25에 `main`과 동일한 지점으로 fast-forward 동기화되었고, 그 이후로는 운영하지 않는다(필요 시 같은 지점으로 재동기화만 한다).
- `main`은 실배포 대상이다 — `render.yaml`의 `autoDeploy: true`로 백엔드(Render)가, Vercel이 프론트엔드를 같은 브랜치에서 자동 배포한다. **`main`에 푸시 = 프로덕션 반영**이라는 점을 항상 인지한다.

### AI 분석 기능

- AI 영상 분석 관련 UI는 여전히 비활성화(숨김) 상태다. 더 이상 브랜치로 격리하지 않고, **`main` 안에서 feature-flag/숨김 처리로 관리**한다.
- 숨김 처리된 항목: `onboarding` 슬라이드, `faq` 촬영·분석 탭, `injury` CTA, `landing` 영상 분석 카드
- 이 영역을 다시 활성화하려면 위 항목들의 숨김 처리를 해제하고 정상 동작을 검증한 뒤 `main`에 커밋한다.

### 현재 상태 (2026-06-25 기준)

- `main` (`dev`도 동일 지점) : 훈련 플랜 P0/P1 개선, UI QA 크롤러 추가 완료. AI 분석 UI는 여전히 숨김.

---

## 작업 완료 후 필수 Git 절차

모든 기능 구현/수정 완료 후 반드시 아래를 자동 실행한다(사용자에게 매번 확인받지 않음 — 이 지침이 곧 사전 승인이다).

```powershell
git add .
git commit -m "feat/fix: 작업 내용"
git push origin main
```

> **충돌(conflict) 발생 시**: 머지를 중단하고 사용자에게 알림. 자동으로 강제 진행하지 않는다.
> **위험도가 높은 변경**(스키마 마이그레이션, 인증/결제 로직, 대량 데이터 변경 등)은 푸시 전에 사용자에게 먼저 알린다.

---

## Changelog Page (`/changelog`)

- **Environment variable required**: `NOTION_TOKEN` must be set for the API to fetch release notes.
  - Without it, `GET /api/changelog` returns `503` (expected — tests accept 200 or 503).
- **Notion release notes page ID**: `362cb889-5490-81a7-bc1f-e15501550f60`
- **Auto-reflection**: When a new version is released, update the Notion page and the web changelog updates automatically on next fetch (no redeploy needed).
- **Router**: `api/routers/changelog.py`
- **Frontend**: `frontend/changelog.html`
- **Tests** (section 11 in `tests/test_swimtech.py`):
  | Test | What it checks |
  |---|---|
  | `test_changelog_load` | Page renders header + one of loading/timeline/error |
  | `test_changelog_api_responds` | `/api/changelog` returns 200 or 503, never 404/500 |
  | `test_changelog_footer_link` | Landing page footer has a `/changelog` link |
