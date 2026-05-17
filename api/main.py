import os
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse
from routers import videos, customers, analysis, stream, auth, dashboard
from routers.auth import verify_token

app = FastAPI(
    title="SwimTech API",
    description="수영 영법 분석 플랫폼 백엔드",
    version="0.1.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

app.include_router(auth.router,      prefix="/auth",      tags=["인증"])
app.include_router(videos.router,    prefix="/videos",    tags=["영상"])
app.include_router(customers.router, prefix="/customers", tags=["고객"])
app.include_router(analysis.router,  prefix="/analysis",  tags=["분석"])
app.include_router(stream.router,    prefix="/stream",    tags=["실시간 분석"])
app.include_router(dashboard.router, prefix="/api/dashboard", tags=["대시보드"])

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

if os.path.exists(FRONTEND_DIR):
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
