# SwimMate 기술 구조

> 코드 기준일: 2026-07-24

## 한눈에 보는 구조

```text
브라우저
  │
  ├─ HTML/CSS/Vanilla JS/PWA ───────────── Vercel
  │                                          │
  └─ same-origin /api/*, /auth/* 요청 ───────┘
                                             ▼
                                      Render · FastAPI
                                             │
                    ┌────────────────────────┼────────────────────────┐
                    ▼                        ▼                        ▼
             Neon PostgreSQL          Google Gemini             외부 서비스
                    │                                          Google/Kakao OAuth
                    │                                          Kakao Maps
                    │                                          Jira Cloud REST/Webhook
                    └────────────────────────────────────────── Notion changelog 읽기
```

공개 배포는 Vercel·Render·Neon이 핵심이다. Docker Compose의 worker, Redis, MinIO, Flowise와 `analysis/`는 로컬 통합·과거 영상 분석 실험을 위한 선택 구성으로, 공개 제품 아키텍처에 포함하지 않는다.

## 프론트엔드

SwimMate는 프레임워크 빌드 단계가 없는 다중 페이지 애플리케이션이다.

- 페이지: `frontend/*.html`
- 공통 스타일: `frontend/static/style.css`
- 호환 스타일 복제본: `frontend/style.css`
- 공통 API 호출: `frontend/static/api.js`
- 공통 UI 유틸리티: `frontend/static/utils.js`
- 테마: `frontend/static/theme.js`
- 아이콘: `frontend/static/icons.svg`, `frontend/static/icons/*`
- PWA: `frontend/manifest.json`, `frontend/sw.js`

`api.js`는 쿠키를 포함한 요청, JSON 파싱, 401 로그인 이동과 오류 토스트를 공통 처리한다. `utils.js`는 HTML 이스케이프, 날짜·거리 형식, 인증 확인, 토스트, 탭과 외부 클릭 처리를 제공한다.

Vercel은 clean URL과 rewrite를 사용한다.

- `/api/*`, `/auth/*` → Render
- `/badges` → 정적 `badge.html`
- `/training-log` → 정적 `training_log.html`
- `/`, `/app` → `/landing` 307 리다이렉트
- 과거 영상 분석 경로 → `/landing`

## FastAPI 애플리케이션

진입점은 `api/main.py`다.

### 등록된 API 그룹

| Prefix | 라우터 | 책임 |
| --- | --- | --- |
| `/auth` | `auth.py` | 가입, 로그인, 데모, 토큰 갱신, 로그아웃, 탈퇴, 닉네임, OAuth |
| `/api/account` | `account.py` | 개인 데이터 JSON 내보내기, 비밀번호 변경, 모든 세션 무효화 |
| `/customers` | `customers.py` | 관리자용 고객 조회·생성 |
| `/api/dashboard` | `dashboard.py` | 요약, 이력, 준비도, 주간 목표, 훈련 어드바이저 |
| `/api/training-log` | `training_log.py` | 일지 CRUD, 통계, 연속 출석, 목표, 플랜 연동 |
| `/api/training-log/import` | `health_import.py` | 건강 앱 내보내기 파일 미리보기·확정 |
| `/api/benchmarks` | `benchmarks.py` | 테스트 세트 저장·조회·삭제, 영법·거리·코스별 PB 판정 |
| `/api/report` | `report.py` | 월간 집계, 히트맵, 공유 리포트 |
| `/api/plans` | `plans.py` | 커스텀 플랜, 즐겨찾기, 공유 |
| `/api/badges` | `badge.py` | 단계형 뱃지 계산 |
| `/api/challenge` | `challenge.py` | 챌린지와 참가·랭킹 |
| `/api/community` | `community.py` | 게시글·댓글·반응·신고·이미지 |
| `/api/notifications` | `notifications.py` | 알림 조회·읽음 |
| `/api/coach` | `coach.py`, `coach_ai.py` | 관계, 피드백, 개인·단체 강습, AI 문서, 크루 운영 |
| `/api/clubs` | `clubs.py`, `club_operations.py` | 클럽·반 생성, 코드 참여, 범위별 역할, 일정·출석·공지·읽음, 코치용 반 수행 분석 |
| `/api/jira` | `jira.py` | Jira 상태·이슈·웹훅 |
| `/api/chat` | `chat.py` | AI 코치와 대화 이력 |
| `/api/pool` | `pool.py` | 수영장 즐겨찾기 |
| `/api/admin` | `admin.py` | 관리자 집계·목록·운영 로그 |
| `/api/feedback` | `feedback.py` | 피드백 등록·관리자 조회 |
| `/api/changelog` | `changelog.py` | Notion 릴리즈 노트 읽기 |
| `/api/sheets` | `sheets.py` | 과거 Google Sheets 선택 연동 코드 |

`analysis.py`, `videos.py`, `stream.py`는 파일이 남아 있어도 `main.py`에서 공개 등록하지 않는다.

### 공통 기반

- `api/db.py`: `DATABASE_URL`과 PostgreSQL 연결
- `api/deps.py`: 현재·선택 사용자 인증 의존성
- `api/activity_log.py`: 페이지 조회·메뉴·운영 이벤트 기록
- `api/rate_limit.py`: SlowAPI limiter
- `api/integrations/jira_client.py`: Jira 설정·REST 호출·안전한 오류

일부 기존 라우터는 아직 자체 인증·DB helper를 사용한다. 새 코드는 가능한 한 `db.py`, `deps.py`를 재사용하고, 리팩터링 시 고객 ID 기준이 달라지지 않는지 회귀 테스트해야 한다.

## 데이터 모델과 기준 데이터

### 회원·인증

- `customers`: 계정, 닉네임, 역할, 상태, 수준·목표·주간 목표·선호 풀, 온보딩 완료 시각, OAuth 식별자, 인증 세션 버전·비밀번호 변경 시각
- JWT access/refresh cookie: `swimtech_token`, `swimtech_refresh_token`
- `user_activity_logs`: 페이지 조회, 메뉴, 액션, IP·브라우저

액세스·갱신 토큰에는 `auth_version`이 들어가며 비밀번호 변경, 모든 기기 로그아웃과 탈퇴 뒤 DB 버전이 증가하면 이전 토큰은 즉시 거부된다. 쿠키 이름은 호환성을 위한 레거시 기술 식별자이며 사용자 표시 브랜드는 아니다.

### 개인 훈련

- `training_logs`: 날짜, 영법, 거리, 시간, 풀 길이, 강도, 기분, 메모
- `training_readiness`: 수면, 피로, 근육 상태, 가용 시간, 계산 점수
- `training_goals`: 월간 거리 목표
- `swim_test_results`: 테스트 날짜, 영법, 거리, 풀 길이, 0.01초 단위 기록, 선택 일지 연결
- `custom_plans`: 사용자 플랜 JSON과 메타데이터
- `plan_completions`: 플랜 세션과 실제 일지의 연결
- `wearable_workouts`: 건강 앱 내보내기 원본 운동과 변환 일지 ID
- `user_badges`, `challenges`, `challenge_participants`: 성취·참여

`training_logs.customer_id`가 대시보드, 월간 리포트, 뱃지와 챌린지 집계의 중심이다. 리포트는 토큰의 customer ID를 우선 사용하고 레거시 토큰은 username으로 보완한다.

테스트 세트 PB는 `swim_test_results`의 같은 customer ID·영법·거리·풀 길이 조합 안에서만 비교한다. 기록 저장은 PostgreSQL advisory transaction lock으로 사용자별 순서를 직렬화해 동시에 들어온 결과도 이전 PB를 일관되게 판정한다. 선택한 `training_log_id`는 같은 소유자·날짜·풀 길이일 때만 연결한다.

### 커뮤니티

- `posts`, `comments`
- `post_likes`, `comment_likes`, `bookmarks`
- `post_tags`, `post_images`, `reports`
- `notifications`

이미지 저장은 MinIO 설정이 있을 때 동작한다. 공개 Render 무료 구성에서 영속 파일 저장소가 없으면 텍스트 기능과 분리해 실패해야 한다.

### 코치

- `coaches`: 프로필, 코드, 선택 자격정보·인증 상태
- `coach_students`: 학생이 만든 활성 관계
- `coach_feedbacks`, `coach_plans`
- `swim_shares`, `coach_lessons`
- `coach_ai_documents`, `coach_ai_document_recipients`, `coach_ai_insights`
- `coach_action_items`: Jira와 동기화되는 로컬 우선 코칭 과제

코치 API는 활성 관계를 다시 확인한 뒤 학생 기록을 조회하거나 문서를 배포한다. 선택 자격 인증은 신뢰 표시이며 기능 권한을 여는 승인 게이트가 아니다.

### 클럽·반

- `swim_clubs`: 등록 코치 소유자, 이름, 기본 풀 길이, 상태
- `swim_club_members`: 클럽별 `owner`, `coach`, `assistant`, `member` 역할
- `swim_classes`: 클럽 안의 반, 담당 코치, 수준·목표·풀 길이·정원·참여 코드
- `swim_class_members`: 반별 `coach`, `assistant`, `student` 역할
- `swim_class_sessions`: 반 일정, 날짜·시간·장소·레인·훈련 초점과 상태
- `swim_class_attendance`: 일정별 학생 출석 상태·메모·확인자
- `swim_class_notices`: 클럽 전체 또는 특정 반 공지
- `swim_class_notice_reads`: 사용자별 공지 읽음 시각

학생의 반 코드 참여는 클럽과 반 멤버십을 한 트랜잭션에서 활성화한다. 클럽 권한과 반 권한을 분리해 등록 코치가 특정 반만 관리할 수 있고, 모든 쓰기 API가 현재 사용자 멤버십·등록 코치 여부·담당 코치 무결성을 다시 확인한다.

일정·출석 쓰기는 클럽 소유자·코치 또는 해당 반 코치에게만 허용한다. 학생의 출석 조회는 본인 행으로 제한하고, 공지는 클럽·반 멤버십 범위에 맞는 대상만 조회·읽음 처리할 수 있다. 공지 게시 트랜잭션은 대상 회원의 기존 `notifications` 알림도 함께 만든다.

반 수행 분석 API는 같은 관리 권한을 다시 확인한 뒤 현재 활성 학생과 지난 일정만 집계한다. 출석·지각·결석만 확인된 출석률의 분모로 사용하고 사유 결석은 제외하며, 전체 학생·일정 조합 중 출석 상태가 입력된 비율은 별도의 기록 완료율로 반환한다. 학생별 개인 훈련 횟수·거리는 현재 관리자가 등록 코치이고 해당 학생과 `coach_students.status='active'` 관계까지 있을 때만 조회한다. 따라서 반 운영 권한만으로 개인 일지 통계가 공개되지 않는다.

## 주요 데이터 흐름

### 개인화 온보딩 → 추천·플랜 기본값

1. 로그인 응답과 `/auth/me`가 서버의 `onboarding_completed_at`을 기준으로 온보딩 필요 여부를 판단한다.
2. `PUT /auth/onboarding`이 수준, 목표, 주간 횟수와 선호 풀을 같은 `customers` 행에 저장한다.
3. 대시보드 어드바이저는 저장된 풀 길이를 최근 기록 추론보다 우선하고, 수준별 거리 범위와 목표별 세션 구성을 계산한다.
4. 플랜 화면은 서버 설정을 생성 폼의 목표·횟수·풀·난이도 기본값으로 사용하되, 사용자가 이후 직접 선택한 브라우저 값은 유지한다.
5. 체험 계정은 공유 샘플 데이터 오염을 막기 위해 온보딩 변경을 허용하지 않는다.

### 훈련 일지 → 월간 리포트

```text
직접 기록 / 플랜 완료 / 건강 파일 가져오기
                   │
                   ▼
             training_logs
       ┌───────────┼────────────┬──────────────┐
       ▼           ▼            ▼              ▼
   대시보드     월간 리포트    뱃지          챌린지
       └── 1:N training_log_sets ───────────→ 월간 리포트
           반복·거리·목표/실제 사이클·수행량
        training_goals + plan_completions ──→ 월간 리포트
        swim_test_results ── 코스별 PB ─────→ 월간 리포트
```

`training_logs`의 총거리는 기존 대시보드·뱃지·챌린지 호환 기준으로 유지한다. 세트 일괄 갱신에서 실제 완료 거리 동기화를 선택하면 같은 트랜잭션에서 총거리도 바뀌어 월간 리포트가 즉시 일치한다. 세트 조회·교체는 일지 소유자 customer ID를 확인하고, 일지 삭제 시 외래키 cascade로 함께 제거된다. 서로 다른 화면에서 사용자 식별 기준이 달라지면 거리·횟수가 0으로 보일 수 있으므로 customer ID와 월 필터를 함께 테스트한다.

### 테스트 세트 → 코스별 PB

1. 사용자가 날짜, 영법, 표준 거리, 25m/50m 풀과 0.01초 단위 기록을 입력한다.
2. 서버는 거리가 풀 길이의 배수인지 검사하고, 선택 일지가 있으면 소유자·날짜·풀 길이까지 확인한다.
3. 같은 사용자·영법·거리·풀 길이의 이전 최저 기록을 조회해 PB와 단축 시간을 계산한 뒤 저장한다.
4. 훈련 일지는 월간 시도·신규 PB와 전체 현재 PB를, 월간 리포트는 같은 월 필터의 테스트 성과를 표시한다.
5. 삭제는 소유권이 같은 기록만 허용하고 QA 데이터는 리포트 검증 후 모두 정리한다.

### 풀사이드 세트 실행

```text
훈련 일지의 세트 기록
        │
        ▼
 /workout?log={id} ── GET 전체 세트
        │
  출발 사이클/스톱워치 · 반복 완료 · RPE
        │
        ▼
 PATCH /api/training-log/{log_id}/sets/{set_id}
        │
        ├── training_log_sets 한 행 갱신
        └── 완료 거리 합계 → training_logs.total_distance
                              │
                              └── 일지 통계·월간 리포트
```

단일 세트 갱신은 일지와 세트의 customer ID를 모두 확인하고 트랜잭션 안에서 수행한다. 브라우저는 저장 성공 응답을 받은 뒤에만 화면 진행률을 확정하며, 실패 시 현재 세트를 유지하고 재시도할 수 있게 한다. 화면 켜짐 유지는 지원 브라우저의 Screen Wake Lock API를 사용하고 권한이나 기기 미지원 시 훈련 저장 기능과 분리해 동작한다.

### 준비도 → 훈련 추천

1. 사용자가 수면·피로·근육 상태·가용 시간을 저장한다.
2. 서버가 설명 가능한 가중 규칙으로 0~100점을 계산한다.
3. 최근 일지, 주간 목표와 준비도 상태를 조합해 회복·기술·지구력·대시 방향을 고른다.
4. 저장 직후 대시보드 어드바이저를 다시 불러온다.

생성형 AI 호출은 없다.

### 코치 문서 생성·배포

1. 등록 코치와 대상 조건을 확인한다.
2. Gemini 구조화 출력을 요청한다.
3. 실패하면 규칙 템플릿을 생성한다.
4. 결과를 초안으로 DB에 저장한다.
5. 코치가 제목·본문을 검토하고 수정한다.
6. 활성 관계의 전체 또는 선택 학생에게만 배포하고 알림을 만든다.

수업 브리핑은 외부 AI에 학생 이름을 보내지 않고 `S1`, `S2` 참조를 사용한다.

### Jira 코칭 과제

1. 코치·학생 활성 관계를 확인한다.
2. `coach_action_items`에 먼저 저장한다.
3. Jira 이슈 생성에 성공하면 키·URL·동기화 상태를 기록한다.
4. 실패해도 로컬 과제는 유지하고 `failed` 상태와 안전한 오류만 저장한다.
5. SwimMate 완료 버튼은 가능한 경우 Jira 완료 전환 후 로컬 상태를 갱신한다.
6. Jira 웹훅은 HMAC 서명과 이슈 키를 검증해 상태를 반영한다.
7. 분석은 최근 로컬 과제의 Jira 키 최대 100개를 검색하고 서버에서 60초 캐시한다.

## 인증·권한·보안

- 비밀번호는 bcrypt 해시로 저장한다.
- access cookie 8시간, refresh cookie 7일이며 HttpOnly·Secure·SameSite=Lax다.
- Redis가 연결된 환경에서는 동일 IP 로그인 실패 5회 후 15분 잠금한다.
- 로그인 30회/분, 데모 로그인 20회/분, AI 채팅 10회/분, 코치 AI 문서·브리핑 각각 6회/시간 제한이 있다.
- 관리자 권한은 DB `role='admin'`을 우선하고 `ADMIN_ID`를 호환 폴백으로 사용한다.
- 사용자 HTML 출력은 공통 `esc()` 또는 동등한 이스케이프를 사용한다.
- Jira 웹훅은 `JIRA_WEBHOOK_SECRET`을 사용한 Atlassian 형식 HMAC을 검증한다.
- 외부 API 오류에 토큰·응답 본문 같은 비밀값을 노출하지 않는다.

## DB 스키마 버전 관리

- `api/alembic/versions/`가 배포 스키마 변경의 단일 이력이다. 기존 운영 DB의 baseline은 `20260723_01`, 현재 배포 head는 개인화 온보딩·세트 수행·클럽·반 역할·일정·출석·공지와 테스트 세트 기록 테이블을 포함한 `20260723_06`이다.
- Render는 Uvicorn보다 먼저 `alembic upgrade head`를 실행한다. 기존 Render 시작 명령이 남은 환경도 FastAPI lifespan에서 같은 명령을 실행하므로 migration 누락 상태로 요청을 받지 않는다.
- Alembic 환경은 PostgreSQL advisory transaction lock을 획득해 중복 배포의 동시 migration을 직렬화한다.
- `/api/health`는 `alembic_version`을 코드의 `EXPECTED_SCHEMA_REVISION`과 비교한다. 불일치하면 503으로 배포 health check를 실패시킨다.
- GitHub Actions 핵심 게이트는 `alembic heads`를 실행해 분기된 migration head를 방지한다.
- `db/init.sql`과 일부 라우터의 `IF NOT EXISTS`는 도입 이전 스키마 호환용이다. 신규 변경은 Alembic 리비전에만 추가한다.

## 실패 격리

| 외부 또는 선택 구성 | 실패 시 기대 동작 |
| --- | --- |
| Gemini | 코치 문서는 템플릿 폴백, 채팅은 사용자에게 오류 안내 |
| Jira | 로컬 과제 저장 유지, 동기화 실패 상태 표시 |
| Notion | changelog API 503, 핵심 훈련 기능 영향 없음 |
| Kakao Maps | 키·SDK 오류 안내, 다른 페이지 영향 없음 |
| Redis | 로그인 실패 잠금 저장을 건너뛰되 인증 자체는 DB로 진행 |
| MinIO | 커뮤니티 이미지 기능 제한, 텍스트 게시글은 분리 운영 |
| 선택 DB 테이블 | 관리자 집계는 가능한 범위에서 0값과 테이블 상태 반환 |

## 관련 문서

- [기능 지도](./FEATURE_MAP.md)
- [배포 가이드](./DEPLOYMENT.md)
- [품질 검증 게이트](./QUALITY_GATE.md)
- [README](../README.md)
