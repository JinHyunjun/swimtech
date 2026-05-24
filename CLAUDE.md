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
