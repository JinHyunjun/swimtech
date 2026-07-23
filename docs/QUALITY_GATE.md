# SwimMate 품질 검증 게이트

> 기준일: 2026-07-23

SwimMate는 단순 페이지 모음에서 훈련 기록, 플랜, 리포트, 준비도, 커뮤니티, 코치-수강생, 코치 AI, Jira 운영판까지 연결된 서비스로 커졌다. 이제 기능 하나를 추가할 때 화면이 열리는지만 확인하면 부족하다. 데이터가 다른 화면에 반영되는지, 권한 경계가 지켜지는지, 외부 연동이 실패해도 업무가 이어지는지까지 함께 봐야 한다.

이 문서는 새 기능을 개발하거나 기존 기능을 바꿀 때 넘어가야 하는 품질 기준이다.

## 현재 자동 검증 레이어

| 레이어 | 파일 | 목적 |
| --- | --- | --- |
| 단위·계약 테스트 | `tests/test_api_unit.py`, `tests/test_training_product_contracts.py` | 라우터 등록, 데이터 계약, 문서와 QA 매핑 누락 방지 |
| Playwright E2E | `tests/test_swimtech.py` | 주요 페이지 로드, UI 상호작용, 스크린샷 회귀 검증 |
| 운영 API QA | `scripts/qa_runner.py` | 실제 배포 URL에서 인증, 훈련 일지, 리포트, 준비도, 코치 AI, 관리자 API 흐름 점검 |
| 운영 UI QA | `scripts/qa_ui_crawler.py` | 실제 브라우저로 주요 메뉴, 탭, 버튼, 콘솔 오류, 실패 API 응답 점검 |
| GitHub Actions 일괄 품질 게이트 | `.github/workflows/qa.yml` | Push·PR 핵심 검사와 정기·수동 운영 API/UI 검사를 한 워크플로에서 판정 |

현재 핵심 자동 테스트는 단위·계약·Jira 통합 75개이며 Alembic 단일 head 검사도 같은 작업에서 실행한다. `tests/test_swimtech.py`의 Playwright E2E 정의 104개는 과거 로컬 통합 환경용 참고 시나리오이며 필수 품질 게이트의 통과 수에 포함하지 않는다. 실제 로그인 화면과 배포 서비스는 `qa_runner.py`와 `qa_ui_crawler.py`가 일괄 검증하고 실행별 리포트를 증적으로 보관한다.

## 변경 유형별 필수 게이트

| 변경 유형 | 반드시 확인할 것 | 테스트·문서 연결 |
| --- | --- | --- |
| 새 공개 페이지·메뉴 | 200 응답, 보호 페이지 리다이렉트, 핵심 DOM, 모바일 레이아웃, 콘솔 오류 없음 | `tests/test_swimtech.py`, `PAGE_EXPECTATIONS`, `PAGES` |
| 로그인·프로필·비회원 체험 | 쿠키 발급, 새로고침 유지, 로그아웃, 데모 계정 격리, 탈퇴·닉네임 예외 | `qa_runner.py` 인증 구간, `auth.py` 계약 테스트 |
| 훈련 일지 | 작성·조회·수정·삭제, 월간 통계, 연속 출석, 최근 기록 복사, 테스트 데이터 정리 | `qa_runner.py` 9~11, 계약 테스트 |
| 준비도·주간 어드바이저 | 체크인 저장·복원, 낮은 준비도에서 회복 우선 추천, 관리자 7일 지표 | `qa_runner.py` 18a, `/admin` UI 기대값 |
| 훈련 플랜 | 풀 길이, 사이클, 드릴·대시 필터, 품질 검증, 템플릿, 즐겨찾기, 공유, 일지 전송 | `plan.html` 계약 테스트, Playwright plan 섹션 |
| 헬스 데이터 가져오기 | 내보내기 파일 형식·크기 검증, 미리보기, 비동기 상태, 사용자별 작업 격리, 중복 표시, 선택 확인, 워치 직접 동기화로 오해할 문구 없음 | `health_import.py` 계약 테스트, 수동 샘플 업로드 |
| 월간 리포트 | 훈련 일지와 같은 사용자 기준, 평균 거리, 플랜 수행률, 목표 달성률, 공유 링크 | `qa_runner.py` 17, `report.py` 계약 테스트 |
| 뱃지·챌린지 | 실제 일지 기반 진행률, 랭킹, 참가·탈퇴, 다음 뱃지, 목표 단계 | Playwright challenge/badge, `badge.py` 계약 테스트 |
| 커뮤니티·알림 | 게시글·댓글·좋아요·북마크·신고, 태그·멘션, 이미지 제한, 읽음 처리 | `test_api_unit.py`, Playwright community, `qa_runner.py` 관리자 피드백 |
| 코치 코드·수강생 관계 | 코치 코드 즉시 발급, 학생 직접 연동·교체·해제, 코치의 접근 권한 제한 | `qa_runner.py` 18d~18f, `qa_ui_crawler.py` 사전 연동 |
| 코치 AI 강습 운영 | 생성 결과 검토 후 배포, 선택 학생 수신, 템플릿 폴백, 익명 `S1` 참조, 삭제 정리 | `coach_ai.py` 계약 테스트, `qa_runner.py` 18e |
| Jira 운영판 | SwimMate DB 선저장, Jira 동기화 실패 격리, 웹훅 멱등성, 60초 캐시, 100개 검색 제한 | `test_coach_crew_jira.py`, 선택 환경변수 QA |
| 슈퍼 관리자 | 관리자 로그인·권한, 페이지네이션, 20/50/100 page size, 운영 지표, 읽기 전용 QA, 선택 테이블 0값 폴백 | `qa_runner.py` 18b, `PAGE_EXPECTATIONS["/admin"]` |
| DB 스키마 변경 | Alembic 순차 리비전, 단일 head, Render/FastAPI 시작 전 upgrade, health 리비전 일치 | `api/alembic/`, `alembic heads`, `qa_runner.py` health |
| AI·외부 연동 | Gemini rate limit, 구조화 출력 검증, 폴백, OAuth·Kakao·Notion 키 없음 상태 | 관련 라우터 계약 테스트, 운영 smoke |
| 공개 메타데이터·정책 | PWA 이름·설명, 개인정보처리방침, 이용약관, 커뮤니티 초기 콘텐츠가 현재 브랜드·데이터 처리·활성 기능과 일치 | 문서 계약 테스트, `manifest.json`, `privacy.html`, `terms.html` |
| 릴리즈·문서 | README, 기능 지도, 아키텍처, 배포, 기능 체크리스트, 품질 게이트를 코드와 함께 갱신. Notion 릴리즈 노트·서비스 설명서는 배포 검증이 끝난 기능만 갱신 | `test_quality_gate_documentation_is_kept_current` |
| 영상 분석 재활성화 | 공개 라우터 등록 전 데이터셋, 보관·삭제 정책, 비동기 분석, E2E, 법적 안내 | 현재는 비활성 유지 계약 테스트 |

## 완료 기준

새 기능은 아래 항목을 모두 만족해야 완료로 본다.

1. 사용자 화면에서 핵심 흐름이 동작한다.
2. 저장, 재조회, 새로고침, 다른 화면 반영이 확인된다.
3. 권한이 필요한 데이터는 본인, 코치-수강생, 관리자 경계가 지켜진다.
4. 외부 API 키가 없거나 AI가 실패해도 안내 또는 폴백이 있다.
5. 비용이 생길 수 있는 요청에는 rate limit, 캐시, 전역 예산 중 최소 하나가 있다.
6. 새 페이지·새 API·새 관리자 지표는 `scripts/qa_runner.py` 또는 `scripts/qa_ui_crawler.py`에 매핑된다.
7. 계약 테스트가 README, 체크리스트, 품질 문서, 라우터 등록 상태를 함께 지킨다.
8. 운영 QA가 만든 임시 데이터는 삭제하거나 기존 상태로 복원한다.
9. 릴리즈 노트, 저장소 문서, PWA 메타데이터와 정책 문서가 실제 공개 기능과 같은 방향을 말한다.
10. 과거 영상 분석 실험 코드나 워치 기기명이 남아 있어도 공개 기능·직접 연동으로 오해할 표현이 없어야 한다.
11. 테이블·컬럼·인덱스 변경은 Alembic 리비전과 기대 스키마 리비전, health QA를 함께 갱신한다.

## 자동 실행과 계정

로컬 배치 파일은 사용하지 않는다. `.github/workflows/qa.yml`이 유일한 필수 품질 게이트다.

1. `main` Push·PR에서는 핵심 테스트를 실행한다.
2. 매일 09:00 KST 및 `workflow_dispatch`에서는 핵심 테스트 통과 후 운영 API와 브라우저 검사를 순차 실행한다.
3. API가 실패해도 브라우저 검사를 실행해 두 리포트를 모두 수집한다.
4. 마지막 결과 작업이 필수 단계 전체를 판정한다.

로그인 검사는 GitHub Actions Secrets의 전용 계정으로 수행한다. 누락된 계정이 있으면 관리자 검사를 생략하지 않고 사전 검증 단계에서 실패한다.

- 일반·코치 역할: `QA_USERNAME`, `QA_PASSWORD`, `QA_EMAIL`
- 학생 역할: `QA_STUDENT_USERNAME`, `QA_STUDENT_PASSWORD`, `QA_STUDENT_EMAIL`
- 슈퍼 관리자 역할: `ADMIN_ID`, `ADMIN_PW` (`role='admin'` 계정)

QA는 비로그인 401, 잘못된 비밀번호 401, 정상 로그인, 보안 쿠키, 로그아웃 후 세션 폐기, 일반·코치·학생·관리자 권한 경계를 확인한다. 계정 값은 코드와 리포트에 기록하지 않는다. Jira·Gemini 등 외부 키가 없는 환경에서는 해당 연동의 실패 격리와 폴백을 확인하고, 실제 키가 있는 운영 환경에서는 별도 smoke로 정상 경로를 확인한다.

## 산출물

- `tests/ci_report.html`, `tests/ci_results.xml`: 핵심 테스트 리포트
- `qa_report.json`: 운영 API QA 결과
- `qa_ui_report.json`: 운영 UI QA 결과
- `qa_ui_screenshots/`: 운영 UI QA 스크린샷
