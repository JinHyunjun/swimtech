-- ================================================
-- SwimTech — PostgreSQL 초기 스키마
-- docker-compose up 시 자동 실행됨
-- ================================================

-- Metabase 전용 DB 생성
CREATE DATABASE metabase;

-- ── 고객 테이블 ──────────────────────────────────
CREATE TABLE IF NOT EXISTS customers (
    id              SERIAL PRIMARY KEY,
    name            VARCHAR(100) NOT NULL,
    email           VARCHAR(200) UNIQUE NOT NULL,
    username        VARCHAR(100) UNIQUE,
    password_hash   VARCHAR(200),
    phone           VARCHAR(20),
    level           VARCHAR(20) DEFAULT 'beginner',  -- beginner / intermediate / advanced
    goal            TEXT,
    sheets_url      TEXT,           -- 고객별 Google Sheets 링크
    metabase_token  VARCHAR(200),   -- 고객별 Metabase 공유 토큰
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW()
);

-- ── 분석 세션 테이블 ─────────────────────────────
CREATE TABLE IF NOT EXISTS sessions (
    id              SERIAL PRIMARY KEY,
    customer_id     INTEGER REFERENCES customers(id) ON DELETE CASCADE,
    session_date    DATE DEFAULT CURRENT_DATE,
    notes           TEXT,
    created_at      TIMESTAMP DEFAULT NOW()
);

-- ── 영상 업로드 테이블 ───────────────────────────
CREATE TABLE IF NOT EXISTS videos (
    id              SERIAL PRIMARY KEY,
    session_id      INTEGER REFERENCES sessions(id) ON DELETE CASCADE,
    customer_id     INTEGER REFERENCES customers(id) ON DELETE CASCADE,
    original_filename   VARCHAR(255),
    minio_object_key    VARCHAR(500),   -- MinIO 저장 경로
    minio_result_key    VARCHAR(500),   -- 분석 결과 영상 경로
    file_size_mb        NUMERIC(8,2),
    duration_sec        INTEGER,
    status          VARCHAR(30) DEFAULT 'uploaded',
    -- uploaded / processing / done / failed
    task_id         VARCHAR(100),       -- Celery task ID
    uploaded_at     TIMESTAMP DEFAULT NOW(),
    processed_at    TIMESTAMP
);

-- ── 영법 분석 결과 테이블 ────────────────────────
CREATE TABLE IF NOT EXISTS analysis_results (
    id              SERIAL PRIMARY KEY,
    video_id        INTEGER REFERENCES videos(id) ON DELETE CASCADE,
    customer_id     INTEGER REFERENCES customers(id),
    session_id      INTEGER REFERENCES sessions(id),

    analyzed_at     TIMESTAMP DEFAULT NOW(),

    -- 영법 분류
    stroke_type     VARCHAR(30),   -- freestyle / backstroke / breaststroke / butterfly
    confidence      NUMERIC(5,2),  -- 분류 신뢰도 0~100

    -- 분석 목적 / 컨텍스트
    purpose         TEXT,          -- 고객 목표 (customers.goal)
    context         TEXT,          -- 분류 근거 설명

    -- 팔 분석
    l_elbow_avg     NUMERIC(6,2),
    r_elbow_avg     NUMERIC(6,2),
    l_elbow_min     NUMERIC(6,2),
    r_elbow_min     NUMERIC(6,2),
    arm_symmetry    NUMERIC(5,2),  -- 0~100

    -- 발차기 분석
    kick_count      INTEGER,
    kick_freq_hz    NUMERIC(5,3),

    -- 머리/시선 분석
    head_angle_avg      NUMERIC(6,2),
    head_rotation_score NUMERIC(5,2),

    -- 전체 점수
    overall_score   NUMERIC(5,2),  -- 0~100

    -- 피드백
    ai_feedback              TEXT,
    drill_recommendations    TEXT,
    youtube_recommendations  TEXT,

    analysis_duration_sec INTEGER
);

-- ── 프레임별 상세 데이터 테이블 (Metabase 시각화용) ──
CREATE TABLE IF NOT EXISTS frame_metrics (
    id              SERIAL PRIMARY KEY,
    video_id        INTEGER REFERENCES videos(id) ON DELETE CASCADE,
    frame_number    INTEGER NOT NULL,
    timestamp_sec   NUMERIC(8,3),

    -- 계산된 지표
    l_elbow_angle    NUMERIC(6,2),
    r_elbow_angle    NUMERIC(6,2),
    l_shoulder_angle NUMERIC(6,2),
    r_shoulder_angle NUMERIC(6,2),
    head_angle       NUMERIC(6,2),
    body_roll        NUMERIC(6,2),

    -- 발차기 감지
    kick_detected    BOOLEAN DEFAULT FALSE,

    created_at       TIMESTAMP DEFAULT NOW()
);

-- ── 인덱스 ───────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_videos_customer    ON videos(customer_id);
CREATE INDEX IF NOT EXISTS idx_videos_session     ON videos(session_id);
CREATE INDEX IF NOT EXISTS idx_videos_status      ON videos(status);
CREATE INDEX IF NOT EXISTS idx_analysis_customer  ON analysis_results(customer_id);
CREATE INDEX IF NOT EXISTS idx_analysis_video     ON analysis_results(video_id);
CREATE INDEX IF NOT EXISTS idx_frame_video        ON frame_metrics(video_id);
CREATE INDEX IF NOT EXISTS idx_frame_timestamp    ON frame_metrics(video_id, timestamp_sec);

-- ── 샘플 고객 데이터 (테스트용) ──────────────────
INSERT INTO customers (name, email, phone, level, goal) VALUES
    ('홍길동', 'hong@example.com', '010-1234-5678', 'intermediate', '자유형 턴 개선'),
    ('김수영', 'kim@example.com',  '010-9876-5432', 'beginner',     '기본 자세 교정')
ON CONFLICT (email) DO NOTHING;
