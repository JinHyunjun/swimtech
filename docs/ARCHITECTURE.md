# SwimMate 기술 구조

> 코드 기준일: 2026-08-09

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
- 기능 페이지 공통 내비게이션: `frontend/static/service-nav.js`
- 목적별 사용 가이드 공통 UI: `frontend/static/tutorial-guide.css`, `tutorial-guide.js`
- 아이콘: `frontend/static/icons.svg`, `frontend/static/icons/*`
- 기능 가이드 캡처: `frontend/static/tutorial/*`
- PWA: `frontend/manifest.json`, `frontend/sw.js`

`api.js`는 쿠키를 포함한 요청, JSON 파싱, 401 로그인 이동과 오류 토스트를 공통 처리한다. `utils.js`는 HTML 이스케이프, 날짜·거리 형식, 인증 확인, 토스트, 탭과 외부 클릭 처리를 제공한다. 공개 `/tutorial`은 API 상태에 의존하지 않는 짧은 가이드 허브이고, `/tutorial/{personal|record|data|coach|help}`는 실제 QA 캡처와 사용 순서를 목적별로 나눈 정적 상세 페이지다. 공통 CSS와 활성 카테고리 스크립트로 화면 밀도와 탐색 방식을 일치시키며, 기존 서비스 사이드바도 모든 상세 경로에서 유지한다. `/admin`은 일반 서비스 메뉴와 권한·목적이 달라 별도의 8개 항목 세로 내비게이션을 사용하고, 900px 이하에서는 오버레이 드로어로 전환한다.

대표 홈 `/landing`은 별도의 기능 카드 목록 대신 개인 훈련 요약을 우선 렌더링한다. `/auth/me`로 사용자·역할·온보딩 상태를 확인하고 `/api/dashboard/summary`, `/weekly`, `/history`, `/training-advisor`를 병렬 조회해 이번 주·월간·누적 훈련량, 최근 기록과 다음 세션을 표시한다. 모든 서비스 경로는 카테고리형 왼쪽 사이드바에 모으며 준비도 입력과 상세 차트는 `/dashboard`에 유지해 대표 홈의 정보 밀도를 낮춘다.

`theme.js`는 두 적용 범위를 분리한다. `APP_HEADER_PATHS`에는 서비스·온보딩·관리자·법적 안내 화면을 넣어 공통 상단 헤더를 한 번만 만들고, `SERVICE_NAV_PATHS`에는 실제 기능 전환이 필요한 화면만 넣어 `service-nav.js`를 불러온다. 헤더는 `/auth/me`로 인증 상태를 확인해 `/landing` 홈, `/profile` 수정, 로그아웃과 테마 변경을 동일한 순서로 제공하며 비로그인 공개 화면에서는 인증 버튼을 로그인으로 바꾼다. 페이지마다 직접 만들었던 홈·브랜드·로그아웃 헤더는 숨기되 풀사이드 화면 유지처럼 페이지 고유 도구는 보조 도구막대로 남긴다.

공통 내비게이션은 현재 URL과 쿼리를 정규화해 활성 링크를 표시하고 `/auth/me`가 성공하면 회원·체험 상태를 갱신하되, 공개 정보 화면의 비로그인 401은 페이지 이동으로 바꾸지 않는다. 데스크톱에서는 헤더 아래 268px 고정 메뉴로 본문을 이동하고 900px 이하에서는 동일 메뉴를 공통 헤더의 버튼으로 여는 오버레이 드로어로 전환하며 `aria-expanded`·`aria-hidden`·`inert`, ESC 닫기와 본문 스크롤 잠금을 함께 관리한다. `favicon.svg`는 작은 크기에서도 구분되는 수영 선수·물결 도형이며 `theme.js`가 Vercel 정적 자산을 브라우저 탭에 연결하고 manifest가 PWA 아이콘으로 선언한다. FastAPI의 아이콘 호환 라우트도 해당 경로가 사용되는 배포 구성에서는 SVG를 `image/svg+xml`로 응답한다.

Vercel은 clean URL과 rewrite를 사용한다.

- `/api/*`, `/auth/*` → Render
- `/badges` → 정적 `badge.html`
- `/training-log` → 정적 `training_log.html`
- `/tutorial/{personal|record|data|coach|help}` → 목적별 정적 `tutorial_*.html`
- `/`, `/app` → `/landing` 307 리다이렉트
- 과거 영상 분석 경로 → `/landing`

## FastAPI 애플리케이션

진입점은 `api/main.py`다.

### 등록된 API 그룹

| Prefix | 라우터 | 책임 |
| --- | --- | --- |
| `/auth` | `auth.py` | 가입, 로그인, 데모, 토큰 갱신, 로그아웃, 탈퇴, 닉네임, OAuth |
| `/api/account` | `account.py` | 개인 데이터 JSON 내보내기·장기 인사이트, 비밀번호 변경, 모든 세션 무효화 |
| `/customers` | `customers.py` | 관리자용 고객 조회·생성 |
| `/api/dashboard` | `dashboard.py` | 요약, 이력, 준비도, 주간 목표, 훈련 어드바이저 |
| `/api/training-log` | `training_log.py` | 일지 CRUD, 통계, 연속 출석, 목표, 플랜 연동 |
| `/api/training-log/import` | `health_import.py` | 건강 앱 내보내기 파일 미리보기·확정 코드. 현재 공개 UI는 비활성 |
| `/api/training-log/screenshot` | `workout_screenshot.py` | 사용자 선택 운동 이미지의 Gemini 구조화 추출, 일관성 경고, 고객별 확인 토큰, 확인 후 일지·영법 세트 저장. 원본 이미지 비저장 |
| `/api/benchmarks` | `benchmarks.py` | 테스트 세트 저장·조회·삭제, 영법·거리·코스별 PB 판정 |
| `/api/report` | `report.py` | 월간 집계, 히트맵 |
| `/api/promotion` | `promotion.py` | 취소 가능한 월간 결과 카드 스냅샷, 공개 결과 조회, 클럽 공동 목표·초대 캠페인과 QR |
| `/api/plans` | `plans.py` | 커스텀 플랜, 즐겨찾기, 공유 |
| `/api/badges` | `badge.py` | 단계형 뱃지 계산 |
| `/api/challenge` | `challenge.py` | 챌린지와 참가·랭킹 |
| `/api/community` | `community.py` | 게시글·댓글·반응·신고·이미지 |
| `/api/notifications` | `notifications.py` | 알림 조회·읽음 |
| `/api/coach` | `coach.py`, `coach_ai.py` | 관계, 피드백, 개인·단체 강습, AI 문서, 크루 운영 |
| `/api/clubs` | `clubs.py`, `club_operations.py` | 클럽·반 생성, 코드 참여, 범위별 역할, 일정·출석·공지·읽음, 코치용 반 수행 분석 |
| `/api/jira` | `jira.py` | Jira 상태·이슈·웹훅 |
| `/api/chat` | `chat.py` | AI 코치 대화 이력, 검수 지식·개인화 문맥 조립과 안전한 근거 메타데이터 |
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

- `customers`: 계정, 닉네임, 역할, 상태, QA 전용 계정 표식, 수준·목표·주간 목표·선호 풀, 온보딩 완료 시각, OAuth 식별자, 인증 세션 버전·비밀번호 변경 시각
- JWT access/refresh cookie: `swimtech_token`, `swimtech_refresh_token`
- `user_activity_logs`: 페이지 조회, 메뉴, 액션, IP·브라우저. 조회 시 `customer_id`, 미인증 이벤트는 아이디를 통해 QA 계정 여부를 결합한다.

액세스·갱신 토큰에는 `auth_version`이 들어가며 비밀번호 변경, 모든 기기 로그아웃과 탈퇴 뒤 DB 버전이 증가하면 이전 토큰은 즉시 거부된다. 쿠키 이름은 호환성을 위한 레거시 기술 식별자이며 사용자 표시 브랜드는 아니다.

### 개인 훈련

- `training_logs`: 날짜, 영법, 거리, 시간, 풀 길이, 강도, 기분, 메모
- `training_readiness`: 수면, 피로, 근육 상태, 가용 시간, 계산 점수
- `training_goals`: 월간 거리 목표
- `swim_test_results`: 테스트 날짜, 영법, 거리, 풀 길이, 0.01초 단위 기록, 선택 일지 연결
- `custom_plans`: 사용자 플랜 JSON과 메타데이터
- `plan_completions`: 플랜 세션과 실제 일지의 연결
- `wearable_workouts`: 건강 앱 파일 또는 확인된 운동 스크린샷의 공급자·중복 지문·구조화 값과 변환 일지 ID. 스크린샷은 AI 초안·사용자 확정값·이미지 SHA-256만 보관하고 원본 이미지 바이트는 저장하지 않음
- `user_badges`, `challenges`, `challenge_participants`: 성취·참여
- `promotion_result_shares`: 공개 허용 월간 합계 JSON 스냅샷, 선택 닉네임, 불투명 토큰, 만료·종료·조회 수

`training_logs.customer_id`가 대시보드, 개인 데이터 대시보드, 월간 리포트, 뱃지와 챌린지 집계의 중심이다. 월간 결과 카드는 생성 시점에 허용된 집계만 `promotion_result_shares.snapshot`에 복사하며 원본 일지, 위치, 심박, 메모와 스크린샷을 공개 토큰으로 다시 조회하지 않는다.

`GET /api/account/insights`는 인증된 customer ID만 사용해 기존 데이터를 읽기 전용으로 집계한다. 전체 기간과 최근·직전 90일, 고정 12개월 추이, 영법·풀 길이, 구조화 세트·플랜·사이클 기록률과 코스별 PB를 한 응답으로 제공하며 다른 사용자의 행을 섞지 않는다. JSON 내보내기는 원본 백업·이동용이고 이 API는 화면 해석용이다.

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
- `club_promotion_campaigns`: 클럽별 공개 공동 거리 목표, 기간, 선택 반, 불투명 공개 토큰, 공개·회원 수 표시 설정과 조회 수

학생의 반 코드 참여는 클럽과 반 멤버십을 한 트랜잭션에서 활성화한다. 클럽 권한과 반 권한을 분리해 등록 코치가 특정 반만 관리할 수 있고, 모든 쓰기 API가 현재 사용자 멤버십·등록 코치 여부·담당 코치 무결성을 다시 확인한다.

일정·출석 쓰기는 클럽 소유자·코치 또는 해당 반 코치에게만 허용한다. 학생의 출석 조회는 본인 행으로 제한하고, 공지는 클럽·반 멤버십 범위에 맞는 대상만 조회·읽음 처리할 수 있다. 공지 게시 트랜잭션은 대상 회원의 기존 `notifications` 알림도 함께 만든다.

반 수행 분석 API는 같은 관리 권한을 다시 확인한 뒤 현재 활성 학생과 지난 일정만 집계한다. 출석·지각·결석만 확인된 출석률의 분모로 사용하고 사유 결석은 제외하며, 전체 학생·일정 조합 중 출석 상태가 입력된 비율은 별도의 기록 완료율로 반환한다. 학생별 개인 훈련 횟수·거리는 현재 관리자가 등록 코치이고 해당 학생과 `coach_students.status='active'` 관계까지 있을 때만 조회한다. 따라서 반 운영 권한만으로 개인 일지 통계가 공개되지 않는다.

클럽 공개 캠페인 쓰기는 클럽 소유자·코치에게만 허용한다. `swim_club_members.promotion_distance_opt_in`은 기본 `false`이며 각 회원이 직접 켠 경우에만 기간 내 일지 거리를 SQL에서 익명 합산한다. 공개 응답은 회원 식별자·개별 거리·일지 행을 반환하지 않는다. 반을 선택한 캠페인만 해당 반 참여 코드와 QR을 공개하며, 운영자가 비공개로 전환하면 같은 토큰은 즉시 404가 된다.

## 주요 데이터 흐름

### 개인화 온보딩 → 추천·플랜 기본값

1. 로그인 응답과 `/auth/me`가 서버의 `onboarding_completed_at`을 기준으로 온보딩 필요 여부를 판단한다.
2. `PUT /auth/onboarding`이 수준, 목표, 주간 횟수와 선호 풀을 같은 `customers` 행에 저장한다.
3. 대시보드 어드바이저는 저장된 풀 길이를 최근 기록 추론보다 우선하고, 수준별 거리 범위와 목표별 세션 구성을 계산한다.
4. 플랜 화면은 서버 설정을 생성 폼의 목표·횟수·풀·난이도 기본값으로 사용하되, 사용자가 이후 직접 선택한 브라우저 값은 유지한다.
5. 체험 계정은 공유 샘플 데이터 오염을 막기 위해 온보딩 변경을 허용하지 않는다.

### 훈련 일지 → 월간 리포트

```text
직접 기록 / 플랜 완료 / 확인된 운동 스크린샷
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

`training_logs`의 총거리는 기존 대시보드·뱃지·챌린지 호환 기준으로 유지한다. 세트 일괄 갱신에서 실제 완료 거리 동기화를 선택하면 같은 트랜잭션에서 총거리도 바뀌어 월간 리포트가 즉시 일치한다. 스크린샷에서 확인한 영법별 거리는 완료 상태의 `training_log_sets`로 저장되며, 월간 영법 분포는 구조화 세트가 있으면 세트 거리를 우선하고 미분류 차이는 기타 거리로 보존한다. 세트 조회·교체는 일지 소유자 customer ID를 확인하고, 일지 삭제 시 외래키 cascade로 함께 제거된다. 서로 다른 화면에서 사용자 식별 기준이 달라지면 거리·횟수가 0으로 보일 수 있으므로 customer ID와 월 필터를 함께 테스트한다.

### 운동 스크린샷 → 사용자 확인 → 훈련 일지

```text
브라우저 사진 선택기 (이미지 최대 5장)
        │  브라우저 큐에서 한 장씩 순차 처리
        │  PNG/JPEG/WEBP/HEIC/HEIF · 장당 최대 8MB · 파일 서명 검사
        ▼
POST /api/training-log/screenshot/preview (사진마다 1회)
        │  이미지 바이트는 Gemini 요청 동안만 메모리에 존재
        ▼
Gemini 구조화 추출 ── 날짜·거리·시간·풀·페이스·심박·랩·영법별 거리
        │
        ├── 서버 범위 검사·거리 합계·랩×풀 길이 경고
        └── 고객별 20분 확인 토큰 (이미지 SHA-256, 구조화 값만 보유)
                              │
                  사진별 사용자 확인·수정: “이 운동이 맞나요?”
                              │
                              ▼
POST /api/training-log/screenshot/confirm (확인한 운동마다 1회)
        ├── 의미 기반 중복 지문 → wearable_workouts
        ├── 총거리·시간 → training_logs
        └── 영법별 완료 거리 → training_log_sets
                              │
                              └── 대시보드·월간 리포트·내 데이터
```

브라우저의 다중 선택은 기존 단일 이미지 API를 병렬 호출하지 않고 순차 호출한다. 따라서 원본을 서버 배치로 묶어 보관하지 않으며 사진별 20분 확인 토큰·검토·중복 판정을 그대로 유지한다. 미리보기는 어떠한 일지도 만들지 않는다. 확인 토큰은 로그인 customer ID에 묶이고 20분 후 만료되며, 이미지 속 텍스트는 명령이 아닌 데이터로 취급해 프롬프트 주입을 무시한다. 연도가 보이지 않는 Apple Fitness 화면은 가장 가까운 과거 연도를 임시 제안하되 경고를 표시하고 날짜 입력을 사용자에게 맡긴다. 같은 사용자·공급자·날짜·시작 시각·거리·시간·풀 길이 조합은 중복 저장하지 않는다. 1차 지원 공급자는 Apple Fitness이고 Samsung Health는 같은 공급자 모델로 확장할 수 있다.

### 훈련 기록 → 내 수영 데이터

```text
training_logs ────────────── 평생 누적·최근 90일·12개월·영법·풀 분포
training_log_sets ────────── 구조화 세트·실제 사이클·세트 완료율
plan_completions ─────────── 플랜 기반 세션 비율
swim_test_results ────────── 테스트 시도·영법/거리/코스별 현재 PB
          │
          ▼
 GET /api/account/insights ── 인증된 customer ID 전용 집계
          │
          ▼
       /my-data ───────────── 장기 추이·기록 습관·규칙 인사이트
```

월 단위 성장 리포트는 선택한 달의 상세 성과를, 개인 데이터 대시보드는 전체 기간과 최근 변화의 맥락을 담당한다. 두 화면 모두 같은 훈련 기록을 읽으므로 새 일지나 세트 수행량이 저장되면 별도의 복제 테이블 없이 다음 조회에 반영된다.

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

### AI 코치 지식 검색·개인화

1. `chat.py`가 최근 사용자 발화와 현재 질문을 합쳐 후속 질문 문맥을 만든다.
2. `services/swimming_knowledge.py`가 검수된 영법·훈련·장비·안전·규정 항목을 결정적 키워드 점수로 최대 3개 선택한다.
3. `services/chat_personalization.py`는 로그인 사용자가 본인 기록 기반 답변을 명시적으로 요청한 경우에만 프로필 설정, 최근 일지 수치, 주간·월간 집계, 목표, 준비도, PB, 플랜·세트 수행 요약을 읽는다.
4. 이름·이메일·사용자명, 일지 메모와 준비도 자유 입력 메모는 생성형 AI 문맥에 포함하지 않는다.
5. 기존 Gemini 3.1 Flash-Lite 우선 폴백 순서로 답변을 생성하고, 선택된 공식 출처·내부 가이드·개인화 적용 여부를 별도 `grounding` 필드로 반환한다.
6. `/api/chat/context-preview`는 Gemini를 호출하지 않고 동일한 근거 메타데이터만 반환해 운영 QA에서 인증·지식 선택·개인화 매핑을 결정적으로 검사한다.

경기 규정 지식은 최신 확인 필요 상태로 관리한다. 자연어 답변은 공식 원문 또는 참가 대회 요강의 최종 판단을 대체하지 않는다.

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

- `api/alembic/versions/`가 배포 스키마 변경의 단일 이력이다. 기존 운영 DB의 baseline은 `20260723_01`, 현재 소스 head는 개인화 온보딩·세트 수행·클럽·반 역할·일정·출석·공지·테스트 세트·계정 세션 버전·QA 계정 분류와 홍보용 결과/클럽 캠페인을 포함한 `20260723_09`이다.
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
