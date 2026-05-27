-- SwimTech 고정 테스트 계정 (v2.5.2)
-- 실행: psql $DATABASE_URL -f db/test_accounts.sql
-- 비고: 모든 INSERT 에 ON CONFLICT DO NOTHING 적용 — 재실행 안전

-- ── 테스트 계정 생성 ────────────────────────────────────────────────────────

-- 코치 테스트 계정 (TestCoach123!)
INSERT INTO customers (name, email, username, password_hash, level, social_provider)
VALUES (
    '테스트코치',
    'coach_test@swimtech.test',
    'coach_test',
    '$2b$10$rKOhdd.YF7OrLwXT4SmE6u0rJs/ZW5BXPK3.GIPfUNYp8zDQHQeLS',
    'advanced',
    'local'
)
ON CONFLICT (username) DO NOTHING;

-- 수강생 테스트 계정 (TestStudent123!)
INSERT INTO customers (name, email, username, password_hash, level, social_provider)
VALUES (
    '테스트수강생',
    'student_test@swimtech.test',
    'student_test',
    '$2b$10$rBVY8DPgZ10E.l8EZopOYuHw1nPEXZAvLN.RaUXi7iiFw93jpYsHm',
    'beginner',
    'local'
)
ON CONFLICT (username) DO NOTHING;

-- ── 코치 프로필 등록 (초대코드: SWIM-TEST1) ────────────────────────────────

INSERT INTO coaches (customer_id, specialty, career, intro, invite_code)
SELECT c.id,
       '자유형·접영',
       '테스트용 코치 계정 (자동 생성)',
       '테스트 코치 프로필입니다.',
       'SWIM-TEST1'
FROM customers c
WHERE c.username = 'coach_test'
  AND NOT EXISTS (SELECT 1 FROM coaches WHERE invite_code = 'SWIM-TEST1')
ON CONFLICT DO NOTHING;

-- ── 코치 ↔ 수강생 active 연동 등록 ───────────────────────────────────────

INSERT INTO coach_students (coach_id, student_id, status)
SELECT co.id, cu.id, 'active'
FROM coaches co
JOIN customers cu ON cu.username = 'student_test'
WHERE co.invite_code = 'SWIM-TEST1'
  AND NOT EXISTS (
    SELECT 1 FROM coach_students cs
    WHERE cs.coach_id = co.id AND cs.student_id = cu.id
  )
ON CONFLICT DO NOTHING;
