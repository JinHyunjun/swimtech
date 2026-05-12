"""
SwimTech — 실시간 분석 스트리밍 엔드포인트
GET /stream/analyze?video_key=uploads/1/xxx.mp4
→ Server-Sent Events로 프레임별 분석 결과 실시간 전송
"""
import os, sys, json, asyncio
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from minio import Minio
import tempfile

router = APIRouter()

MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "minio:9000")
MINIO_ACCESS   = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET   = os.getenv("MINIO_SECRET_KEY", "minioadmin123")
MINIO_BUCKET   = os.getenv("MINIO_BUCKET", "swim-videos")

def get_minio():
    return Minio(MINIO_ENDPOINT, access_key=MINIO_ACCESS,
                 secret_key=MINIO_SECRET, secure=False)


def sse(data: dict) -> str:
    """SSE 포맷으로 직렬화"""
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def analyze_stream(video_path: str, forced_stroke: str = "", context: str = ""):
    """
    pose.py의 분석 로직을 프레임 단위로 yield
    → SSE 제너레이터
    """
    sys.path.insert(0, "/app/analysis")
    import cv2
    import numpy as np
    import mediapipe as mp
    from mediapipe.tasks import python as mp_python
    from mediapipe.tasks.python.vision import PoseLandmarker, PoseLandmarkerOptions, RunningMode
    from pose import (
        _ensure_model, MODEL_PATH, LM,
        calc_angle, lm_xy, KickDetector,
        AnalysisSummary
    )
    from classifier import classify_stroke, generate_rule_based_feedback
    from pose import FrameMetric

    _ensure_model()

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        yield sse({"type": "error", "message": "영상을 열 수 없습니다"})
        return

    fps          = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration     = round(total_frames / fps, 2)

    yield sse({"type": "meta", "fps": fps,
               "total_frames": total_frames, "duration": duration})

    kick_detector  = KickDetector()
    frame_metrics  = []
    l_elbows, r_elbows, head_angles = [], [], []
    kick_count = 0

    options = PoseLandmarkerOptions(
        base_options=mp_python.BaseOptions(model_asset_path=MODEL_PATH),
        running_mode=RunningMode.VIDEO,
        num_poses=1,
        min_pose_detection_confidence=0.5,
        min_pose_presence_confidence=0.5,
        min_tracking_confidence=0.5,
    )

    with PoseLandmarker.create_from_options(options) as landmarker:
        frame_num = 0
        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break

            timestamp_ms = int(frame_num / fps * 1000)
            rgb      = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            result   = landmarker.detect_for_video(mp_image, timestamp_ms)

            payload = {
                "type": "frame",
                "frame": frame_num,
                "timestamp": round(frame_num / fps, 3),
                "landmarks_visible": False,
            }

            fm = FrameMetric(frame_number=frame_num,
                             timestamp_sec=round(frame_num / fps, 3))

            if result.pose_landmarks and len(result.pose_landmarks) > 0:
                lms = result.pose_landmarks[0]
                fm.landmarks_visible = True

                l_elbow    = calc_angle(lm_xy(lms,LM.LEFT_SHOULDER),  lm_xy(lms,LM.LEFT_ELBOW),    lm_xy(lms,LM.LEFT_WRIST))
                r_elbow    = calc_angle(lm_xy(lms,LM.RIGHT_SHOULDER), lm_xy(lms,LM.RIGHT_ELBOW),   lm_xy(lms,LM.RIGHT_WRIST))
                l_shoulder = calc_angle(lm_xy(lms,LM.LEFT_HIP),       lm_xy(lms,LM.LEFT_SHOULDER), lm_xy(lms,LM.LEFT_ELBOW))
                r_shoulder = calc_angle(lm_xy(lms,LM.RIGHT_HIP),      lm_xy(lms,LM.RIGHT_SHOULDER),lm_xy(lms,LM.RIGHT_ELBOW))
                head_angle = calc_angle(lm_xy(lms,LM.LEFT_EAR),       lm_xy(lms,LM.NOSE),          lm_xy(lms,LM.RIGHT_EAR))
                kicked     = kick_detector.update(lms[LM.LEFT_ANKLE].y, lms[LM.RIGHT_ANKLE].y)

                if kicked:
                    kick_count += 1

                fm.left_elbow_angle     = round(l_elbow,    2)
                fm.right_elbow_angle    = round(r_elbow,    2)
                fm.left_shoulder_angle  = round(l_shoulder, 2)
                fm.right_shoulder_angle = round(r_shoulder, 2)
                fm.head_angle           = round(head_angle, 2)
                fm.kick_detected        = kicked

                l_elbows.append(l_elbow)
                r_elbows.append(r_elbow)
                head_angles.append(head_angle)

                # 스켈레톤 좌표 (정규화 0~1)
                skeleton = {
                    idx: {"x": round(lms[idx].x, 4), "y": round(lms[idx].y, 4)}
                    for idx in [
                        LM.NOSE,
                        LM.LEFT_SHOULDER,  LM.RIGHT_SHOULDER,
                        LM.LEFT_ELBOW,     LM.RIGHT_ELBOW,
                        LM.LEFT_WRIST,     LM.RIGHT_WRIST,
                        LM.LEFT_HIP,       LM.RIGHT_HIP,
                        LM.LEFT_ANKLE,     LM.RIGHT_ANKLE,
                    ]
                }

                payload.update({
                    "landmarks_visible": True,
                    "left_elbow_angle":  round(l_elbow,    2),
                    "right_elbow_angle": round(r_elbow,    2),
                    "head_angle":        round(head_angle, 2),
                    "kick_detected":     kicked,
                    "kick_count":        kick_count,
                    "skeleton":          skeleton,
                    "progress":          round(frame_num / total_frames * 100, 1),
                })

            frame_metrics.append(fm)

            # 매 프레임 전송 (30fps면 너무 많으니 3프레임마다)
            if frame_num % 3 == 0:
                yield sse(payload)

            frame_num += 1

    cap.release()

    # ── 최종 요약 전송 ──────────────────────────────
    from classifier import classify_stroke, generate_rule_based_feedback

    # 사용자가 직접 선택한 영법이 있으면 우선 적용
    if forced_stroke and forced_stroke != "unknown":
        class ForcedClassification:
            stroke_type = forced_stroke
            confidence  = 100.0
            reason      = "사용자 직접 선택"
        classification = ForcedClassification()
    else:
        classification = classify_stroke(frame_metrics)
    summary_data = {}

    if l_elbows:
        l_avg = round(float(np.mean(l_elbows)), 2)
        r_avg = round(float(np.mean(r_elbows)), 2)
        diff  = abs(l_avg - r_avg)
        summary_data = {
            "left_arm_angle_avg":  l_avg,
            "right_arm_angle_avg": r_avg,
            "arm_symmetry_score":  round(max(0, 100 - diff * 2), 2),
            "kick_count":          kick_count,
            "kick_frequency_hz":   round(kick_count / duration, 3) if duration > 0 else 0,
            "head_angle_avg":      round(float(np.mean(head_angles)), 2) if head_angles else 0,
        }

    feedback = generate_rule_based_feedback(
        type("S", (), summary_data)(),
        classification.stroke_type
    )

    yield sse({
        "type": "done",
        "stroke_type":   classification.stroke_type,
        "context":       context,
        "confidence":    classification.confidence,
        "reason":        classification.reason,
        "feedback":      feedback["feedback"],
        "drills":        feedback["drills"],
        **summary_data,
    })


@router.get("/analyze")
def stream_analyze(video_key: str = "", local_path: str = "", forced_stroke: str = "", context: str = ""):
    """
    video_key : MinIO object key (Docker 환경)
    local_path: 로컬 파일 경로 (개발/테스트용)
    """
    def generator():
        if local_path:
            # 로컬 파일 직접 분석 (테스트용)
            yield from analyze_stream(local_path, forced_stroke=forced_stroke, context=context)

        elif video_key:
            # MinIO에서 다운로드 후 분석
            minio = get_minio()
            with tempfile.TemporaryDirectory() as tmpdir:
                local = os.path.join(tmpdir, "input.mp4")
                minio.fget_object(MINIO_BUCKET, video_key, local)
                yield from analyze_stream(local)
        else:
            yield sse({"type": "error", "message": "video_key 또는 local_path 필요"})

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # nginx 버퍼링 비활성화
        }
    )
