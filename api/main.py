import logging
import os
import psycopg2
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from rate_limit import limiter
from routers import videos, customers, analysis, stream, auth, dashboard, sheets, badge
from routers.auth import verify_token

logging.basicConfig(level=logging.INFO)

app = FastAPI(
    title="SwimTech API",
    description="수영 영법 분석 플랫폼 백엔드",
    version="0.1.0"
)

_API_PREFIXES = ("/api/", "/auth/", "/videos/", "/analysis/", "/stream/", "/customers/")

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)


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

app.include_router(auth.router,      prefix="/auth",      tags=["인증"])
app.include_router(videos.router,    prefix="/videos",    tags=["영상"])
app.include_router(customers.router, prefix="/customers", tags=["고객"])
app.include_router(analysis.router,  prefix="/analysis",  tags=["분석"])
app.include_router(stream.router,    prefix="/stream",    tags=["실시간 분석"])
app.include_router(dashboard.router, prefix="/api/dashboard", tags=["대시보드"])
app.include_router(sheets.router,   prefix="/api/sheets",    tags=["Sheets"])
app.include_router(badge.router,    prefix="/api/badges",    tags=["뱃지"])

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
def serve_meta(request: Request):
    redir = _auth_redirect(request)
    if redir: return redir
    return _serve("meta.html")

# 업로드 페이지
@app.get("/upload")
def serve_upload(request: Request):
    redir = _auth_redirect(request)
    if redir: return redir
    return _serve("upload.html")

# 분석 뷰어 페이지
@app.get("/viewer")
def serve_viewer(request: Request):
    redir = _auth_redirect(request)
    if redir: return redir
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
    return _serve("pool.html")

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
