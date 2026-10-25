# SwimMate GA4 측정·개선 계획

작성일: 2026-10-25. 상태: **수집 비활성 상태의 1차 코드·설계 준비**.
GA4/GTM 계정·속성·태그는 아직 생성하지 않았습니다. 실제 데이터 수집,
개선 효과, 사용자 수 또는 전환율 성과를 주장하지 않습니다.

## 기획 목표와 가설

핵심 가치: 자신의 수영 훈련을 기록하고 리포트에서 되돌아보기.
질문: 사용자가 기록 화면에 들어온 뒤 작성을 시작하고 저장하기까지 어디서
막히는가? 가설: 입력 부담이나 검증 오류가 저장 완료를 저해할 수 있다.
이는 관측 전 가설이며 확인된 문제나 인과관계가 아니다.

## 범위

1차: 동의한 일반 로그인 사용자, 운영 도메인의 훈련 일지·리포트 화면.
관리자, QA, 데모, 미분류 계정, 비로그인 사용자, 미리보기 도메인은 제외한다.
쿠키 동의가 없거나 설정/인증/DB 확인이 실패하면 Google 코드를 로드하지 않는다.

2차: 유입·회원가입·로그인 여정과 첫 기록 사용자 식별을 별도로 설계한다.
현재 1차 코드로는 가입 후 7일 전환율을 산출할 수 없다. GA4 식별자에 의존한
반복 기록은 브라우저/동의/쿠키 삭제 영향을 받는다. User-ID는 이번에 도입하지 않는다.
단순 이벤트 건수로 신규 사용자나 재방문율을 계산하지 않는다.

## 이벤트 정의서 v1

| 이벤트 | 발생 조건 | 파라미터 | 해석 |
|---|---|---|---|
| page_view | 동의 후 허용 화면당 1회 | screen_name, event_schema_version | 자동 수집과 중복 금지 |
| training_log_view | 동의 후 일지 화면당 1회 | 공통값 | 동의 전의 진입은 소급하지 않음 |
| training_log_start | 신규 수기 양식의 첫 사용자 입력 | input_method=manual | 같은 작성 시도에서 1회 |
| training_log_create | 신규 수기 POST 저장 성공 | input_method=manual | 수정 PUT·수입·스크린샷 저장 제외 |
| training_log_error | 신규 수기 입력 검증·API·통신 오류 | input_method, error_code | validation/server/network 중 하나 |
| report_view | 동의 후 리포트 화면당 1회 | 공통값 | 내용이나 건강 정보 제외 |

오류 원문, 일지 본문, 운동량, 영법, 준비도, 기분, 부상, 닉네임, 이메일,
계정 ID, 토큰, 파일명은 전송하지 않는다. 허용한 열거형만 dataLayer에 넣는다.
페이지 위치는 도메인+고정 경로만 사용하고 쿼리·해시·referrer를 제거한다.

## 첫 보고서와 지표

- 동일 세션/관측 가능한 동의 사용자 기준 일지 진입 → 작성 시작 → 저장 성공
  퍼널을 만든다. 이탈은 관측 부재이지 반드시 실제 포기라는 의미는 아니다.
- 작성 완료율: 해당 관측 범위의 작성 시작 사용자 중 저장 성공 사용자 비율.
  사용자 기반/세션 기반을 섞지 않고 집계 기간·조건을 보고서에 적는다.
- 저장 오류가 발생한 세션과 발생하지 않은 세션의 흐름을 탐색한다.
- report_view는 독립 방문도 있으므로 저장 직후 경로 분석을 별도로 구성한다.
- 저장 건수의 기준은 서비스 DB. GA4 누락을 DB 결과와 동일하다고 가정하지 않는다.
- 실제 트래픽이 적으면 원자료 표본 수를 공개하고 소규모 사용성 테스트와 함께
  탐색적 결과로만 해석한다. 유의미하지 않은 차이를 성과로 제시하지 않는다.

## GA4·GTM 생성 안내

1. https://analytics.google.com 에서 계정을 만들고 속성 이름을
   `SwimMate 운영`으로 지정한다. 시간대는 대한민국, 통화는 KRW로 설정한다.
2. 데이터 스트림을 **웹**으로 만들고 URL을 `https://swimtech.vercel.app`,
   이름을 `SwimMate Web`으로 지정한다. 측정 ID `G-...`를 확인한다.
3. 초기에는 향상된 측정(폼·검색·스크롤·아웃바운드 등)을 끈다. 자동 페이지 조회와
   수동 page_view가 중복되지 않는지도 점검한다. 별도 gtag 스니펫을 추가하지 않는다.
4. https://tagmanager.google.com 에서 계정 `SwimMate`, 컨테이너
   `SwimMate Web`, 대상 플랫폼 **웹**을 만든다. `GTM-...`를 확인한다.
   약관 동의는 계정 소유자가 직접 한다. 생성만 하고 미검증 태그는 게시하지 않는다.
5. ID 두 개만 개발 담당자에게 전달한다. 비밀번호·토큰·계정 공유는 불필요하다.

공식 설정 안내:
- https://support.google.com/analytics/answer/9304153
- https://support.google.com/tagmanager/answer/14842164

## GTM 구성 체크리스트 — 활성화 전 필수

- Google 태그: 측정 ID를 지정하고 send_page_view=false. 트리거는
  커스텀 이벤트 `sm_analytics_ready`. All Pages 태그를 별도로 추가하지 않는다.
- GA4 이벤트 태그: 커스텀 이벤트 정규식은
  `^(page_view|training_log_view|training_log_start|training_log_create|training_log_error|report_view)$`.
  GA4 이벤트 이름은 GTM 기본 Event 변수, 매개변수는 허용 목록으로만 연결한다.
- 데이터 영역 변수: screen_name, input_method, error_code, event_schema_version,
  safe_page_location, safe_page_referrer, safe_page_title.
- page_location/page_referrer/page_title은 반드시 safe_* 변수로 덮어쓴다.
  screen_name은 GA4 이벤트 범위 맞춤 측정기준으로 등록한다. 자유 문자열 금지.
- 이전 이벤트의 error_code/input_method가 잔류하지 않도록 태그를 이벤트별로
  나누어 그 이벤트에서 필요한 매개변수만 전달한다.
- 자동 DOM/폼/검색/사용자 제공 데이터/광고 개인 최적화/Google Signals는 사용하지 않는다.
- 운영 컨테이너에 임의 Custom HTML, 광고 픽셀, 전체 URL/제목 변수 태그를 넣지 않는다.
- GTM은 별도로 게시되는 실행 코드이므로 코드 저장소의 허용 목록만으로는
  모든 외부 태그를 통제하지 못한다. 컨테이너 변경 승인·게시 이력을 보존한다.
- 데이터 보관은 목적에 맞게 정한다. 14개월 탐색이 필요하면 설정·근거를 기록한다.
  GA4 적용 이전 이력은 생기지 않으며 기존 DB 로그와 기간을 섞지 않는다.
- training_log_create를 주요 이벤트로 설정한다. 데이터 수집부터 검증한 뒤 적용한다.

## 활성화 게이트

운영 Render 환경에서 아래 네 설정이 모두 필요하다. 지금은 설정하지 않는다.

```
GTM_CONTAINER_ID=GTM-실제값
GA4_MEASUREMENT_ID=G-실제값
PRODUCT_ANALYTICS_ENABLED=true
ANALYTICS_PRIVACY_REVIEWED=true
```

마지막 플래그는 개인정보 안내·동의 UI·GTM 실제 전송 payload·QA 제외 검증을
모두 끝낸 뒤 설정한다. 동의 UI 코드만으로 법적 요건 충족을 주장하지 않는다.
활성화 전에 개인정보처리방침에 Google 제공자/수집 항목/목적/보유/거부·철회 방법 및
적용되는 국외 처리 고지 등 필요한 내용을 검토·반영한다.

개발/QA는 운영 플래그를 켜지 않고 로컬 mock/dataLayer로 검증한다. 실제 Google 전송
QA가 필요하면 별도 속성·별도 비운영 컨테이너·테스트 환경 allowlist를 설계한 후 진행한다.
운영 계정의 is_qa_account=false 확인은 fail-closed이며 분류가 누락되면 수집하지 않는다.

## 검증·포트폴리오 산출물

- [x] 이벤트 정의·가설·1/2차 범위 문서화
- [x] 수집 기본 OFF, 분석 동의 게이트, 서버 기반 QA/관리자 제외 코드
- [x] 신규 수기 저장 성공/실패 계측, 연속 클릭 방지, 수정 제외
- [x] 설정 실패/거부/테스트 경로/허용 매개변수 회귀 테스트
- [ ] 실제 GA4/GTM 생성 및 컨테이너 태그 구성
- [ ] 개인정보 안내 검토, 동의·철회 및 네트워크 payload 검증
- [ ] DebugView·실시간 보고서로 이벤트 순서·중복·QA 제외 증거 확보
- [ ] 초기 관측 기간·표본 수 확보, 퍼널 스크린샷과 해석 작성
- [ ] 관측 근거로 개선안 1개 실행, 동일 조건 재측정 및 한계 기록

포트폴리오 목차: 문제/가설 → 사용자 여정 → 이벤트·KPI 정의 → 수집 QA →
관측 결과 → 기획 의사결정 → 개선 → 재측정. 지금은 설계·구현 단계이고 성과 단계가 아니다.

## 기술 참고

- https://developers.google.com/tag-platform/tag-manager/datalayer
- https://developers.google.com/tag-platform/security/guides/consent
- https://support.google.com/analytics/answer/6366371
- https://support.google.com/analytics/answer/7201382
