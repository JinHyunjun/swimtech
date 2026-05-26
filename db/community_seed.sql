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
