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

ALTER TABLE coaches ADD COLUMN IF NOT EXISTS credential_type VARCHAR(60);
ALTER TABLE coaches ADD COLUMN IF NOT EXISTS credential_number VARCHAR(120);
ALTER TABLE coaches ADD COLUMN IF NOT EXISTS credential_organization VARCHAR(120);
ALTER TABLE coaches ADD COLUMN IF NOT EXISTS verification_status VARCHAR(12) NOT NULL DEFAULT 'pending';
ALTER TABLE coaches ADD COLUMN IF NOT EXISTS verification_note TEXT;
ALTER TABLE coaches ADD COLUMN IF NOT EXISTS verified_at TIMESTAMPTZ;
ALTER TABLE coaches ADD COLUMN IF NOT EXISTS verified_by VARCHAR(100);

INSERT INTO coaches (customer_id, specialty, career, intro, invite_code,
                     credential_type, credential_number, credential_organization,
                     verification_status, verified_at, verified_by)
SELECT c.id,
       '자유형·접영',
       '테스트용 코치 계정 (자동 생성)',
       '테스트 코치 프로필입니다.',
       'SWIM-TEST1',
       'QA 테스트 자격', 'QA-COACH-001', 'SwimMate QA',
       'verified', NOW(), 'test_seed'
FROM customers c
WHERE c.username = 'coach_test'
  AND NOT EXISTS (SELECT 1 FROM coaches WHERE invite_code = 'SWIM-TEST1')
ON CONFLICT DO NOTHING;

UPDATE coaches SET
    credential_type = 'QA 테스트 자격', credential_number = 'QA-COACH-001',
    credential_organization = 'SwimMate QA', verification_status = 'verified',
    verified_at = COALESCE(verified_at, NOW()), verified_by = 'test_seed'
WHERE customer_id = (SELECT id FROM customers WHERE username = 'coach_test');

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
