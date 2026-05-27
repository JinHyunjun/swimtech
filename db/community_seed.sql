-- SwimTech 커뮤니티 초기 콘텐츠 시드 데이터
-- admin 계정(username='admin') 작성, 중복 삽입 방지 포함
-- 실행: psql $DATABASE_URL -f db/community_seed.sql

-- ── 공지사항 ────────────────────────────────────────────────────────────────

INSERT INTO posts (customer_id, category, title, content, created_at)
SELECT c.id,
       '공지',
       'SwimTech 커뮤니티 이용 안내',
       '안녕하세요, SwimTech 커뮤니티에 오신 것을 환영합니다! 🏊

커뮤니티 이용 시 아래 규칙을 꼭 지켜주세요.

1. 상호 존중 — 다른 회원에게 욕설, 비방, 혐오 표현을 사용하지 마세요.
2. 주제 준수 — 수영 기술, 훈련, 장비, 건강에 관련된 내용을 공유해 주세요.
3. 스팸 금지 — 동일한 글을 반복 게시하거나 광고성 내용을 올리지 마세요.
4. 저작권 존중 — 타인의 사진, 영상, 글을 무단으로 게시하지 마세요.

위반 시 신고 기능을 통해 운영팀에 알려주시면 빠르게 조치하겠습니다.
함께 건강한 수영 커뮤니티를 만들어 나가요!',
       NOW() - INTERVAL '30 days'
FROM customers c
WHERE c.username = 'admin'
  AND NOT EXISTS (
    SELECT 1 FROM posts p
    WHERE p.customer_id = c.id
      AND p.title = 'SwimTech 커뮤니티 이용 안내'
  );

INSERT INTO posts (customer_id, category, title, content, created_at)
SELECT c.id,
       '공지',
       'v2.4 업데이트 안내 — 이미지 첨부·알림·북마크 출시',
       '안녕하세요! SwimTech v2.4 업데이트 내용을 안내드립니다.

■ 새 기능
• 이미지 첨부 — 게시글에 최대 3장(jpg/png/webp, 장당 5MB)을 첨부할 수 있습니다.
• 알림 센터 — 댓글 작성·좋아요·@멘션 시 실시간 알림을 받아보세요.
• 북마크 — 마음에 드는 게시글을 저장하고 나중에 모아볼 수 있습니다.
• 태그 — 게시글에 #태그를 추가해 관심 주제별로 검색하세요.
• @멘션 — 본문에 @닉네임을 입력하면 해당 회원에게 알림이 전송됩니다.
• 신고 기능 — 부적절한 게시글/댓글을 신고할 수 있습니다.
• 정렬 — 최신순·인기순·조회순으로 게시글을 정렬할 수 있습니다.

■ 개선 사항
• 주간 인기 게시글 TOP 3 섹션이 상단에 표시됩니다.
• 인기 태그 빠른 선택 기능이 추가되었습니다.

버그 또는 개선 요청은 커뮤니티 질문 게시판에 남겨주세요.',
       NOW() - INTERVAL '7 days'
FROM customers c
WHERE c.username = 'admin'
  AND NOT EXISTS (
    SELECT 1 FROM posts p
    WHERE p.customer_id = c.id
      AND p.title = 'v2.4 업데이트 안내 — 이미지 첨부·알림·북마크 출시'
  );

INSERT INTO posts (customer_id, category, title, content, created_at)
SELECT c.id,
       '공지',
       '[필독] 신고 제도 운영 안내',
       '커뮤니티 신고 제도 운영 방식을 안내드립니다.

■ 신고 사유
• 스팸 / 광고
• 욕설 / 혐오 표현
• 개인정보 노출
• 불법 정보
• 기타 (커뮤니티 규칙 위반)

■ 처리 기준
• 동일 게시글/댓글에 신고가 3건 이상 접수되면 자동으로 숨김 처리됩니다.
• 운영팀이 검토 후 최종 삭제 여부를 결정합니다.
• 허위 신고가 반복될 경우 이용이 제한될 수 있습니다.

건강한 커뮤니티 운영에 협조해 주셔서 감사합니다.',
       NOW() - INTERVAL '5 days'
FROM customers c
WHERE c.username = 'admin'
  AND NOT EXISTS (
    SELECT 1 FROM posts p
    WHERE p.customer_id = c.id
      AND p.title = '[필독] 신고 제도 운영 안내'
  );

-- ── 자유게시판 ──────────────────────────────────────────────────────────────

INSERT INTO posts (customer_id, category, title, content, created_at)
SELECT c.id,
       '자유',
       '수영 시작한 지 3개월째 — 첫 1km 완주 후기',
       '오늘 드디어 쉬지 않고 1km를 완주했습니다! 🎉

3개월 전에는 25m도 힘들었는데 이렇게 성장할 수 있을 줄 몰랐어요.
자유형 팔 동작이 처음에는 너무 어색했는데, SwimTech 분석으로 팔꿈치 각도를 교정하고 나서
훨씬 부드러워진 것 같습니다.

기록: 1000m / 23분 15초 (완전 느리지만 제겐 감동...)

다음 목표는 1500m 논스톱입니다. 다들 화이팅!',
       NOW() - INTERVAL '14 days'
FROM customers c
WHERE c.username = 'admin'
  AND NOT EXISTS (
    SELECT 1 FROM posts p
    WHERE p.customer_id = c.id
      AND p.title = '수영 시작한 지 3개월째 — 첫 1km 완주 후기'
  );

INSERT INTO posts (customer_id, category, title, content, created_at)
SELECT c.id,
       '자유',
       '겨울 새벽 수영의 매력',
       '요즘 매일 오전 6시에 수영장에 가는데, 새벽 수영의 매력을 이제야 알았습니다.

✔ 사람이 적어서 레인을 마음껏 쓸 수 있음
✔ 수영 후 아침 햇살 맞으며 걷는 기분이 최고
✔ 하루가 훨씬 여유롭게 느껴짐

단점은 이불 밖이 너무 힘들다는 것... 😅
새벽 수영 하시는 분 계신가요? 어떻게 기상 루틴 잡으셨는지 공유해 주세요!',
       NOW() - INTERVAL '10 days'
FROM customers c
WHERE c.username = 'admin'
  AND NOT EXISTS (
    SELECT 1 FROM posts p
    WHERE p.customer_id = c.id
      AND p.title = '겨울 새벽 수영의 매력'
  );

INSERT INTO posts (customer_id, category, title, content, created_at)
SELECT c.id,
       '자유',
       '수영복 브랜드 비교 — 아레나 vs 스피도 vs TYR',
       '1년 넘게 세 브랜드 수영복을 써본 소감을 공유합니다.

🔵 아레나 (Arena)
내구성이 좋고 핏이 한국인 체형에 잘 맞는 편. 가성비 최고.

🔴 스피도 (Speedo)
원단이 얇고 물 저항이 적음. 경기용으로 추천. 가격이 좀 있음.

🟡 TYR
디자인이 다양하고 어깨 스트랩이 편안함. 오래 입어도 피로감이 적음.

개인적으로는 훈련용 아레나, 기록 도전 시 스피도를 씁니다.
여러분은 어느 브랜드 선호하시나요?',
       NOW() - INTERVAL '6 days'
FROM customers c
WHERE c.username = 'admin'
  AND NOT EXISTS (
    SELECT 1 FROM posts p
    WHERE p.customer_id = c.id
      AND p.title = '수영복 브랜드 비교 — 아레나 vs 스피도 vs TYR'
  );

-- ── 질문/답변 ───────────────────────────────────────────────────────────────

INSERT INTO posts (customer_id, category, title, content, created_at)
SELECT c.id,
       '질문',
       '접영 드릴 추천해 주세요 — 팔 입수 타이밍이 안 맞아요',
       '접영을 배운 지 2개월이 됐는데, 팔이 입수할 때 타이밍이 자꾸 어긋납니다.
킥은 어느 정도 잡혔는데 팔과 킥이 싱크가 안 되는 느낌이에요.

현재 연습 방법:
1. 돌핀킥 보드 드릴 — 매일 200m
2. 원 암 버터플라이 — 주 3회

혹시 팔 입수 타이밍을 잡는 데 도움 되는 드릴이나 팁이 있으시면 공유해 주세요!
영상 분석도 해보고 싶은데 SwimTech로 접영도 분석이 가능한가요?',
       NOW() - INTERVAL '4 days'
FROM customers c
WHERE c.username = 'admin'
  AND NOT EXISTS (
    SELECT 1 FROM posts p
    WHERE p.customer_id = c.id
      AND p.title = '접영 드릴 추천해 주세요 — 팔 입수 타이밍이 안 맞아요'
  );

INSERT INTO posts (customer_id, category, title, content, created_at)
SELECT c.id,
       '질문',
       '수영 후 어깨 통증 — 스트레칭 루틴 추천받고 싶어요',
       '주 4회 수영을 하고 있는데 최근 2주 사이 왼쪽 어깨가 운동 후에 뻐근합니다.
병원 검사에서는 특별한 이상은 없다고 했고, 근육 피로 혹은 자세 문제일 수 있다고 했어요.

평소 자유형 위주로 1회 2km 정도 수영합니다.
수영 전후 스트레칭을 잘 안 했는데, 좋은 루틴 있으면 추천해 주실 수 있나요?

특히 어깨 회전근 강화에 좋은 육상 운동도 같이 알려주시면 감사합니다!',
       NOW() - INTERVAL '2 days'
FROM customers c
WHERE c.username = 'admin'
  AND NOT EXISTS (
    SELECT 1 FROM posts p
    WHERE p.customer_id = c.id
      AND p.title = '수영 후 어깨 통증 — 스트레칭 루틴 추천받고 싶어요'
  );

-- ── 훈련후기 ────────────────────────────────────────────────────────────────

INSERT INTO posts (customer_id, category, title, content, created_at)
SELECT c.id,
       '훈련후기',
       '오늘 훈련 기록 — 피라미드 인터벌 세트',
       '오늘의 훈련 메뉴 공유합니다!

[워밍업] 400m 자유형 easy
[메인] 피라미드 인터벌
  50m × 2 (rest 20s)
  100m × 2 (rest 30s)
  200m × 1 (rest 60s)
  100m × 2 (rest 30s)
  50m × 2 (rest 20s)
[쿨다운] 200m 배영 easy

총 거리: 1,500m
소요 시간: 42분

200m 구간에서 페이스 유지가 힘들었지만, 인터벌 후반으로 갈수록 속도가 붙는 느낌!
다음 주는 100m 구간을 3세트로 늘려볼 계획입니다.',
       NOW() - INTERVAL '3 days'
FROM customers c
WHERE c.username = 'admin'
  AND NOT EXISTS (
    SELECT 1 FROM posts p
    WHERE p.customer_id = c.id
      AND p.title = '오늘 훈련 기록 — 피라미드 인터벌 세트'
  );

INSERT INTO posts (customer_id, category, title, content, created_at)
SELECT c.id,
       '훈련후기',
       '배영 교정 후 2주 — 팔꿈치 각도 바꾸니 확실히 달라요',
       'SwimTech AI 분석을 통해 배영 팔꿈치 각도 문제를 발견하고 2주간 교정 훈련을 한 결과입니다.

[Before] 팔꿈치가 너무 일찍 구부러져서 추진력 손실이 컸음
[After] 팔꿈치 각도를 90도로 유지하며 S자 풀링 연습

변화:
• 100m 기록: 1분 42초 → 1분 35초 (7초 단축!)
• 어깨 피로감 감소
• 수면 중 어깨 통증이 없어짐

연습 드릴:
1. 싱글 암 배영 (팔꿈치 각도 의식하며)
2. 풀부이 배영 (킥 없이 팔 동작에만 집중)
3. 벽 잡고 팔 동작 거울 확인

앞으로 목표: 100m 1분 30초!',
       NOW() - INTERVAL '1 day'
FROM customers c
WHERE c.username = 'admin'
  AND NOT EXISTS (
    SELECT 1 FROM posts p
    WHERE p.customer_id = c.id
      AND p.title = '배영 교정 후 2주 — 팔꿈치 각도 바꾸니 확실히 달라요'
  );

-- ── 태그 연결 (선택) ─────────────────────────────────────────────────────────
-- 시드 게시글에 태그 추가 (post_id를 title로 조회)

INSERT INTO post_tags (post_id, tag)
SELECT p.id, '커뮤니티규칙'
FROM posts p JOIN customers c ON p.customer_id = c.id
WHERE c.username = 'admin' AND p.title = 'SwimTech 커뮤니티 이용 안내'
ON CONFLICT DO NOTHING;

INSERT INTO post_tags (post_id, tag)
SELECT p.id, '공지'
FROM posts p JOIN customers c ON p.customer_id = c.id
WHERE c.username = 'admin' AND p.title = 'v2.4 업데이트 안내 — 이미지 첨부·알림·북마크 출시'
ON CONFLICT DO NOTHING;

INSERT INTO post_tags (post_id, tag)
SELECT p.id, '업데이트'
FROM posts p JOIN customers c ON p.customer_id = c.id
WHERE c.username = 'admin' AND p.title = 'v2.4 업데이트 안내 — 이미지 첨부·알림·북마크 출시'
ON CONFLICT DO NOTHING;

INSERT INTO post_tags (post_id, tag)
SELECT p.id, '자유형'
FROM posts p JOIN customers c ON p.customer_id = c.id
WHERE c.username = 'admin' AND p.title = '수영 시작한 지 3개월째 — 첫 1km 완주 후기'
ON CONFLICT DO NOTHING;

INSERT INTO post_tags (post_id, tag)
SELECT p.id, '접영'
FROM posts p JOIN customers c ON p.customer_id = c.id
WHERE c.username = 'admin' AND p.title = '접영 드릴 추천해 주세요 — 팔 입수 타이밍이 안 맞아요'
ON CONFLICT DO NOTHING;

INSERT INTO post_tags (post_id, tag)
SELECT p.id, '드릴'
FROM posts p JOIN customers c ON p.customer_id = c.id
WHERE c.username = 'admin' AND p.title = '접영 드릴 추천해 주세요 — 팔 입수 타이밍이 안 맞아요'
ON CONFLICT DO NOTHING;

INSERT INTO post_tags (post_id, tag)
SELECT p.id, '어깨'
FROM posts p JOIN customers c ON p.customer_id = c.id
WHERE c.username = 'admin' AND p.title = '수영 후 어깨 통증 — 스트레칭 루틴 추천받고 싶어요'
ON CONFLICT DO NOTHING;

INSERT INTO post_tags (post_id, tag)
SELECT p.id, '부상예방'
FROM posts p JOIN customers c ON p.customer_id = c.id
WHERE c.username = 'admin' AND p.title = '수영 후 어깨 통증 — 스트레칭 루틴 추천받고 싶어요'
ON CONFLICT DO NOTHING;

INSERT INTO post_tags (post_id, tag)
SELECT p.id, '인터벌'
FROM posts p JOIN customers c ON p.customer_id = c.id
WHERE c.username = 'admin' AND p.title = '오늘 훈련 기록 — 피라미드 인터벌 세트'
ON CONFLICT DO NOTHING;

INSERT INTO post_tags (post_id, tag)
SELECT p.id, '배영'
FROM posts p JOIN customers c ON p.customer_id = c.id
WHERE c.username = 'admin' AND p.title = '배영 교정 후 2주 — 팔꿈치 각도 바꾸니 확실히 달라요'
ON CONFLICT DO NOTHING;

INSERT INTO post_tags (post_id, tag)
SELECT p.id, 'AI분석'
FROM posts p JOIN customers c ON p.customer_id = c.id
WHERE c.username = 'admin' AND p.title = '배영 교정 후 2주 — 팔꿈치 각도 바꾸니 확실히 달라요'
ON CONFLICT DO NOTHING;

-- ── 자유게시판 추가 5개 ──────────────────────────────────────────────────────

INSERT INTO posts (customer_id, category, title, content, created_at)
SELECT c.id, '자유', '올해 수영 목표 세워봤습니다',
'새해는 지났지만 이제라도 수영 목표를 정해봤습니다 😊

1. 자유형 100m 1분 30초 이내
2. 접영 50m 완주
3. 주 4회 꾸준히 나가기
4. 전국 수영 동호인 대회 1회 참가

작년에는 목표 없이 다니다 보니 성취감이 없었는데, 올해는 SwimTech 분석으로 폼도 교정하면서 체계적으로 해보려고요.
다들 올해 목표가 있으신가요?',
NOW() - INTERVAL '20 days'
FROM customers c WHERE c.username = 'admin'
AND NOT EXISTS (SELECT 1 FROM posts p WHERE p.customer_id = c.id AND p.title = '올해 수영 목표 세워봤습니다');

INSERT INTO posts (customer_id, category, title, content, created_at)
SELECT c.id, '자유', '수영장 에티켓 — 함께 쾌적하게 쓰는 법',
'공용 레인을 쓰다 보면 서로 불편한 경우가 생기더라고요.
제가 생각하는 수영장 기본 에티켓을 공유합니다.

🔵 레인 진입 전 속도 확인 — 자신과 비슷한 페이스의 레인을 선택하세요
🔵 추월 시 발을 살짝 터치 — 앞 사람 어깨를 치거나 급하게 끼어들지 않기
🔵 휴식은 코너에서 — 벽 가운데에 서 있으면 방해가 됩니다
🔵 킥보드·패들은 느린 레인에서 — 도구 사용 시 속도가 달라질 수 있으니 주의
🔵 쉬고 싶으면 레인 끝으로 — 레인 중간에 멈추면 충돌 위험

처음 수영 시작하시는 분들께 도움이 됐으면 좋겠습니다!',
NOW() - INTERVAL '16 days'
FROM customers c WHERE c.username = 'admin'
AND NOT EXISTS (SELECT 1 FROM posts p WHERE p.customer_id = c.id AND p.title = '수영장 에티켓 — 함께 쾌적하게 쓰는 법');

INSERT INTO posts (customer_id, category, title, content, created_at)
SELECT c.id, '자유', '수영 후 체중 증가? 근육량 변화 이야기',
'수영 시작하고 3개월이 지났는데 체중이 오히려 2kg 늘었습니다.

처음에는 당황했는데, 알고 보니 체지방은 줄고 근육이 붙은 거였어요.
수영은 전신 근육을 사용하기 때문에 근육량이 빠르게 증가한다고 합니다.

특히 어깨, 등, 코어 근육이 눈에 띄게 강해졌고
자세도 좋아졌다는 말을 많이 들었습니다 😄

체중계보다 체성분 측정이 더 의미 있다는 걸 몸소 느꼈네요.
수영 후 체중 변화 경험 있으신 분 계신가요?',
NOW() - INTERVAL '12 days'
FROM customers c WHERE c.username = 'admin'
AND NOT EXISTS (SELECT 1 FROM posts p WHERE p.customer_id = c.id AND p.title = '수영 후 체중 증가? 근육량 변화 이야기');

INSERT INTO posts (customer_id, category, title, content, created_at)
SELECT c.id, '자유', '수경/수모 추천 — 처음 사시는 분들을 위해',
'입문자 분들이 수경·수모 뭘 사야 할지 모르겠다는 분들 많으시죠?
제가 여러 개 써본 후 정리한 추천 목록입니다.

🥽 수경 (고글)
• 아레나 COBRA 시리즈 — 밀착력 좋고 흘림 없음 (중급 이상 추천)
• 스피도 BIOFUSE — 부드러운 실리콘, 장시간 착용 편안함 (입문 추천)
• TYR SPECIAL OPS — 넓은 시야, 오픈워터에도 OK

🧢 수모 (수영 모자)
• 실리콘 재질 — 물 저항 적고 내구성 좋음 (추천)
• 라텍스 재질 — 저렴하지만 머리카락 뽑힘 주의
• 리크라 재질 — 가장 부드럽지만 물 저항이 있음

처음엔 너무 비싼 것보다 중간 가격대로 시작하는 걸 권장합니다!',
NOW() - INTERVAL '8 days'
FROM customers c WHERE c.username = 'admin'
AND NOT EXISTS (SELECT 1 FROM posts p WHERE p.customer_id = c.id AND p.title = '수경/수모 추천 — 처음 사시는 분들을 위해');

INSERT INTO posts (customer_id, category, title, content, created_at)
SELECT c.id, '자유', '다음 달 수영 대회 참가 예정입니다!',
'드디어 첫 수영 대회에 참가 신청을 했습니다. 떨리네요 😅

종목: 자유형 100m (일반부 남성)
예상 기록 목표: 1분 40초 이내

현재 훈련 상황:
- 주 5회, 회당 2km 내외
- 스타트·턴 집중 연습 중
- SwimTech로 팔 당김 각도 교정 완료

대회 경험 있으신 분들 조언 부탁드립니다!
특히 대회 당일 웜업 루틴이나 멘탈 관리 팁 있으시면 공유해 주세요 🙏',
NOW() - INTERVAL '2 days'
FROM customers c WHERE c.username = 'admin'
AND NOT EXISTS (SELECT 1 FROM posts p WHERE p.customer_id = c.id AND p.title = '다음 달 수영 대회 참가 예정입니다!');

-- ── 질문/답변 추가 5개 ──────────────────────────────────────────────────────

INSERT INTO posts (customer_id, category, title, content, created_at)
SELECT c.id, '질문', '평영 킥이 계속 흘립니다 — 무릎 방향 교정 방법은?',
'평영을 배운 지 6개월 됐는데 킥할 때마다 무릎이 안쪽으로 모이지 않고 바깥으로 흘러버립니다.
코치님께서 "무릎을 모으세요"라고 하시는데 의식적으로 해도 자꾸 벌어져요.

혹시 비슷한 경험 하셨던 분 계신가요?
육상에서 할 수 있는 교정 운동이나 드릴이 있으면 알려주세요.

현재 시도 중인 방법:
1. 벽 잡고 킥 연습 — 무릎 모음 의식
2. 킥보드 연속 킥
3. 유연성 향상을 위한 개구리 스트레칭',
NOW() - INTERVAL '18 days'
FROM customers c WHERE c.username = 'admin'
AND NOT EXISTS (SELECT 1 FROM posts p WHERE p.customer_id = c.id AND p.title = '평영 킥이 계속 흘립니다 — 무릎 방향 교정 방법은?');

INSERT INTO posts (customer_id, category, title, content, created_at)
SELECT c.id, '질문', '자유형 호흡할 때 물이 들어옵니다 — 해결책이 있을까요?',
'자유형 호흡할 때 입으로 물이 계속 들어옵니다.
머리를 돌리는 타이밍이 문제인지, 입 모양이 문제인지 모르겠어요.

증상 설명:
- 왼쪽으로만 호흡하는데 오른쪽 파도가 입에 들어오는 느낌
- 빠른 페이스에서 더 심해짐
- 수심 얕은 레인에서 더 잘 생김

현재 수영 실력은 500m 정도는 쉬지 않고 갈 수 있는 수준입니다.
혹시 고개를 너무 많이 드는 건지, 아니면 다른 원인이 있는 건지 조언 주시면 감사하겠습니다!',
NOW() - INTERVAL '13 days'
FROM customers c WHERE c.username = 'admin'
AND NOT EXISTS (SELECT 1 FROM posts p WHERE p.customer_id = c.id AND p.title = '자유형 호흡할 때 물이 들어옵니다 — 해결책이 있을까요?');

INSERT INTO posts (customer_id, category, title, content, created_at)
SELECT c.id, '질문', '개인 레슨 vs 그룹 레슨 — 어느 쪽이 더 나을까요?',
'수영을 제대로 배우고 싶어서 레슨 등록을 고려 중인데요.
개인 레슨과 그룹 레슨 중 어떤 걸 선택해야 할지 고민입니다.

현재 상황:
- 수영 경험 전무 (완전 초보)
- 예산: 월 10~15만원 범위
- 목표: 기본 4가지 영법 마스터 후 1km 완주

개인 레슨은 피드백이 빠를 것 같고, 그룹 레슨은 가성비가 좋을 것 같아서요.
어느 쪽으로 시작하셨고 어떠셨는지 경험 공유해주시면 큰 도움이 될 것 같습니다!',
NOW() - INTERVAL '9 days'
FROM customers c WHERE c.username = 'admin'
AND NOT EXISTS (SELECT 1 FROM posts p WHERE p.customer_id = c.id AND p.title = '개인 레슨 vs 그룹 레슨 — 어느 쪽이 더 나을까요?');

INSERT INTO posts (customer_id, category, title, content, created_at)
SELECT c.id, '질문', '수영 전 식사 타이밍이 궁금합니다',
'오전 수영을 다니는데 식사 타이밍을 어떻게 해야 할지 모르겠어요.

케이스 1: 공복으로 수영 후 아침 식사
케이스 2: 간단히 먹고 1시간 후 수영
케이스 3: 수영 전 바나나 등 가벼운 간식만

공복 수영이 지방 연소에 좋다는 말도 있고,
빈속에 운동하면 근육이 빠진다는 말도 있어서 헷갈립니다.

여러분은 보통 어떻게 하시나요? 특히 오전 6시 수영 다니시는 분들 루틴이 궁금합니다.',
NOW() - INTERVAL '5 days'
FROM customers c WHERE c.username = 'admin'
AND NOT EXISTS (SELECT 1 FROM posts p WHERE p.customer_id = c.id AND p.title = '수영 전 식사 타이밍이 궁금합니다');

INSERT INTO posts (customer_id, category, title, content, created_at)
SELECT c.id, '질문', '오픈워터 수영 준비 — 실내 풀과 다른 점이 있나요?',
'올 여름 처음으로 오픈워터 수영(해수욕장 1km 코스)에 도전해볼까 합니다.
실내 수영장에서는 1.5km 정도는 편하게 수영하는 수준입니다.

오픈워터가 실내 풀과 어떻게 다른지, 그리고 추가로 준비해야 할 것들이 있는지 궁금합니다.

특히:
1. 파도·조류에 대한 체력 차이
2. 방향 찾기(사이팅) 연습 방법
3. 오픈워터 전용 장비 (웻수트 등) 필요성
4. 안전 주의사항

경험 있으신 분들의 조언 부탁드립니다!',
NOW() - INTERVAL '1 day'
FROM customers c WHERE c.username = 'admin'
AND NOT EXISTS (SELECT 1 FROM posts p WHERE p.customer_id = c.id AND p.title = '오픈워터 수영 준비 — 실내 풀과 다른 점이 있나요?');

-- ── 훈련후기 추가 5개 ──────────────────────────────────────────────────────

INSERT INTO posts (customer_id, category, title, content, created_at)
SELECT c.id, '훈련후기', '접영 첫 25m 완주 — 3개월 드릴 연습 결실',
'오늘 드디어 접영 25m를 완주했습니다!! 🦋🎉

3개월 전만 해도 5m도 못 갔는데 정말 감격스럽습니다.

훈련 히스토리:
[1개월차] 돌핀킥 드릴만 집중 — 킥보드 잡고 매일 200m
[2개월차] 단팔 접영 + 호흡 타이밍 연습
[3개월차] 전체 동작 통합, 거리 늘리기

가장 어려웠던 점: 팔 입수 타이밍과 킥 싱크를 맞추는 것.
해결 방법: SwimTech 분석으로 슬로우 모션으로 보니까 킥이 너무 일렀습니다. 2킥 타이밍 의식 후 바로 개선됐어요.

다음 목표: 접영 50m!',
NOW() - INTERVAL '22 days'
FROM customers c WHERE c.username = 'admin'
AND NOT EXISTS (SELECT 1 FROM posts p WHERE p.customer_id = c.id AND p.title = '접영 첫 25m 완주 — 3개월 드릴 연습 결실');

INSERT INTO posts (customer_id, category, title, content, created_at)
SELECT c.id, '훈련후기', '주말 장거리 훈련 후기 — 오픈워터 대비 3km',
'이번 주말에 오픈워터 대회 준비로 3km 장거리 훈련을 했습니다.

[훈련 메뉴]
웜업: 자유형 500m easy
메인: 자유형 2,000m (500m 인터벌 4세트, 휴식 2분)
보조: 킥판 킥 300m + 배영 200m
쿨다운: 자유형 200m easy
총: 3,200m / 65분

[느낀 점]
- 1,500m 이후부터 팔 당김이 짧아지는 경향 발견
- 후반부 호흡 리듬이 흐트러짐
- 턴 후 글라이드가 줄어드는 패턴

[다음 훈련 수정 사항]
- 후반부 코어 힘 유지를 위한 드라이랜드 운동 추가
- 인터벌 간 휴식을 1분 30초로 줄이기',
NOW() - INTERVAL '15 days'
FROM customers c WHERE c.username = 'admin'
AND NOT EXISTS (SELECT 1 FROM posts p WHERE p.customer_id = c.id AND p.title = '주말 장거리 훈련 후기 — 오픈워터 대비 3km');

INSERT INTO posts (customer_id, category, title, content, created_at)
SELECT c.id, '훈련후기', '평영 → 자유형 전환 훈련 — IM 준비 일지',
'개인혼영(IM) 도전을 목표로 영법 전환 훈련을 시작했습니다.

오늘의 메뉴:
[웜업] 자유형 400m
[드릴] 각 영법 50m씩 × 2 (접영/배영/평영/자유형)
[메인] IM 200m × 4 (인터벌 2분 30초)
[쿨다운] 배영 200m
총 거리: 2,000m

개인 기록:
- IM 200m 첫 도전: 4분 22초 (엄청 느리지만 완영 성공!)
- 가장 약한 구간: 평영 (숨이 먼저 차버림)

교훈: 평영 지구력 훈련을 따로 집중해야 할 것 같습니다.
다음 주는 평영 2,000m 집중 훈련 예정!',
NOW() - INTERVAL '11 days'
FROM customers c WHERE c.username = 'admin'
AND NOT EXISTS (SELECT 1 FROM posts p WHERE p.customer_id = c.id AND p.title = '평영 → 자유형 전환 훈련 — IM 준비 일지');

INSERT INTO posts (customer_id, category, title, content, created_at)
SELECT c.id, '훈련후기', '스피드 훈련 결과 — 50m 자유형 기록 갱신',
'드디어 50m 자유형 목표 기록을 달성했습니다!

목표: 35초 이내
결과: 34.2초 🎉 (이전 기록 37.1초)

4주 스피드 훈련 요약:
[1-2주] 스타트 개선 — 릴레이 출발 + 잠수돌핀킥 7회
[3주] 스프린트 세트 12×25m + 8×50m
[4주] 테이퍼링 + 기록 도전

가장 큰 차이를 만든 것:
→ 스타트 후 잠수 구간 (7m까지 연장)
→ 15m 이후 팔 회전수 유지 (숨 참기 훈련)

다음 목표는 33초대 진입!
같이 50m 기록 도전하시는 분 있으신가요?',
NOW() - INTERVAL '7 days'
FROM customers c WHERE c.username = 'admin'
AND NOT EXISTS (SELECT 1 FROM posts p WHERE p.customer_id = c.id AND p.title = '스피드 훈련 결과 — 50m 자유형 기록 갱신');

INSERT INTO posts (customer_id, category, title, content, created_at)
SELECT c.id, '훈련후기', '재활 후 복귀 훈련 — 어깨 수술 6개월 뒤',
'어깨 회전근개 수술 후 6개월만에 수영 복귀를 했습니다.

복귀 첫 훈련 메뉴 (의사·PT 협의 하에 진행):
- 배영 킥만 300m (팔 사용 금지)
- 킥판 자유형 킥 200m
- 자유형 단팔 (건강한 팔만) 100m × 2
총: 900m (40분)

수술 전 대비 50% 거리로 시작했는데도 어깨 주변 근육이 많이 약해진 게 느껴졌습니다.

앞으로 계획:
- 3주: 킥 위주 + 단팔
- 4-6주: 양팔 저강도 자유형 도입
- 2개월 이후: 인터벌 훈련 복귀

비슷한 부상 경험 있으신 분들, 복귀 과정에서 주의사항 알려주시면 감사합니다.',
NOW() - INTERVAL '4 days'
FROM customers c WHERE c.username = 'admin'
AND NOT EXISTS (SELECT 1 FROM posts p WHERE p.customer_id = c.id AND p.title = '재활 후 복귀 훈련 — 어깨 수술 6개월 뒤');

-- ── 추가 태그 ────────────────────────────────────────────────────────────────

INSERT INTO post_tags (post_id, tag)
SELECT p.id, '목표설정'
FROM posts p JOIN customers c ON p.customer_id = c.id
WHERE c.username = 'admin' AND p.title = '올해 수영 목표 세워봤습니다'
ON CONFLICT DO NOTHING;

INSERT INTO post_tags (post_id, tag)
SELECT p.id, '에티켓'
FROM posts p JOIN customers c ON p.customer_id = c.id
WHERE c.username = 'admin' AND p.title = '수영장 에티켓 — 함께 쾌적하게 쓰는 법'
ON CONFLICT DO NOTHING;

INSERT INTO post_tags (post_id, tag)
SELECT p.id, '장비'
FROM posts p JOIN customers c ON p.customer_id = c.id
WHERE c.username = 'admin' AND p.title = '수경/수모 추천 — 처음 사시는 분들을 위해'
ON CONFLICT DO NOTHING;

INSERT INTO post_tags (post_id, tag)
SELECT p.id, '입문'
FROM posts p JOIN customers c ON p.customer_id = c.id
WHERE c.username = 'admin' AND p.title = '수경/수모 추천 — 처음 사시는 분들을 위해'
ON CONFLICT DO NOTHING;

INSERT INTO post_tags (post_id, tag)
SELECT p.id, '대회'
FROM posts p JOIN customers c ON p.customer_id = c.id
WHERE c.username = 'admin' AND p.title = '다음 달 수영 대회 참가 예정입니다!'
ON CONFLICT DO NOTHING;

INSERT INTO post_tags (post_id, tag)
SELECT p.id, '평영'
FROM posts p JOIN customers c ON p.customer_id = c.id
WHERE c.username = 'admin' AND p.title = '평영 킥이 계속 흘립니다 — 무릎 방향 교정 방법은?'
ON CONFLICT DO NOTHING;

INSERT INTO post_tags (post_id, tag)
SELECT p.id, '자유형'
FROM posts p JOIN customers c ON p.customer_id = c.id
WHERE c.username = 'admin' AND p.title = '자유형 호흡할 때 물이 들어옵니다 — 해결책이 있을까요?'
ON CONFLICT DO NOTHING;

INSERT INTO post_tags (post_id, tag)
SELECT p.id, '호흡'
FROM posts p JOIN customers c ON p.customer_id = c.id
WHERE c.username = 'admin' AND p.title = '자유형 호흡할 때 물이 들어옵니다 — 해결책이 있을까요?'
ON CONFLICT DO NOTHING;

INSERT INTO post_tags (post_id, tag)
SELECT p.id, '레슨'
FROM posts p JOIN customers c ON p.customer_id = c.id
WHERE c.username = 'admin' AND p.title = '개인 레슨 vs 그룹 레슨 — 어느 쪽이 더 나을까요?'
ON CONFLICT DO NOTHING;

INSERT INTO post_tags (post_id, tag)
SELECT p.id, '오픈워터'
FROM posts p JOIN customers c ON p.customer_id = c.id
WHERE c.username = 'admin' AND p.title = '오픈워터 수영 준비 — 실내 풀과 다른 점이 있나요?'
ON CONFLICT DO NOTHING;

INSERT INTO post_tags (post_id, tag)
SELECT p.id, '접영'
FROM posts p JOIN customers c ON p.customer_id = c.id
WHERE c.username = 'admin' AND p.title = '접영 첫 25m 완주 — 3개월 드릴 연습 결실'
ON CONFLICT DO NOTHING;

INSERT INTO post_tags (post_id, tag)
SELECT p.id, '드릴'
FROM posts p JOIN customers c ON p.customer_id = c.id
WHERE c.username = 'admin' AND p.title = '접영 첫 25m 완주 — 3개월 드릴 연습 결실'
ON CONFLICT DO NOTHING;

INSERT INTO post_tags (post_id, tag)
SELECT p.id, '장거리'
FROM posts p JOIN customers c ON p.customer_id = c.id
WHERE c.username = 'admin' AND p.title = '주말 장거리 훈련 후기 — 오픈워터 대비 3km'
ON CONFLICT DO NOTHING;

INSERT INTO post_tags (post_id, tag)
SELECT p.id, '오픈워터'
FROM posts p JOIN customers c ON p.customer_id = c.id
WHERE c.username = 'admin' AND p.title = '주말 장거리 훈련 후기 — 오픈워터 대비 3km'
ON CONFLICT DO NOTHING;

INSERT INTO post_tags (post_id, tag)
SELECT p.id, '혼영'
FROM posts p JOIN customers c ON p.customer_id = c.id
WHERE c.username = 'admin' AND p.title = '평영 → 자유형 전환 훈련 — IM 준비 일지'
ON CONFLICT DO NOTHING;

INSERT INTO post_tags (post_id, tag)
SELECT p.id, '스피드'
FROM posts p JOIN customers c ON p.customer_id = c.id
WHERE c.username = 'admin' AND p.title = '스피드 훈련 결과 — 50m 자유형 기록 갱신'
ON CONFLICT DO NOTHING;

INSERT INTO post_tags (post_id, tag)
SELECT p.id, '기록'
FROM posts p JOIN customers c ON p.customer_id = c.id
WHERE c.username = 'admin' AND p.title = '스피드 훈련 결과 — 50m 자유형 기록 갱신'
ON CONFLICT DO NOTHING;

INSERT INTO post_tags (post_id, tag)
SELECT p.id, '재활'
FROM posts p JOIN customers c ON p.customer_id = c.id
WHERE c.username = 'admin' AND p.title = '재활 후 복귀 훈련 — 어깨 수술 6개월 뒤'
ON CONFLICT DO NOTHING;

INSERT INTO post_tags (post_id, tag)
SELECT p.id, '부상예방'
FROM posts p JOIN customers c ON p.customer_id = c.id
WHERE c.username = 'admin' AND p.title = '재활 후 복귀 훈련 — 어깨 수술 6개월 뒤'
ON CONFLICT DO NOTHING;
