import io
import logging
import os
import re
import uuid

import psycopg2
from fastapi import APIRouter, UploadFile, File, HTTPException
from minio import Minio

router = APIRouter()
logger = logging.getLogger(__name__)

minio_client = Minio(
    os.getenv("MINIO_ENDPOINT", "minio:9000"),
    access_key=os.getenv("MINIO_ACCESS_KEY", "minioadmin"),
    secret_key=os.getenv("MINIO_SECRET_KEY", "minioadmin123"),
    secure=False
)

BUCKET       = os.getenv("MINIO_BUCKET",  "swim-videos")
DATABASE_URL = os.getenv("DATABASE_URL",  "")

ALLOWED_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
MAX_FILE_SIZE      = 500 * 1024 * 1024  # 500 MB

_UNSAFE_CHARS = re.compile(r'[^a-zA-Z0-9가-힣_\-]')


def _get_db():
    return psycopg2.connect(DATABASE_URL)


def _sanitize_filename(filename: str) -> str:
    name, ext = os.path.splitext(filename)
    safe = _UNSAFE_CHARS.sub("_", name)
    return (safe or "upload") + ext.lower()


@router.post("/upload")
async def upload_video(
    customer_id: int,
    stroke_type: str = "freestyle",
    env: str = "default",
    purpose: str = "",
    file: UploadFile = File(...)
):
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, "허용되지 않는 파일 형식입니다. (mp4, mov, avi, mkv, webm)")

    mime = (file.content_type or "").lower()
    if not mime.startswith("video/"):
        raise HTTPException(400, "비디오 파일만 업로드할 수 있습니다.")

    content = await file.read()

    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(400, "파일 크기는 500MB를 초과할 수 없습니다.")

    safe_name    = _sanitize_filename(file.filename or "upload.mp4")
    safe_ext     = os.path.splitext(safe_name)[1]
    object_key   = f"uploads/{customer_id}/{uuid.uuid4()}{safe_ext}"
    file_size_mb = round(len(content) / 1_048_576, 2)

    try:
        if not minio_client.bucket_exists(BUCKET):
            minio_client.make_bucket(BUCKET)
        minio_client.put_object(
            BUCKET, object_key,
            io.BytesIO(content), len(content),
            content_type=file.content_type,
        )
    except Exception:
        logger.error("upload: MinIO error", exc_info=True)
        raise HTTPException(500, "스토리지 저장에 실패했습니다.")

    try:
        conn = _get_db()
        cur  = conn.cursor()
        cur.execute(
            """
            INSERT INTO videos (customer_id, original_filename, minio_object_key,
                                file_size_mb, status)
            VALUES (%s, %s, %s, %s, 'uploaded')
            RETURNING id
            """,
            (customer_id, safe_name, object_key, file_size_mb),
        )
        video_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        conn.close()
    except Exception:
        logger.error("upload: DB insert error", exc_info=True)
        raise HTTPException(500, "영상 정보 저장에 실패했습니다.")

    from tasks.analyze import run_analysis
    task = run_analysis.delay(object_key, customer_id, video_id, stroke_type, env, purpose)

    try:
        conn = _get_db()
        cur  = conn.cursor()
        cur.execute(
            "UPDATE videos SET task_id = %s, status = 'processing' WHERE id = %s",
            (task.id, video_id),
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception:
        pass  # task_id 기록 실패는 분석에 영향 없음

    return {
        "status":     "uploaded",
        "video_id":   video_id,
        "object_key": object_key,
        "task_id":    task.id,
        "message":    "분석이 시작되었습니다. task_id로 진행 상황을 확인하세요.",
    }


@router.get("/task/{task_id}")
def get_task_status(task_id: str):
    from worker import app as celery_app
    result = celery_app.AsyncResult(task_id)
    return {
        "task_id": task_id,
        "status": result.status,
        "result": result.result if result.ready() else None
    }
