import os, uuid, io
import psycopg2
from fastapi import APIRouter, UploadFile, File, HTTPException
from minio import Minio

router = APIRouter()

minio_client = Minio(
    os.getenv("MINIO_ENDPOINT", "minio:9000"),
    access_key=os.getenv("MINIO_ACCESS_KEY", "minioadmin"),
    secret_key=os.getenv("MINIO_SECRET_KEY", "minioadmin123"),
    secure=False
)

BUCKET       = os.getenv("MINIO_BUCKET",  "swim-videos")
DATABASE_URL = os.getenv("DATABASE_URL",  "")


def _get_db():
    return psycopg2.connect(DATABASE_URL)


@router.post("/upload")
async def upload_video(
    customer_id: int,
    file: UploadFile = File(...)
):
    allowed = {".mp4", ".mov", ".avi", ".mkv"}
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in allowed:
        raise HTTPException(400, f"지원하지 않는 형식: {ext}")

    object_key   = f"uploads/{customer_id}/{uuid.uuid4()}{ext}"
    content      = await file.read()
    file_size_mb = round(len(content) / 1_048_576, 2)

    try:
        if not minio_client.bucket_exists(BUCKET):
            minio_client.make_bucket(BUCKET)
        minio_client.put_object(
            BUCKET, object_key,
            io.BytesIO(content), len(content),
            content_type=file.content_type,
        )
    except Exception as e:
        raise HTTPException(500, f"스토리지 저장 실패: {e}")

    # videos 테이블에 레코드 생성 → video_id 확보
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
            (customer_id, file.filename, object_key, file_size_mb),
        )
        video_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        raise HTTPException(500, f"DB 저장 실패: {e}")

    # Celery 분석 태스크 등록 (video_id 함께 전달)
    from tasks.analyze import run_analysis
    task = run_analysis.delay(object_key, customer_id, video_id)

    # task_id를 videos 테이블에 기록
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
