-- SwimTech 코치-수강생 시드 데이터 (v2.5.2)
-- 실행: psql $DATABASE_URL -f db/coach_seed.sql

-- ── 테스트 계정 생성 ─────────────────────────────────────────────────────────

INSERT INTO customers (name, email, username, level)
SELECT '수영코치김철수', 'coach_kim@swimtech.test', 'coach_kim', 'advanced'
WHERE NOT EXISTS (SELECT 1 FROM customers WHERE username = 'coach_kim');

INSERT INTO customers (name, email, username, level)
SELECT '수강생이영희', 'student_lee@swimtech.test', 'student_lee', 'beginner'
WHERE NOT EXISTS (SELECT 1 FROM customers WHERE username = 'student_lee');

-- ── 코치 등록 (초대코드: SWIM-TEST) ─────────────────────────────────────────

INSERT INTO coaches (customer_id, specialty, career, intro, invite_code)
SELECT c.id,
       '자유형·접영',
       '15년 경력 수영 강사, 전국 동호인 대회 입상',
       '안녕하세요! 맞춤형 기술 코칭으로 실력 향상을 도와드립니다.',
       'SWIM-TEST'
FROM customers c
WHERE c.username = 'coach_kim'
  AND NOT EXISTS (SELECT 1 FROM coaches WHERE invite_code = 'SWIM-TEST');

-- ── 수강생 연동 (active) ──────────────────────────────────────────────────────

INSERT INTO coach_students (coach_id, student_id, status)
SELECT co.id, cu.id, 'active'
FROM coaches co, customers cu
WHERE co.invite_code = 'SWIM-TEST'
  AND cu.username = 'student_lee'
  AND NOT EXISTS (
    SELECT 1 FROM coach_students cs
    WHERE cs.coach_id = co.id AND cs.student_id = cu.id
  );
