"""Private loopback web API. No production credentials, database or cloud AI."""
from __future__ import annotations

from contextlib import asynccontextmanager
import json
from pathlib import Path
import secrets
import time
from typing import Literal
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from ..annotation import build_annotation
from ..adjudication import build_review_report
from ..pose_cache import video_sha256
from .service import Workbench, MAX_BYTES, inspect_video, create_preview, save_json, single_review_comparison


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    stroke: Literal["freestyle", "backstroke", "breaststroke", "butterfly"]
    start_sec: float = Field(ge=0)
    end_sec: float = Field(gt=0)
    distance_m: float | None = Field(default=None, gt=0, le=5000)
    roi: list[float] = Field(min_length=4, max_length=4)
    rotation: Literal["none", "clockwise", "counterclockwise"] = "clockwise"


class Label(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    annotator: str = Field(min_length=1, max_length=80)
    arm_events: list[float] = Field(max_length=2000)
    kick_events: list[float] = Field(max_length=2000)
    arm_status: Literal["labeled", "unresolvable"] = "labeled"
    kick_status: Literal["labeled", "unresolvable"] = "labeled"
    never_seen_predictions: bool = False


def create_app(data_dir: Path, *, runner=None) -> FastAPI:
    store = Workbench(data_dir, runner=runner)
    csrf = secrets.token_urlsafe(32)

    @asynccontextmanager
    async def lifespan(app):
        yield
        await run_in_threadpool(store.close)

    app = FastAPI(title="SwimMate Review Lab", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.store = store

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        # Host validation also blocks DNS rebinding into the local workbench.
        if request.url.hostname not in {"127.0.0.1", "localhost", "testserver"}:
            return JSONResponse({"detail": "로컬 PC에서만 사용할 수 있습니다."}, status_code=403)
        origin = request.headers.get("origin")
        if origin and urlsplit(origin).netloc != request.headers.get("host"):
            return JSONResponse({"detail": "다른 사이트의 요청은 허용하지 않습니다."}, status_code=403)
        if request.headers.get("sec-fetch-site") == "cross-site":
            return JSONResponse({"detail": "교차 사이트 요청은 허용하지 않습니다."}, status_code=403)
        if request.method not in {"GET", "HEAD"} and not secrets.compare_digest(request.headers.get("x-review-token", ""), csrf):
            return JSONResponse({"detail": "새로고침 후 다시 시도해 주세요."}, status_code=403)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; "
            "media-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'none'"
        )
        return response

    @app.exception_handler(ValueError)
    async def bad_input(request, error):
        return JSONResponse({"detail": str(error)}, status_code=400)

    @app.exception_handler(FileNotFoundError)
    async def not_found(request, error):
        return JSONResponse({"detail": "영상을 찾을 수 없습니다."}, status_code=404)

    assets = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=assets), name="static")

    @app.get("/")
    def home():
        return FileResponse(assets / "index.html")

    @app.get("/api/session")
    def session():
        return {"token": csrf, "max_bytes": MAX_BYTES, "local_only": True}

    @app.get("/api/videos")
    def videos():
        return store.list()

    @app.post("/api/videos")
    async def upload(request: Request, filename: str = "video.mp4"):
        if len(filename) > 200:
            raise ValueError("파일 이름이 너무 깁니다.")
        size = request.headers.get("content-length")
        if size and (not size.isdigit() or int(size) > MAX_BYTES):
            raise HTTPException(413, "영상은 200MB 이하로 올려 주세요.")
        ident, directory = store.allocate()
        try:
            count = 0
            with (directory / "source.mp4").open("wb") as stream:
                async for chunk in request.stream():
                    count += len(chunk)
                    if count > MAX_BYTES:
                        raise HTTPException(413, "영상은 200MB 이하로 올려 주세요.")
                    stream.write(chunk)
            info = await run_in_threadpool(inspect_video, directory / "source.mp4")
            await run_in_threadpool(create_preview, directory / "source.mp4", info)
            data = dict(id=ident, name=filename.replace("\\", "/").split("/")[-1],
                        created_at=time.time(), state="uploaded", revealed=False, settings=None,
                        preview=True, timeline="source_frame_index_divided_by_fps",
                        sha256=await run_in_threadpool(video_sha256, directory / "source.mp4"), **info)
            save_json(directory / "meta.json", data)
            return data
        except BaseException:
            store.delete(ident)
            raise

    @app.get("/api/videos/{ident}")
    def video(ident: str):
        return store.read(ident)

    @app.delete("/api/videos/{ident}")
    def delete(ident: str):
        store.delete(ident)
        return {"deleted": True}

    @app.post("/api/videos/{ident}/analyze")
    def analyze(ident: str, settings: Settings):
        data = store.read(ident)
        if not settings.start_sec < settings.end_sec <= data["duration"] + .001:
            raise ValueError("분석 시작·종료 시각을 영상 범위 안으로 지정해 주세요.")
        if settings.end_sec - settings.start_sec > 60 or (settings.end_sec - settings.start_sec) * data["fps"] > 7200:
            raise ValueError("한 번에 60초 이하 구간을 분석합니다.")
        x1, y1, x2, y2 = settings.roi
        if not (0 <= x1 < x2 <= 1 and 0 <= y1 < y2 <= 1) or min(x2 - x1, y2 - y1) < .03:
            raise ValueError("선수/레인 영역을 넉넉하게 지정해 주세요.")
        store.start(ident, settings.model_dump())
        return {"state": "queued"}

    @app.post("/api/videos/{ident}/cancel")
    def cancel(ident: str):
        store.cancel(ident)
        return store.read(ident)

    @app.get("/media/{ident}")
    def media(ident: str, request: Request):
        path = store.directory(ident) / "preview.mp4"
        length = path.stat().st_size
        start, end = 0, length - 1
        header = request.headers.get("range")
        if header:
            import re
            match = re.fullmatch(r"bytes=(\d*)-(\d*)", header)
            if not match or not any(match.groups()):
                return JSONResponse({}, status_code=416, headers={"Content-Range": f"bytes */{length}"})
            first, last = match.groups()
            if first:
                start, end = int(first), min(int(last), end) if last else end
            else:
                start = max(0, length - int(last))
            if start > end or start >= length:
                return JSONResponse({}, status_code=416, headers={"Content-Range": f"bytes */{length}"})

        def chunks():
            with path.open("rb") as stream:
                stream.seek(start)
                remaining = end - start + 1
                while remaining:
                    data = stream.read(min(256 * 1024, remaining))
                    if not data:
                        break
                    remaining -= len(data)
                    yield data

        headers = {"Accept-Ranges": "bytes", "Content-Length": str(end - start + 1)}
        if header:
            headers["Content-Range"] = f"bytes {start}-{end}/{length}"
        return StreamingResponse(chunks(), status_code=206 if header else 200, media_type="video/mp4", headers=headers)

    @app.post("/api/videos/{ident}/labels")
    def save_label(ident: str, label: Label):
        with store.lock:
            data = store.read(ident)
            settings = data.get("settings")
            if not settings:
                raise ValueError("분석 구간과 영법부터 지정해 주세요.")
            if any(not settings["start_sec"] <= t < settings["end_sec"] for t in label.arm_events + label.kick_events):
                raise ValueError("이벤트는 분석 구간 [시작, 종료) 안에 있어야 합니다.")
            payload = build_annotation(data["sha256"], settings["stroke"], 1, settings["start_sec"], settings["end_sec"],
                label.arm_events, label.kick_events, label.annotator, video_sha256=data["sha256"],
                arm_label_status=label.arm_status, kick_label_status=label.kick_status)
            if data["revealed"] or not label.never_seen_predictions:
                payload.update(label_mode="prediction_assisted", prediction_visible=True)
            payload["display_filename"] = data["name"]
            payload["review_context"] = {"roi": settings["roi"], "timeline": "source_frame_index_divided_by_fps"}
            path = store.directory(ident) / "label.json"
            # A later assisted edit cannot overwrite the previously saved blind snapshot.
            if payload["label_mode"] == "blinded_manual":
                save_json(path.parent / "blind-label.json", payload)
            save_json(path, payload)
            return payload

    @app.get("/api/videos/{ident}/labels")
    def get_label(ident: str):
        path = store.directory(ident) / "label.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    @app.post("/api/videos/{ident}/reveal")
    def reveal(ident: str):
        with store.lock:
            if store.read(ident)["state"] != "complete":
                raise ValueError("분석이 끝나면 모델 결과를 볼 수 있습니다.")
            store.update(ident, revealed=True)
        return load_comparison(ident)

    def load_comparison(ident: str) -> dict:
        directory = store.directory(ident)
        data = store.read(ident)
        result = json.loads((directory / "result.json").read_text(encoding="utf-8"))
        review = json.loads((directory / "review.json").read_text(encoding="utf-8"))
        label = get_label(ident)
        return {"result": result, "review": review, "comparison": single_review_comparison(
            label, result, data["settings"].get("distance_m")) if label else None}

    @app.get("/api/videos/{ident}/export")
    def export(ident: str):
        data = store.read(ident)
        directory = store.directory(ident)
        payload = {"project": data, "label": get_label(ident)}
        blind = directory / "blind-label.json"
        payload["blind_label"] = json.loads(blind.read_text(encoding="utf-8")) if blind.exists() else None
        if data["revealed"] and data["state"] == "complete":
            comparison = load_comparison(ident)
            comparison["review"].pop("overlays", None)
            payload.update(comparison)
        return JSONResponse(payload, headers={"Content-Disposition": 'attachment; filename="swimmate-review.json"'})

    @app.post("/api/adjudicate")
    async def adjudicate(request: Request):
        raw = await request.body()
        if len(raw) > 1024 * 1024:
            raise HTTPException(413, "라벨 파일이 너무 큽니다.")
        data = json.loads(raw)
        try:
            return build_review_report(data["first"], data["second"])
        except (KeyError, TypeError) as exc:
            raise ValueError("라벨 파일 형식을 확인해 주세요.") from exc

    return app
