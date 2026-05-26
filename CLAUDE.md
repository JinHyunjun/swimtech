# SwimTech — CLAUDE.md

수영 영법 AI 분석 플랫폼. FastAPI + PostgreSQL + MinIO + Celery + Caddy 스택.

## 아키텍처 요약

```
caddy (443) → swim-api (FastAPI 8000)
                ├── routers/auth.py       /auth/*
                ├── routers/videos.py     /videos/*
                ├── routers/customers.py  /customers/*
                ├── routers/analysis.py   /analysis/*
                ├── routers/stream.py     /stream/*
                ├── routers/dashboard.py  /api/dashboard/*
                ├── routers/sheets.py     /api/sheets/*
                ├── routers/badge.py      /api/badges/*
                └── routers/community.py  /api/community/*

swim-worker (Celery) — 영상 분석 비동기 처리
swim-postgres (PostgreSQL 15)
swim-redis (Redis 7)
swim-minio (S3 오브젝트 스토리지)
swim-flowise (AI 챗봇, /flowise/*)
swim-flower (Celery 모니터링, dev profile)
```

## 자주 쓰는 명령

```bash
docker compose up -d              # 전체 서비스 시작
docker compose logs -f api        # API 로그 실시간 확인
docker compose exec postgres psql -U swim -d swimdb   # DB 접속
pytest tests/test_swimtech.py -v  # 테스트 실행 (서비스 실행 중 필요)
```

## 환경 변수 (docker-compose.yml)

| 변수 | 설명 |
|---|---|
| `DATABASE_URL` | PostgreSQL 연결 문자열 |
| `REDIS_URL` | Redis 연결 URL |
| `SECRET_KEY` | JWT 서명 키 |
| `ADMIN_ID` / `ADMIN_PW` | 관리자 계정 |
| `ANTHROPIC_API_KEY` | Claude API 키 |
| `KAKAO_CLIENT_ID` / `KAKAO_CLIENT_SECRET` | 카카오 OAuth |

## DB 스키마 요약

- **customers** — 사용자 (로컬/소셜 로그인)
- **sessions** — 분석 세션
- **videos** — 업로드 영상 (MinIO 경로 포함)
- **analysis_results** — AI 분석 결과 (점수, 피드백, 공유 토큰)
- **frame_metrics** — 프레임별 자세 데이터
- **posts** — 커뮤니티 게시글 (category: 자유/질문/훈련후기/공지)
- **comments** — 댓글 (parent_id로 대댓글 지원)
- **post_likes** / **comment_likes** — 좋아요 중복 방지 (복합 PK)

마이그레이션은 `db/init.sql` 한 파일에 `IF NOT EXISTS` / `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` 패턴으로 관리.

## 라우터 추가 시 체크리스트

1. `api/routers/<name>.py` 생성
2. `api/main.py` — import + `app.include_router(...)` 추가
3. `api/main.py` — 페이지 라우트 추가 (`@app.get("/path")`)
4. `caddy/Caddyfile` — `handle /path { reverse_proxy swim-api:8000 }` 추가
5. `frontend/landing.html` — 카드 추가 (필요 시)
6. `db/init.sql` — 테이블 추가 (필요 시)
7. `tests/test_swimtech.py` — 테스트 추가

## 인증 패턴

- JWT는 `swimtech_token` HttpOnly 쿠키로 전달
- `routers/auth.py`의 `decode_token(token)` → payload dict 반환
- `verify_token(token)` → username 문자열 반환 (실패 시 None)
- 관리자: `ADMIN_ID` 환경변수 (DB에 없는 특수 계정)
- 소셜 로그인 사용자는 `customer_id`가 payload에 있음; admin은 없음

## 커뮤니티 기능 (v2.3.0)

- `GET  /api/community` — 목록 (category, page, search 쿼리 파라미터)
- `POST /api/community` — 작성 (로그인 + customer_id 필요)
- `GET  /api/community/{id}` — 상세 + 댓글 목록 (조회수 자동 증가)
- `PUT  /api/community/{id}` — 수정 (본인만)
- `DELETE /api/community/{id}` — 삭제 (본인 또는 admin)
- `POST /api/community/{id}/like` — 게시글 좋아요 토글
- `POST /api/community/{id}/comments` — 댓글 작성 (parent_id로 대댓글)
- `POST /api/community/comments/{id}/like` — 댓글 좋아요 토글
- `DELETE /api/community/comments/{id}` — 댓글 삭제 (본인 또는 admin)

> 라우터 정의 순서 주의: `/comments/{id}` 관련 라우트는 반드시 `/{post_id}` 앞에 정의해야 FastAPI 라우팅이 올바르게 동작함.

## 프론트엔드 구조

- `frontend/style.css` — 공통 다크 테마 CSS 변수 (`--text`, `--muted`, `--surface`, `--border`, `--blue`, `--purple`, `--cyan`)
- 각 페이지는 독립 HTML. SPA가 아닌 MPA 구조.
- 인증은 페이지 로드 시 `fetch('/auth/me')` 로 확인.
- 커뮤니티는 로그인 없이 열람 가능. 글쓰기/댓글/좋아요는 로그인 필요.

## 테스트

```bash
# 기본 실행 (서비스가 https://localhost 에서 실행 중이어야 함)
pytest tests/test_swimtech.py -v

# 다른 URL 지정 시
TEST_BASE_URL=http://localhost:8000 VERIFY_SSL=false pytest tests/test_swimtech.py -v
```
