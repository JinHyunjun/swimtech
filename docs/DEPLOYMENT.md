# SwimMate 배포 가이드

> 기준일: 2026-07-20

사용자 표시 이름은 SwimMate지만 기존 인프라 식별자와 URL에는 `swimtech`가 남아 있다. URL·Render 서비스·쿠키 이름을 바꾸는 작업은 호환성과 외부 콘솔 설정을 함께 변경해야 하므로 이 문서 갱신 범위에서는 유지한다.

## 운영 구성

| 계층 | 서비스 | 현재 역할 |
| --- | --- | --- |
| Frontend | Vercel | `frontend/` 정적 페이지, clean URL, API rewrite, PWA |
| Backend | Render | `api/` FastAPI, 외부 API 호출, PostgreSQL 집계 |
| Database | Neon PostgreSQL | 회원·훈련·커뮤니티·코치·운영 데이터 |
| AI | Google Gemini | AI 코치, 코치 강습 문서·브리핑 |
| Work management | Jira Cloud | 코치 후속 과제 미러링·상태 동기화 |
| Release notes | Notion API | 공개 `/changelog` 읽기 |
| Maps/OAuth | Kakao, Google | 수영장 지도, 소셜 로그인 |

공개 URL:

- Frontend: `https://swimtech.vercel.app`
- Backend: `https://swimtech-api.onrender.com`
- Health: `https://swimtech-api.onrender.com/api/health`

## Vercel

Vercel 프로젝트의 Root Directory는 `frontend`다. 루트 `vercel.json`과 `frontend/vercel.json`은 현재 같은 라우팅을 유지한다.

핵심 rewrite:

```text
/api/:path*   → https://swimtech-api.onrender.com/api/:path*
/auth/:path*  → https://swimtech-api.onrender.com/auth/:path*
/pool         → https://swimtech-api.onrender.com/pool
```

호환 경로:

```text
/badges       → /badge
/training-log → /training_log
/app          → /landing
/             → /landing
```

과거 영상 분석 주소 `/meta`, `/upload`, `/viewer`, `/share/*`는 `/landing`으로 보낸다.

### Vercel 확인 항목

1. Git 연결 브랜치가 `main`인지 확인
2. Root Directory가 `frontend`인지 확인
3. clean URL과 rewrite 적용 확인
4. `/manifest.json`, `/sw.js`, `/static/style.css` 200 확인
5. `/api/health`가 same-origin rewrite로 200인지 확인
6. `/auth/demo` 후 회원 전용 페이지 진입 확인

## Render

`render.yaml`의 핵심 설정:

```yaml
name: swimtech-api
runtime: python
plan: free
rootDir: api
buildCommand: pip install -r requirements.txt
startCommand: uvicorn main:app --host 0.0.0.0 --port $PORT
healthCheckPath: /api/health
autoDeploy: true
```

Render 서비스 이름은 기존 URL 호환을 위해 `swimtech-api`를 유지한다.

### 필수 환경변수

| 변수 | 목적 |
| --- | --- |
| `DATABASE_URL` | Neon pooled PostgreSQL 연결 문자열 |
| `SECRET_KEY` | JWT 서명 |
| `BASE_URL` | OAuth callback 기준 Vercel URL |
| `ADMIN_ID`, `ADMIN_PW` | 슈퍼 관리자 호환 계정 |

`SECRET_KEY`와 관리자 비밀번호는 길고 임의의 값으로 설정하며 저장소에 넣지 않는다.

### 기능별 선택 환경변수

| 기능 | 환경변수 | 없을 때 |
| --- | --- | --- |
| AI 코치·코치 AI | `GEMINI_API_KEY` | 채팅 제한, 코치 문서는 템플릿 폴백 |
| Notion 릴리즈 노트 | `NOTION_TOKEN` | `/api/changelog` 503 |
| Google OAuth | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | Google 로그인 미사용 |
| Kakao OAuth | `KAKAO_CLIENT_ID`, `KAKAO_CLIENT_SECRET` | Kakao 로그인 미사용 |
| Kakao Maps | `KAKAO_JS_KEY` | 지도 SDK 제한 |
| Jira | `JIRA_BASE_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN`, `JIRA_PROJECT_KEY` | 로컬 코칭 과제만 저장 |
| Jira webhook | `JIRA_WEBHOOK_SECRET` | 웹훅 거부 |
| 로그인 실패 잠금 | `REDIS_URL` | Redis 기반 실패 횟수 저장 생략 |
| 커뮤니티 이미지 | `MINIO_ENDPOINT`, `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY` | 텍스트 기능과 분리해 이미지 제한 |

데모 계정 표시값은 `DEMO_USERNAME`, `DEMO_EMAIL`, `DEMO_NAME`, `DEMO_NICKNAME`으로 덮어쓸 수 있지만 기본 샘플 계정이 있어 필수는 아니다.

### Render 무료 인스턴스 주의

Render 공식 문서 기준 Free Web Service는 15분 동안 인바운드 HTTP/WebSocket 트래픽이 없으면 중지되고 다음 요청에서 다시 시작한다. 로컬 파일시스템은 재시작·재배포 때 사라질 수 있으므로 사용자 데이터와 업로드 파일의 영속 저장소로 사용하지 않는다.

- 공식 안내: <https://render.com/docs/free>
- `.github/workflows/keep-warm.yml`은 14분 간격 health ping을 보내지만, GitHub Actions 지연이나 Render 정책을 가용성 보장으로 간주하면 안 된다.
- 데이터는 Neon에 저장한다.
- 커뮤니티 이미지는 외부 영속 object storage가 설정된 경우에만 안정적으로 운영한다.

## Neon

1. Neon 프로젝트와 데이터베이스를 만든다.
2. pooled connection string을 `DATABASE_URL`로 등록한다.
3. 초기 환경은 `db/init.sql`을 적용한다.
4. 앱 시작 시 `api/main.py`와 라우터가 추가 테이블·컬럼을 보완한다.
5. 배포 후 관리자 훈련 운영 화면의 테이블 상태와 로그를 확인한다.

현재는 런타임 `IF NOT EXISTS` 마이그레이션이 많다. 운영 데이터가 중요해질수록 Alembic 버전 마이그레이션, 배포 전 백업, 스키마 롤백 절차를 별도로 둬야 한다.

Neon 무료 한도는 변경될 수 있으므로 <https://neon.com/pricing>과 프로젝트 Usage 화면을 기준으로 판단한다.

## Google·Kakao 콘솔

`BASE_URL=https://swimtech.vercel.app` 기준 callback:

```text
https://swimtech.vercel.app/auth/google/callback
https://swimtech.vercel.app/auth/kakao/callback
```

카카오 개발자 콘솔에는 Vercel 도메인을 Web 플랫폼과 Kakao Maps JavaScript 허용 도메인에 등록한다. 배포 URL을 바꾸면 OAuth callback, 카카오 도메인, `BASE_URL`과 Vercel rewrite를 함께 갱신한다.

## Jira

필수 설정:

1. Jira Cloud 프로젝트와 API token 준비
2. Render에 Jira 환경변수 등록
3. Jira webhook URL을 `https://swimtech.vercel.app/api/jira/webhook`으로 등록
4. 생성한 임의 secret을 Jira webhook과 `JIRA_WEBHOOK_SECRET`에 동일하게 설정
5. 코치 화면에서 연결 상태, 이슈 생성, 완료 전환 확인
6. Jira에서 상태를 바꾼 뒤 SwimMate에 반영되는지 확인

Jira 이슈에는 코칭 과제 제목·설명·분류와 대상 학생 표시명이 포함된다. 운영 전 Jira 프로젝트 접근 권한을 코치·운영자에게만 제한한다.

## Notion 릴리즈 노트

`api/routers/changelog.py`는 고정된 공개 릴리즈 노트 페이지의 블록을 읽어 5분 캐시한다.

- Render에 `NOTION_TOKEN` 설정
- Notion 페이지에 해당 integration 연결
- `GET /api/changelog` 200과 `/changelog` 렌더 확인
- 토큰이 없을 때 503이 핵심 훈련 기능에 영향을 주지 않는지 확인

운영 정책상 Notion 릴리즈 노트와 서비스 설명서는 배포 환경에서 기능·데이터 연동·권한·오류·회귀가 모두 확인된 기능만 반영한다.

## GitHub Actions

| Workflow | 트리거 | 역할 |
| --- | --- | --- |
| `ci.yml` | `main` push·PR | 단위·계약·Jira 통합 테스트와 리포트 |
| `render-deploy.yml` | `main`의 `api/**`, `render.yaml` 변경 | Render deploy hook |
| `qa.yml` | 매일 09:00 KST, 수동 | 배포 API QA와 UI crawler |
| `keep-warm.yml` | 14분 간격, 수동 | Render health ping |

필요한 GitHub Secrets:

- `RENDER_DEPLOY_HOOK`
- `QA_USERNAME`, `QA_PASSWORD`, `QA_EMAIL`
- 선택: `ADMIN_ID`, `ADMIN_PW`

외부 API secret은 GitHub Actions에서 실제로 사용하는 경우에만 최소 권한으로 추가한다.

## 배포 후 검증

최소 smoke:

1. `/api/health` 200
2. 일반 계정 로그인, 로그아웃, refresh, 비회원 체험
3. 훈련 일지 생성 → 통계 → 월간 리포트 같은 거리·횟수 반영 → 테스트 데이터 삭제
4. 준비도 저장 → 어드바이저 갱신 → 원래 상태 복원
5. 플랜 생성·저장·일지 전송 → 리포트 플랜 수행률 반영
6. 코치 코드 발급 → 학생 연동 → 권한 확인 → 연동 해제
7. 코치 강습 문서 생성·수정·선택 배포와 템플릿 폴백
8. Jira 설정 환경에서 과제 생성·완료·웹훅
9. 관리자 20/50/100 페이지 크기, 번호 페이지 이동, 페이지 조회 로그와 피드백 작성자
10. 브라우저 콘솔 오류, 실패 API, 모바일 레이아웃
11. `/meta`, `/upload`, `/viewer`가 영상 분석을 노출하지 않는지 확인

명령:

```powershell
python scripts/qa_runner.py --base https://swimtech.vercel.app
python scripts/qa_ui_crawler.py --base https://swimtech.vercel.app
```

자세한 완료 기준은 [품질 검증 게이트](./QUALITY_GATE.md)를 따른다.

## 관련 문서

- [README](../README.md)
- [기능 지도](./FEATURE_MAP.md)
- [기술 구조](./ARCHITECTURE.md)
- [품질 검증 게이트](./QUALITY_GATE.md)
