# SwimMate Postman API Smoke

이 디렉터리는 SwimMate API를 Postman에서 직접 탐색하고, 배포 후 대표 사용자 흐름을 짧게 검증하기 위한 실행 가능한 문서다.

전체 회귀 검사의 기준은 scripts/qa_runner.py와 scripts/qa_ui_crawler.py다. Postman Collection은 이를 복제하지 않고 다음 경계만 담당한다.

- 공개 health와 비로그인 401
- 일반 사용자 쿠키 로그인과 로그인 유지
- 미리보기 없이 운동 스크린샷 확정 API를 호출할 때 일지가 생성되지 않고 404로 거부되는 고객별 확인 토큰 경계
- 훈련 일지 생성 → 월간 통계 → 월간 리포트 → 내 데이터 반영
- 월간 집계에서 닉네임 비공개 결과 카드 생성 → 공개 응답에 식별·위치 정보가 없는지 확인 → 공유 종료
- Collection이 만든 임시 훈련 일지 삭제
- 로그아웃 후 세션 차단
- 관리자 로그인, 30일 방문·가입 그래프 데이터, 아이디 카테고리 검색과 20개 단위 사용자 페이지 조회
- 일반 사용자 운영 로그의 QA 활동 제외와 QA 검증 로그의 전용 계정 활동·집계
- 관리자 로그아웃 후 권한 차단

## 파일

| 파일 | 용도 |
| --- | --- |
| SwimMate.postman_collection.json | 실행 순서와 응답 검증이 포함된 Collection v2.1 |
| production.template.postman_environment.json | Vercel 프록시를 경유하는 운영 환경 템플릿 |
| direct-api.template.postman_environment.json | Render API를 직접 진단하는 환경 템플릿 |
| local.template.postman_environment.json | 로컬 FastAPI 환경 템플릿 |

## Postman 앱에서 시작하기

1. Import에서 SwimMate.postman_collection.json을 가져온다.
2. 사용할 환경 템플릿을 가져오고 활성 환경으로 선택한다.
3. qa_username, qa_password, admin_id, admin_pw는 Postman의 로컬 값 또는 Vault에만 입력한다.
4. Collection Runner에서 전체 Collection을 순서대로 실행한다.
5. 실행 뒤 training_log_id가 비어 있고 User Logout과 Admin Logout이 통과했는지 확인한다.

FastAPI에서 자동 생성되는 전체 API 명세가 필요하면 아래 URL을 별도로 Import한다.

~~~text
https://swimtech-api.onrender.com/openapi.json
~~~

OpenAPI 가져오기는 전체 라우트 탐색용이고, 저장소의 SwimMate API Smoke Collection은 검증 순서와 정리 정책을 포함한 운영 스모크용이다.

## 인증 방식

POST /auth/login 응답은 swimtech_token과 swimtech_refresh_token을 HttpOnly 쿠키로 설정한다. Postman Cookie Jar가 같은 호스트의 후속 요청에 쿠키를 자동 전송하므로 Bearer 토큰을 따로 만들지 않는다.

운영 검증은 프런트엔드와 같은 프록시·쿠키 경로를 확인하기 위해 다음 값을 기본으로 쓴다.

~~~text
base_url=https://swimtech.vercel.app
~~~

Render를 직접 지정하는 환경은 Vercel 프록시 문제와 백엔드 문제를 분리할 때만 사용한다.

## Postman CLI

공개 폴더는 인증 정보 없이 실행할 수 있다.

~~~powershell
postman collection run tests/postman/SwimMate.postman_collection.json -e tests/postman/production.template.postman_environment.json -i "00 Public & Anonymous" --timeout-request 90000
~~~

전체 Collection은 환경 파일에 실제 비밀번호를 쓰지 않고 현재 셸의 환경변수를 전달한다.

~~~powershell
postman collection run tests/postman/SwimMate.postman_collection.json -e tests/postman/production.template.postman_environment.json --env-var "qa_username=$env:QA_USERNAME" --env-var "qa_password=$env:QA_PASSWORD" --env-var "admin_id=$env:ADMIN_ID" --env-var "admin_pw=$env:ADMIN_PW" --timeout-request 90000
~~~

로컬 파일 경로로 실행할 때는 Postman API Key나 클라우드 로그인이 필요하지 않다. 결과를 Postman Cloud Workspace에 동기화할 때만 별도의 Postman API Key를 사용한다.

## 데이터 정리 정책

- Collection은 전용 QA 계정에 300m 훈련 일지를 한 건 생성한다.
- 생성 응답의 ID를 training_log_id에 저장한다.
- 통계·리포트·내 데이터 반영과 익명 월간 결과 카드 공개·종료를 확인한 뒤 같은 일지 ID만 삭제한다.
- 중간 검증이 실패하더라도 Runner가 Delete 요청까지 진행할 수 있도록 bail 옵션을 사용하지 않는다.
- Create 이후 실행을 중단했다면 training_log_id를 확인해 Delete Smoke Training Log를 직접 실행한다.
- 실제 개인 계정이나 관리자 개인 계정으로 전체 Collection을 실행하지 않는다.

## GitHub Actions

정기·수동 Unified Quality Gate에서는 기존 운영 API와 브라우저 검사가 성공한 뒤 이 Collection을 실행한다.

- QA_USERNAME, QA_PASSWORD: 일반 사용자 스모크
- ADMIN_ID, ADMIN_PW: 관리자 읽기 전용 스모크
- POSTMAN_API_KEY: 사용하지 않음

Collection은 저장소의 로컬 JSON 파일로 실행되며 결과를 Postman Cloud로 전송하지 않는다. 비밀번호는 GitHub Secrets에서 실행 중 `/tmp`에 만드는 임시 환경 파일에만 주입하고 `always()` 정리 단계에서 삭제한다.

## 기능 추가 시

새 API를 Postman에 무조건 추가하지 않는다. 다음 중 하나에 해당할 때 대표 스모크 요청을 추가한다.

1. 로그인이나 권한 경계가 달라진다.
2. 둘 이상의 화면이 같은 데이터를 사용한다.
3. 운영 배포에서만 재현 가능한 프록시·쿠키·외부 연동 경계가 있다.
4. 외부 사용자나 협력자가 실행 가능한 API 예시가 필요하다.

추가한 요청은 상태 코드만 보지 않고 응답 데이터, 권한, 후속 화면 반영, 생성 데이터 정리까지 검증해야 한다. Collection과 환경 템플릿을 수정하면 tests/test_postman_contract.py도 함께 통과해야 한다.
