# SwimMate 저장소 작업 가이드

## 제품 기준

SwimMate는 개인 수영인의 `준비도 → 플랜 → 일지 → 월간 리포트 → 다음 훈련` 흐름과 코치의 수강생·강습 운영을 연결하는 웹 서비스다.

- 사용자에게 보이는 서비스명: **SwimMate**
- 저장소·배포 URL·인증 쿠키 등에 남은 `swimtech`는 레거시 기술 식별자다.
- 공개 AI 기능: AI 코치 대화, 등록 코치용 강습표·일정표·익명 수업 브리핑 초안
- 규칙 기반 기능: 준비도 점수, 주간 훈련 어드바이저, 교정 포인트 플랜, 템플릿 폴백
- 공개하지 않는 기능: 영상 업로드 기반 영법 분석, 분석 결과 공유, 영상 스트리밍
- 지원하지 않는 연동: Apple Watch·Galaxy Watch 직접/실시간 동기화. 건강 앱에서 내보낸 지원 파일의 수동 가져오기만 제공한다.

제품 범위와 페이지·API 매핑은 `docs/FEATURE_MAP.md`, 기술 구조는 `docs/ARCHITECTURE.md`를 기준으로 한다.

## 기술 구조

- Frontend: HTML, CSS, Vanilla JavaScript, Chart.js, Kakao Maps SDK
- Backend: FastAPI, Pydantic, psycopg2, JWT HttpOnly Cookie, SlowAPI
- Database: Neon PostgreSQL
- AI: Google Gemini + 구조화 템플릿 폴백
- External: Google/Kakao OAuth, Jira Cloud REST/Webhook, Notion changelog
- Deployment: Vercel frontend + Render FastAPI + Neon PostgreSQL
- Quality: pytest, Playwright, 운영 API QA, 운영 UI crawler

백엔드 진입점은 `api/main.py`다. `api/worker.py`와 `analysis/`는 공개 영상 분석 경로가 아니라 로컬 레거시 실험 자산이다. `docker-compose.yml`도 이 실험 서비스를 포함하므로 공개 배포 구조와 동일하다고 가정하지 않는다.

## 반드시 지킬 작업 원칙

1. 사용자의 기존 미커밋 변경과 작업물을 보존한다.
2. 새 페이지·API·관리자 지표·외부 연동에는 자동 테스트와 운영 QA 매핑을 함께 추가한다.
3. 사용자 식별, 코치-수강생 관계, 관리자 데이터는 권한 경계를 테스트한다.
4. AI·Jira·OAuth·Kakao·Notion은 정상 경로뿐 아니라 키 없음, 할당량 초과, 외부 실패 시 동작도 확인한다.
5. 훈련 일지는 대시보드, 리포트, 뱃지, 챌린지의 기준 데이터다. 화면별 집계를 별도 데이터처럼 만들지 않는다.
6. 기능 완료 후 README, `FEATURE_CHECKLIST.md`, 기능 지도, 아키텍처와 품질 문서의 영향을 확인한다.
7. Notion 릴리즈 노트와 서비스 설명서는 배포 환경에서 기능·데이터 연동·권한·오류·회귀가 모두 확인된 뒤에만 갱신한다.
8. 비밀값, 테스트 비밀번호, API 토큰과 개인 인증 파일은 커밋하지 않는다.

세부 완료 기준은 `docs/QUALITY_GATE.md`를 따른다.

### 운영 QA 스크립트 갱신 규칙

- 새 API 또는 화면 흐름은 `scripts/qa_runner.py`나 `scripts/qa_ui_crawler.py`에 매핑한다.
- 화면 간 데이터 연동은 200 응답뿐 아니라 저장값이 다른 화면의 집계에 반영되는지 확인한다.
- 새 관리자 지표는 관리자 API, `/admin` DOM과 읽기 전용 운영 QA를 함께 갱신한다.
- QA가 만든 임시 데이터는 삭제하거나 이전 상태로 복원한다.

## 코드 구성

```text
api/
  main.py                 FastAPI 앱, 공개 라우터, 페이지 서빙, 시작 마이그레이션
  db.py                   공통 PostgreSQL 연결
  deps.py                 공통 인증 의존성
  routers/                인증·훈련·리포트·코치·커뮤니티·관리자 API
  integrations/           Jira 등 외부 API 클라이언트
frontend/
  *.html                  다중 페이지 UI
  static/api.js           공통 fetch·401·오류 처리
  static/utils.js         이스케이프·날짜·토스트·탭 유틸리티
  static/style.css        Vercel/Render에서 제공하는 공통 스타일
  style.css               호환용 복제본. 공통 스타일 수정 시 두 파일을 함께 확인
docs/
  FEATURE_MAP.md          페이지·역할·API·상태 매핑
  ARCHITECTURE.md         구성요소·데이터 흐름·외부 연동
  DEPLOYMENT.md           Vercel·Render·Neon 배포와 환경변수
  QUALITY_GATE.md         변경 유형별 필수 검증
scripts/
  qa_runner.py            배포 API 시나리오 QA
  qa_ui_crawler.py        배포 UI·DOM·콘솔 오류 QA
tests/
  test_api_unit.py
  test_training_product_contracts.py
  test_coach_crew_jira.py
  test_jira_integration.py
  test_swimtech.py        로컬 통합 Playwright E2E
```

## 검증 명령

저장소 루트에서 실행한다.

```powershell
$env:PYTHONPATH="api"
$env:PYTHONUTF8="1"
python -m pytest tests/test_api_unit.py tests/test_training_product_contracts.py tests/test_coach_crew_jira.py tests/test_jira_integration.py -q
python -m pytest tests/test_swimtech.py --collect-only -q
```

실행 중인 로컬 Docker Compose 환경에서 Playwright 전체를 검증할 때:

```powershell
tests\run_tests.bat
```

배포 환경 QA는 테스트 계정과 선택적인 관리자 환경변수를 준비한 뒤 실행한다.

```powershell
python scripts/qa_runner.py --base https://swimtech.vercel.app
python scripts/qa_ui_crawler.py --base https://swimtech.vercel.app
```

`qa_runner.py`는 쓰기 테스트 후 임시 데이터를 정리하거나 원상 복구해야 한다. 관리자 UI QA는 운영 데이터 보호를 위해 조회·탭·필터 중심으로 실행한다.

## 현재 테스트 기준

2026-07-20 수집 결과:

- 단위·계약·Jira 통합: 72개, 로컬 통과
- Playwright E2E 정의: 104개, 수집 확인
- 전체 정의: 176개

Playwright 수집 성공은 전체 E2E 통과를 의미하지 않는다. `qa_report.json`, `qa_ui_report.json`, `tests/report.html`도 생성 시점의 증적이며 현재 `main`의 통과 상태로 자동 간주하지 않는다.

## 브랜치와 배포

- 기준 브랜치는 `main` 하나다. `origin/HEAD`와 실배포가 `main`을 가리킨다.
- `dev`는 레거시 브랜치이며 새 작업 대상으로 사용하지 않는다.
- Vercel은 `frontend/`, Render는 `api/`를 기준으로 배포한다.
- 백엔드 관련 `main` 변경은 `.github/workflows/render-deploy.yml`이 Render deploy hook을 호출한다.
- `main` 푸시는 운영 반영으로 이어질 수 있으므로 변경 파일과 검증 결과를 먼저 확인한다.

## 영상 분석 레거시 경계

- `api/main.py`는 `analysis`, `videos`, `stream` 라우터를 공개 등록하지 않는다.
- `/meta`, `/upload`, `/viewer`, `/share/*`는 홈으로 이동하거나 `410 Gone`을 반환한다.
- `analysis/`, `api/tasks/analyze.py`, `api/worker.py`, Docker Compose의 worker·Redis·MinIO·Flowise는 공개 제품 기능의 근거로 문서화하지 않는다.
- 훈련 플랜의 교정 포인트 추천은 사용자가 고민을 직접 선택하는 규칙 기반 도구다. 영상 분석 결과 자동 연동으로 표현하지 않는다.
- 재활성화 전에는 평가 데이터셋, 개인정보 보관·삭제, 비동기 인프라, 비용과 배포 E2E 기준을 먼저 확정한다.

## 문서 동기화

기능이나 구조가 바뀌면 아래 순서로 영향 범위를 확인한다.

1. `README.md`: 공개 소개, 실행, 기술 스택과 검증 현황
2. `docs/FEATURE_MAP.md`: 페이지·역할·API 상태
3. `docs/ARCHITECTURE.md`: 데이터 흐름·외부 연동·보안 경계
4. `docs/DEPLOYMENT.md`: 환경변수·배포 절차
5. `FEATURE_CHECKLIST.md`: 완료 이력과 다음 우선순위
6. `docs/QUALITY_GATE.md`: 테스트 수와 변경 유형별 게이트
7. `frontend/manifest.json`, `privacy.html`, `terms.html`: 공개 메타데이터와 정책
8. 배포 QA 완료 후 Notion 릴리즈 노트와 서비스 설명서

공개 릴리즈 노트는 `api/routers/changelog.py`가 Notion 페이지를 읽어 `/changelog`에 표시한다. `NOTION_TOKEN`이 없으면 `/api/changelog`의 `503`은 의도된 제한 상태다.
