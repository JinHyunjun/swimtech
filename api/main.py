import logging
import os
import psycopg2
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from rate_limit import limiter
from routers import videos, customers, analysis, stream, auth, dashboard, sheets, badge, changelog, plans, community, notifications, training_log, report, challenge, feedback, coach, pool, chat, admin
from activity_log import log_activity, resolve_menu_name
from routers.auth import verify_token, decode_token

logging.basicConfig(level=logging.INFO)

_MIGRATION_SQL = """
ALTER TABLE posts ADD COLUMN IF NOT EXISTS is_hidden BOOLEAN NOT NULL DEFAULT FALSE;
CREATE TABLE IF NOT EXISTS reports (
    id          SERIAL PRIMARY KEY,
    reporter_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    target_type VARCHAR(10) NOT NULL CHECK (target_type IN ('post','comment')),
    target_id   INTEGER NOT NULL,
    reason      VARCHAR(50) NOT NULL,
    created_at  TIMESTAMP DEFAULT NOW(),
    UNIQUE (reporter_id, target_type, target_id)
);
CREATE TABLE IF NOT EXISTS post_images (
    id         SERIAL PRIMARY KEY,
    post_id    INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    minio_key  VARCHAR(500) NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS notifications (
    id          SERIAL PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    type        VARCHAR(30) NOT NULL,
    message     TEXT NOT NULL,
    target_id   INTEGER,
    is_read     BOOLEAN NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMP DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS bookmarks (
    customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    post_id     INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    created_at  TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (customer_id, post_id)
);
CREATE TABLE IF NOT EXISTS post_tags (
    post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    tag     VARCHAR(50) NOT NULL,
    PRIMARY KEY (post_id, tag)
);
CREATE INDEX IF NOT EXISTS idx_reports_target    ON reports(target_type, target_id);
CREATE INDEX IF NOT EXISTS idx_notifications_cid ON notifications(customer_id, is_read, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_bookmarks_cid     ON bookmarks(customer_id);
CREATE INDEX IF NOT EXISTS idx_post_tags_tag     ON post_tags(tag);
CREATE INDEX IF NOT EXISTS idx_post_images_post  ON post_images(post_id);
CREATE TABLE IF NOT EXISTS challenges (
    id             SERIAL PRIMARY KEY,
    title          VARCHAR(200) NOT NULL UNIQUE,
    description    TEXT,
    goal_distance  INTEGER NOT NULL DEFAULT 0,
    challenge_type VARCHAR(20) NOT NULL DEFAULT 'distance',
    start_date     DATE NOT NULL,
    end_date       DATE NOT NULL,
    created_at     TIMESTAMP DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS challenge_participants (
    id               SERIAL PRIMARY KEY,
    challenge_id     INTEGER NOT NULL REFERENCES challenges(id) ON DELETE CASCADE,
    username         VARCHAR(100) NOT NULL,
    current_distance INTEGER NOT NULL DEFAULT 0,
    joined_at        TIMESTAMP DEFAULT NOW(),
    UNIQUE (challenge_id, username)
);
CREATE INDEX IF NOT EXISTS idx_chall_part_cid  ON challenge_participants(challenge_id);
CREATE INDEX IF NOT EXISTS idx_chall_part_user ON challenge_participants(username);
CREATE TABLE IF NOT EXISTS coaches (
    id          SERIAL PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE UNIQUE,
    specialty   VARCHAR(100),
    career      TEXT,
    intro       TEXT,
    invite_code VARCHAR(20) UNIQUE NOT NULL,
    created_at  TIMESTAMP DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS coach_students (
    id          SERIAL PRIMARY KEY,
    coach_id    INTEGER NOT NULL REFERENCES coaches(id) ON DELETE CASCADE,
    student_id  INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    status      VARCHAR(10) NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending','active')),
    created_at  TIMESTAMP DEFAULT NOW(),
    UNIQUE (coach_id, student_id)
);
CREATE TABLE IF NOT EXISTS coach_feedbacks (
    id              SERIAL PRIMARY KEY,
    coach_id        INTEGER NOT NULL REFERENCES coaches(id) ON DELETE CASCADE,
    student_id      INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    training_log_id INTEGER REFERENCES training_logs(id) ON DELETE SET NULL,
    content         TEXT NOT NULL,
    created_at      TIMESTAMP DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS coach_plans (
    id          SERIAL PRIMARY KEY,
    coach_id    INTEGER NOT NULL REFERENCES coaches(id) ON DELETE CASCADE,
    student_id  INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    content     TEXT NOT NULL,
    created_at  TIMESTAMP DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS pool_favorites (
    id         SERIAL PRIMARY KEY,
    username   VARCHAR(100) NOT NULL,
    pool_id    VARCHAR(200) NOT NULL,
    pool_name  VARCHAR(200) NOT NULL,
    address    TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE (username, pool_id)
);
CREATE TABLE IF NOT EXISTS chat_histories (
    id         SERIAL PRIMARY KEY,
    username   VARCHAR(100) NOT NULL,
    role       VARCHAR(10) NOT NULL CHECK (role IN ('user','bot')),
    content    TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_pool_fav_user  ON pool_favorites(username);
CREATE INDEX IF NOT EXISTS idx_chat_hist_user ON chat_histories(username, created_at DESC);
INSERT INTO challenges (title, description, goal_distance, challenge_type, start_date, end_date)
VALUES
  ('5월 100km 챌린지', '5월 한 달 동안 총 100km를 달성하세요! 매일 꾸준히 수영하면 충분히 달성할 수 있습니다.', 100000, 'distance', '2026-05-01', '2026-05-31'),
  ('영법 마스터 챌린지', '자유형·배영·평영·접영 4가지 영법을 각 10km씩, 총 40km를 완주하세요!', 40000, 'distance', '2026-05-01', '2026-06-30'),
  ('30일 연속 수영 챌린지', '30일 동안 하루도 빠지지 않고 수영하세요. 꾸준함이 실력을 만들어 줍니다!', 30, 'streak', '2026-05-01', '2026-06-30')
ON CONFLICT (title) DO NOTHING;
CREATE TABLE IF NOT EXISTS plan_favorites (
    id         SERIAL PRIMARY KEY,
    username   VARCHAR(100) NOT NULL,
    plan_key   VARCHAR(200) NOT NULL,
    plan_title VARCHAR(200),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (username, plan_key)
);
CREATE TABLE IF NOT EXISTS plan_shares (
    id          SERIAL PRIMARY KEY,
    username    VARCHAR(100) NOT NULL,
    plan_key    VARCHAR(200) NOT NULL,
    plan_title  VARCHAR(200),
    share_token VARCHAR(32) NOT NULL UNIQUE,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS user_badges (
    id        SERIAL PRIMARY KEY,
    username  VARCHAR(100) NOT NULL,
    badge_id  VARCHAR(100) NOT NULL,
    earned_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (username, badge_id)
);
CREATE INDEX IF NOT EXISTS idx_plan_fav_user  ON plan_favorites(username);
CREATE INDEX IF NOT EXISTS idx_user_badges_user ON user_badges(username);
"""

app = FastAPI(
    title="SwimTech API",
    description="수영 영법 분석 플랫폼 백엔드",
    version="0.1.0"
)

_API_PREFIXES = ("/api/", "/auth/", "/videos/", "/analysis/", "/stream/", "/customers/")

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)


@app.on_event("startup")
def apply_migrations():
    DATABASE_URL = os.getenv("DATABASE_URL", "")
    if not DATABASE_URL:
        return
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute(_MIGRATION_SQL)
        conn.commit()
        cur.close(); conn.close()
        logging.info("v2.4.1 DB 마이그레이션 완료")
    except Exception as e:
        logging.warning(f"마이그레이션 실패 (무시): {e}")


@app.exception_handler(StarletteHTTPException)
async def custom_http_exception_handler(request: Request, exc: StarletteHTTPException):
    path = request.url.path
    is_api = any(path.startswith(p) for p in _API_PREFIXES)
    if not is_api:
        if exc.status_code == 404:
            html = os.path.join(FRONTEND_DIR, "404.html")
            if os.path.exists(html):
                return FileResponse(html, status_code=404)
        elif exc.status_code >= 500:
            html = os.path.join(FRONTEND_DIR, "500.html")
            if os.path.exists(html):
                return FileResponse(html, status_code=exc.status_code)
    return JSONResponse(status_code=exc.status_code, content={"detail": str(exc.detail)})


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logging.error("Unhandled exception: %s", exc, exc_info=True)
    html = os.path.join(FRONTEND_DIR, "500.html")
    if os.path.exists(html):
        return FileResponse(html, status_code=500)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://localhost"],
    allow_origin_regex=r"https://[^./]+\.trycloudflare\.com",
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)

@app.middleware("http")
async def _log_page_views(request: Request, call_next):
    response = await call_next(request)
    try:
        path = request.url.path
        if request.method == "GET" and not any(
            path.startswith(p) for p in _API_PREFIXES
        ) and not path.startswith("/static"):
            menu = resolve_menu_name(path)
            if menu:
                token = request.cookies.get("swimtech_token")
                username = None
                customer_id = None
                if token:
                    try:
                        payload = decode_token(token)
                        username = payload.get("sub")
                        customer_id = payload.get("customer_id")
                    except Exception:
                        pass
                log_activity(
                    customer_id=customer_id, username=username,
                    event_type="page_view", page=path, menu_name=menu,
                    method=request.method, path=path,
                    ip_address=request.client.host if request.client else None,
                    user_agent=request.headers.get("user-agent"),
                )
    except Exception:
        pass
    return response

app.include_router(auth.router,      prefix="/auth",      tags=["인증"])
app.include_router(admin.router,     prefix="/api/admin", tags=["관리자"])
app.include_router(videos.router,    prefix="/videos",    tags=["영상"])
app.include_router(customers.router, prefix="/customers", tags=["고객"])
app.include_router(analysis.router,  prefix="/analysis",  tags=["분석"])
app.include_router(stream.router,    prefix="/stream",    tags=["실시간 분석"])
app.include_router(dashboard.router, prefix="/api/dashboard", tags=["대시보드"])
app.include_router(sheets.router,   prefix="/api/sheets",    tags=["Sheets"])
app.include_router(badge.router,      prefix="/api/badges",     tags=["뱃지"])
app.include_router(changelog.router,  prefix="/api/changelog",  tags=["변경 이력"])
app.include_router(plans.router,      prefix="/api/plans",      tags=["훈련 플랜"])
app.include_router(community.router,      prefix="/api/community",      tags=["커뮤니티"])
app.include_router(notifications.router,  prefix="/api/notifications",  tags=["알림"])
app.include_router(training_log.router,   prefix="/api/training-log",   tags=["훈련 일지"])
app.include_router(report.router,         prefix="/api/report",          tags=["월간 리포트"])
app.include_router(challenge.router,      prefix="/api/challenge",       tags=["챌린지"])
app.include_router(feedback.router,       prefix="/api/feedback",        tags=["피드백"])
app.include_router(coach.router,          prefix="/api/coach",           tags=["코치"])
app.include_router(pool.router,           prefix="/api/pool",            tags=["수영장"])
app.include_router(chat.router,           prefix="/api/chat",            tags=["챗봇"])

@app.get("/api/health")
def health():
    return {"status": "healthy"}

@app.post("/api/open-folder")
def open_folder():
    """Windows 탐색기에서 video 폴더 열기"""
    import subprocess, platform
    video_dir = "/app/video"
    try:
        if platform.system() == "Windows":
            subprocess.Popen(["explorer", video_dir])
        else:
            # Docker 내부에서는 실행 불가 → 클라이언트에서 파일 선택 다이얼로그 열기
            pass
        return {"status": "ok"}
    except Exception:
        return {"status": "fallback"}

FRONTEND_DIR = "/app/frontend"
templates = Jinja2Templates(directory=FRONTEND_DIR)

# 로그인 페이지
@app.get("/login")
def login_page():
    path = os.path.join(FRONTEND_DIR, "login.html")
    if os.path.exists(path):
        return FileResponse(path)
    return {"error": "login.html not found"}

# 회원가입 페이지
@app.get("/register")
def register_page():
    path = os.path.join(FRONTEND_DIR, "register.html")
    if os.path.exists(path):
        return FileResponse(path)
    return {"error": "register.html not found"}

# 랜딩 페이지 (로그인 불필요, 서비스 소개)
@app.get("/landing")
def landing_page():
    path = os.path.join(FRONTEND_DIR, "landing.html")
    if os.path.exists(path):
        return FileResponse(path)
    return RedirectResponse(url="/login")

# 개인정보처리방침 (로그인 불필요)
@app.get("/privacy")
def privacy_page():
    path = os.path.join(FRONTEND_DIR, "privacy.html")
    if os.path.exists(path):
        return FileResponse(path)
    return {"error": "privacy.html not found"}

# 이용약관 (로그인 불필요)
@app.get("/terms")
def terms_page():
    path = os.path.join(FRONTEND_DIR, "terms.html")
    if os.path.exists(path):
        return FileResponse(path)
    return {"error": "terms.html not found"}

# 드릴 가이드 (로그인 불필요)
@app.get("/drill")
def drill_page():
    return _serve("drill.html")

# FAQ (로그인 불필요)
@app.get("/faq")
def faq_page():
    return _serve("faq.html")

# 부상 예방 가이드 (로그인 불필요)
@app.get("/injury")
def injury_page():
    return _serve("injury.html")

# 훈련 플랜 (로그인 불필요)
@app.get("/plan")
def plan_page():
    return _serve("plan.html")

# 뱃지/업적 (로그인 필요)
@app.get("/badges")
def badges_page(request: Request):
    redir = _auth_redirect(request)
    if redir: return redir
    return _serve("badge.html")

# 닉네임 설정 페이지 (소셜 로그인 후 신규 가입 시)
@app.get("/nickname")
def nickname_page():
    return _serve("nickname.html")

def _auth_redirect(request: Request):
    """토큰 미검증 시 login 리디렉트. 검증 통과 시 None 반환."""
    token = request.cookies.get("swimtech_token")
    if not token or not verify_token(token):
        return RedirectResponse(url="/login")
    return None

def _is_admin(request: Request) -> bool:
    """관리자 계정 여부 확인. role='admin' 컬럼 우선, ADMIN_ID는 과도기 호환 폴백."""
    token = request.cookies.get("swimtech_token")
    if not token:
        return False
    from routers.auth import decode_token
    payload = decode_token(token)
    username = payload.get("sub")
    customer_id = payload.get("customer_id")
    if not username:
        return False
    if customer_id:
        try:
            conn = psycopg2.connect(os.getenv("DATABASE_URL", ""))
            cur = conn.cursor()
            cur.execute("SELECT role FROM customers WHERE id = %s", (customer_id,))
            row = cur.fetchone()
            cur.close(); conn.close()
            if row and row[0] == "admin":
                return True
        except Exception:
            pass
    return username == os.getenv("ADMIN_ID", "admin")

def _serve(filename: str):
    path = os.path.join(FRONTEND_DIR, filename)
    if os.path.exists(path):
        return FileResponse(path)
    raise HTTPException(status_code=404, detail=f"{filename} not found")

# 루트 → 홈 선택 화면
@app.get("/")
def serve_home(request: Request):
    redir = _auth_redirect(request)
    if redir: return redir
    return _serve("landing.html")

# 영상 분석 메타 선택 페이지
@app.get("/meta")
def serve_meta(request: Request):  # admin-only
    redir = _auth_redirect(request)
    if redir: return redir
    if not _is_admin(request):
        return RedirectResponse(url="/landing")
    return _serve("meta.html")

# 업로드 페이지
@app.get("/upload")
def serve_upload(request: Request):  # admin-only
    redir = _auth_redirect(request)
    if redir: return redir
    if not _is_admin(request):
        return RedirectResponse(url="/landing")
    return _serve("upload.html")

# 분석 뷰어 페이지
@app.get("/viewer")
def serve_viewer(request: Request):  # admin-only
    redir = _auth_redirect(request)
    if redir: return redir
    if not _is_admin(request):
        return RedirectResponse(url="/landing")
    return _serve("viewer.html")

# 대시보드 페이지
@app.get("/dashboard")
def serve_dashboard(request: Request):
    redir = _auth_redirect(request)
    if redir: return redir
    return _serve("dashboard.html")

# AI 코치 챗봇 페이지
@app.get("/chat")
def serve_chat(request: Request):
    redir = _auth_redirect(request)
    if redir: return redir
    return _serve("chat.html")

# 수영장 찾기 페이지
@app.get("/pool")
def serve_pool(request: Request):
    redir = _auth_redirect(request)
    if redir: return redir
    return templates.TemplateResponse("pool.html", {
        "request": request,
        "kakao_js_key": os.getenv("KAKAO_JS_KEY", ""),
    })

# 온보딩 튜토리얼 페이지
@app.get("/onboarding")
def serve_onboarding(request: Request):
    redir = _auth_redirect(request)
    if redir: return redir
    return _serve("onboarding.html")

# 수영 용어 사전 페이지
@app.get("/glossary")
def serve_glossary(request: Request):
    redir = _auth_redirect(request)
    if redir: return redir
    return _serve("glossary.html")

# 커뮤니티 게시판 (로그인 필요)
@app.get("/community")
def serve_community(request: Request):
    redir = _auth_redirect(request)
    if redir: return redir
    return _serve("community.html")

# 릴리즈 노트 (로그인 불필요)
@app.get("/changelog")
def changelog_page():
    return _serve("changelog.html")

# 월간 성장 리포트 (로그인 필요)
@app.get("/report")
def report_page(request: Request):
    redir = _auth_redirect(request)
    if redir: return redir
    return _serve("report.html")

# 수영 챌린지 (로그인 필요)
@app.get("/challenge")
def challenge_page(request: Request):
    redir = _auth_redirect(request)
    if redir: return redir
    return _serve("challenge.html")

# 장비 가이드 (로그인 불필요)
@app.get("/equipment")
def equipment_page():
    return _serve("equipment.html")

# 피드백 페이지 (로그인 불필요)
@app.get("/feedback")
def feedback_page():
    return _serve("feedback.html")

# 훈련 일지 (로그인 필요)
@app.get("/training-log")
def training_log_page(request: Request):
    redir = _auth_redirect(request)
    if redir: return redir
    return _serve("training_log.html")

# 코치 연동 페이지 (로그인 필요)
@app.get("/coach")
def coach_page(request: Request):
    redir = _auth_redirect(request)
    if redir: return redir
    return _serve("coach.html")

# 수영 영상 큐레이션 (로그인 필요)
@app.get("/videos")
def videos_page(request: Request):
    redir = _auth_redirect(request)
    if redir: return redir
    return _serve("videos.html")

# 공유 결과 페이지 (로그인 불필요)
@app.get("/share/{token}")
def share_page(token: str):
    return _serve("share.html")

# 공유 결과 데이터 API (인증 불필요)
@app.get("/api/share/{token}")
def get_share_data(token: str):
    DATABASE_URL = os.getenv("DATABASE_URL", "")
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("""
            SELECT stroke_type, purpose, analyzed_at,
                   arm_symmetry, kick_count, kick_freq_hz,
                   head_angle_avg, head_rotation_score, overall_score,
                   ai_feedback, drill_recommendations
            FROM analysis_results
            WHERE share_token = %s
        """, (token,))
        row = cur.fetchone()
        cur.close(); conn.close()
        if not row:
            raise HTTPException(404, "공유된 분석 결과를 찾을 수 없습니다.")
        (stroke_type, purpose, analyzed_at, arm_symmetry, kick_count,
         kick_freq_hz, head_angle_avg, head_rotation_score, overall_score,
         ai_feedback, drill_recommendations) = row

        if overall_score is None:
            sym  = float(arm_symmetry or 0)
            head = float(head_rotation_score or 0)
            freq = min(100.0, float(kick_freq_hz or 0) * 20)
            overall_score = round(sym * 0.4 + head * 0.3 + freq * 0.3, 1)

        return {
            "stroke_type":  stroke_type,
            "purpose":      purpose,
            "analyzed_at":  str(analyzed_at) if analyzed_at else None,
            "arm_symmetry": float(arm_symmetry) if arm_symmetry else 0,
            "kick_count":   kick_count or 0,
            "kick_freq_hz": float(kick_freq_hz) if kick_freq_hz else 0,
            "head_angle_avg": float(head_angle_avg) if head_angle_avg else 0,
            "overall_score":  float(overall_score),
            "feedback":     ai_feedback or "",
            "drills":       drill_recommendations or "",
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"DB 오류: {e}")

# 레거시 루트 (기존 index.html 직접 접근용)
@app.get("/app")
def serve_index_legacy(request: Request):
    redir = _auth_redirect(request)
    if redir: return redir
    return _serve("index.html")

# 로컬 영상 파일 스트리밍 (뷰어 페이지에서 video.src로 사용)
@app.get("/api/video-stream/{filename}")
async def stream_video_file(filename: str, request: Request):
    token = request.cookies.get("swimtech_token")
    if not token or not verify_token(token):
        raise HTTPException(status_code=401, detail="Unauthorized")
    # 경로 순회 공격 방지
    safe_name = os.path.basename(filename)
    video_path = os.path.join("/app/video", safe_name)
    if not os.path.exists(video_path):
        raise HTTPException(status_code=404, detail=f"영상 파일 없음: {safe_name}")
    return FileResponse(video_path, media_type="video/mp4", headers={"Accept-Ranges": "bytes"})

# PWA 필수 파일
@app.get("/manifest.json")
def serve_manifest():
    path = os.path.join(FRONTEND_DIR, "manifest.json")
    return FileResponse(path, media_type="application/manifest+json")

@app.get("/sw.js")
def serve_sw():
    path = os.path.join(FRONTEND_DIR, "sw.js")
    return FileResponse(path, media_type="application/javascript")

@app.get("/static/icons/{filename}")
def serve_icon(filename: str):
    safe = os.path.basename(filename)
    path = os.path.join(FRONTEND_DIR, "static", "icons", safe)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Icon not found")
    return FileResponse(path, media_type="image/png")

if os.path.exists(FRONTEND_DIR):
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


# --- SwimTech safe HTTP error messages ---
from fastapi import Request as _SwimTechRequest, HTTPException as _SwimTechHTTPException
from fastapi.responses import JSONResponse as _SwimTechJSONResponse


def _swimtech_looks_mojibake(value):
    if not isinstance(value, str):
        return False

    bad_count = 0
    for ch in value:
        code = ord(ch)
        if ch == "\ufffd" or code == 0x80 or (0x4E00 <= code <= 0x9FFF):
            bad_count += 1

    markers = [
        "\ufffd", "\u5a9b", "\u7b4c", "\u56a5", "\u75ab",
        "\u7374", "\u63f6", "\u938c", "\uf9cf", "\u6f61"
    ]

    return bad_count >= 1 or any(marker in value for marker in markers)


def _swimtech_default_error_message(status_code):
    messages = {
        400: "\uc785\ub825\uac12\uc744 \ud655\uc778\ud574\uc8fc\uc138\uc694.",
        401: "\ub85c\uadf8\uc778\uc774 \ud544\uc694\ud558\uac70\ub098 \uc778\uc99d \uc815\ubcf4\uac00 \uc62c\ubc14\ub974\uc9c0 \uc54a\uc2b5\ub2c8\ub2e4.",
        403: "\uc811\uadfc \uad8c\ud55c\uc774 \uc5c6\uc2b5\ub2c8\ub2e4.",
        404: "\uc694\uccad\ud55c \uc815\ubcf4\ub97c \ucc3e\uc744 \uc218 \uc5c6\uc2b5\ub2c8\ub2e4.",
        409: "\uc774\ubbf8 \uc874\uc7ac\ud558\ub294 \ub370\uc774\ud130\uc785\ub2c8\ub2e4.",
        422: "\uc694\uccad \ud615\uc2dd\uc774 \uc62c\ubc14\ub974\uc9c0 \uc54a\uc2b5\ub2c8\ub2e4.",
        429: "\uc694\uccad\uc774 \ub108\ubb34 \ub9ce\uc2b5\ub2c8\ub2e4. \uc7a0\uc2dc \ud6c4 \ub2e4\uc2dc \uc2dc\ub3c4\ud574\uc8fc\uc138\uc694.",
        500: "\uc11c\ubc84 \uc624\ub958\uac00 \ubc1c\uc0dd\ud588\uc2b5\ub2c8\ub2e4.",
        503: "\uc11c\ube44\uc2a4 \uc124\uc815\uc774 \uc644\ub8cc\ub418\uc9c0 \uc54a\uc558\uc2b5\ub2c8\ub2e4.",
    }
    return messages.get(status_code, "\uc694\uccad\uc744 \ucc98\ub9ac\ud560 \uc218 \uc5c6\uc2b5\ub2c8\ub2e4.")


@app.exception_handler(_SwimTechHTTPException)
async def _swimtech_http_exception_handler(request: _SwimTechRequest, exc: _SwimTechHTTPException):
    detail = exc.detail

    if isinstance(detail, str) and _swimtech_looks_mojibake(detail):
        detail = _swimtech_default_error_message(exc.status_code)

    return _SwimTechJSONResponse(
        status_code=exc.status_code,
        content={"detail": detail},
        headers=getattr(exc, "headers", None),
    )

