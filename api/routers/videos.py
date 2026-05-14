import os, uuid
from fastapi import APIRouter, UploadFile, File, HTTPException
from minio import Minio

router = APIRouter()

minio_client = Minio(
    os.getenv("MINIO_ENDPOINT", "minio:9000"),
    access_key=os.getenv("MINIO_ACCESS_KEY", "minioadmin"),
    secret_key=os.getenv("MINIO_SECRET_KEY", "minioadmin123"),
    secure=False
)

BUCKET = os.getenv("MINIO_BUCKET", "swim-videos")

@router.post("/upload")
async def upload_video(
    customer_id: int,
    file: UploadFile = File(...)
):
    # 확장자 검사
    allowed = {".mp4", ".mov", ".avi", ".mkv"}
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in allowed:
        raise HTTPException(400, f"지원하지 않는 형식: {ext}")

    # MinIO에 업로드
    object_key = f"uploads/{customer_id}/{uuid.uuid4()}{ext}"
    content = await file.read()

    try:
        if not minio_client.bucket_exists(BUCKET):
            minio_client.make_bucket(BUCKET)

        import io
        minio_client.put_object(
            BUCKET, object_key,
            io.BytesIO(content), len(content),
            content_type=file.content_type
        )
    except Exception as e:
        raise HTTPException(500, f"스토리지 저장 실패: {e}")

    # Celery 분석 태스크 등록
    from tasks.analyze import run_analysis
    task = run_analysis.delay(object_key, customer_id)

    return {
        "status": "uploaded",
        "object_key": object_key,
        "task_id": task.id,
        "message": "분석이 시작되었습니다. task_id로 진행 상황을 확인하세요."
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
