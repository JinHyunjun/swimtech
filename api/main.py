import os
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse
from routers import videos, customers, analysis, stream, auth
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

@app.get("/api/health")
def health():
    return {"status": "healthy"}

FRONTEND_DIR = "/app/frontend"

# 로그인 페이지
@app.get("/login")
def login_page():
    path = os.path.join(FRONTEND_DIR, "login.html")
    if os.path.exists(path):
        return FileResponse(path)
    return {"error": "login.html not found"}

# 루트 — 토큰 없으면 로그인 페이지로
@app.get("/")
def serve_index(request: Request):
    token = request.cookies.get("swimtech_token")
    if not token or not verify_token(token):
        return RedirectResponse(url="/login")
    index = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index):
        return FileResponse(index)
    return {"status": "ok", "service": "SwimTech API"}

if os.path.exists(FRONTEND_DIR):
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
