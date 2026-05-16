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
import psycopg2

router = APIRouter()

MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "minio:9000")
MINIO_ACCESS   = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET   = os.getenv("MINIO_SECRET_KEY", "minioadmin123")
MINIO_BUCKET   = os.getenv("MINIO_BUCKET", "swim-videos")
DATABASE_URL   = os.getenv("DATABASE_URL", "")

def get_minio():
    return Minio(MINIO_ENDPOINT, access_key=MINIO_ACCESS,
                 secret_key=MINIO_SECRET, secure=False)

def get_db():
    return psycopg2.connect(DATABASE_URL)


def sse(data: dict) -> str:
    """SSE 포맷으로 직렬화"""
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def analyze_stream(video_path: str, forced_stroke: str = "", context: str = "", purpose: str = "",
                   video_id: int = 0, customer_id: int = 0):
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

    # 목적별 추가 피드백
    purpose_feedback = {
        "record":      "📊 기록 단축 목적: 스트로크 수 줄이기와 발차기 효율에 집중하세요. 턴 동작도 함께 점검하면 좋습니다.",
        "health":      "💪 건강 수영 목적: 좌우 대칭 유지와 불필요한 힘 빼기가 핵심입니다. 호흡 리듬을 일정하게 유지하세요.",
        "technique":   "🎯 영법 교정 목적: 기본기 각도를 이상적인 수치와 비교했습니다. 반복 드릴로 근육 기억을 만들어주세요.",
        "competition": "🏆 대회 준비 목적: 스타트·턴·피니시 구간 분석도 추가로 필요합니다. 레이스 페이스 유지 훈련을 병행하세요.",
        "hobby":       "😊 취미 수영 목적: 부상 위험 자세를 중점 점검했습니다. 무리 없이 즐기는 것이 가장 중요합니다.",
    }.get(purpose, "")

    if purpose_feedback:
        feedback["feedback"] = purpose_feedback + "\n\n" + feedback["feedback"]

    # ── DB 저장 ────────────────────────────────────────────────────────
    try:
        conn = get_db()
        cur  = conn.cursor()

        # video 레코드 없으면 자동 생성
        vid = video_id
        if vid == 0:
            cur.execute(
                "INSERT INTO videos (original_filename, status, duration_sec, processed_at)"
                " VALUES (%s, 'done', %s, NOW()) RETURNING id",
                (os.path.basename(video_path), int(duration)),
            )
            vid = cur.fetchone()[0]
        else:
            cur.execute(
                "UPDATE videos SET status='done', duration_sec=%s, processed_at=NOW() WHERE id=%s",
                (int(duration), vid),
            )

        cid = customer_id if customer_id else None

        l_min = round(float(min(l_elbows)), 2) if l_elbows else None
        r_min = round(float(min(r_elbows)), 2) if r_elbows else None

        cur.execute("""
            INSERT INTO analysis_results (
                video_id, customer_id,
                stroke_type, confidence,
                purpose, context,
                l_elbow_avg, r_elbow_avg,
                l_elbow_min, r_elbow_min,
                arm_symmetry,
                kick_count, kick_freq_hz,
                head_angle_avg,
                ai_feedback, drill_recommendations,
                analysis_duration_sec
            ) VALUES (
                %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s
            ) RETURNING id
        """, (
            vid, cid,
            classification.stroke_type, classification.confidence,
            purpose or None, context or None,
            summary_data.get("left_arm_angle_avg"),  summary_data.get("right_arm_angle_avg"),
            l_min, r_min,
            summary_data.get("arm_symmetry_score"),
            summary_data.get("kick_count"),           summary_data.get("kick_frequency_hz"),
            summary_data.get("head_angle_avg"),
            feedback.get("feedback"),
            str(feedback.get("drills", [])),
            int(duration),
        ))
        cur.fetchone()  # analysis_id (필요 시 활용 가능)

        # frame_metrics 배치 INSERT (10프레임 간격)
        batch = [
            (
                vid,
                m.frame_number, m.timestamp_sec,
                m.left_elbow_angle,    m.right_elbow_angle,
                m.left_shoulder_angle, m.right_shoulder_angle,
                m.head_angle, m.body_roll, m.kick_detected,
            )
            for m in frame_metrics[::10]
            if m.landmarks_visible
        ]
        if batch:
            cur.executemany("""
                INSERT INTO frame_metrics (
                    video_id, frame_number, timestamp_sec,
                    l_elbow_angle, r_elbow_angle,
                    l_shoulder_angle, r_shoulder_angle,
                    head_angle, body_roll, kick_detected
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, batch)

        conn.commit()
        cur.close()
        conn.close()
    except Exception as _db_err:
        # DB 저장 실패는 스트리밍 결과에 영향 주지 않음
        print(f"[stream] DB 저장 실패: {_db_err}", flush=True)
    # ───────────────────────────────────────────────────────────────────

    yield sse({
        "type":          "done",
        "stroke_type":   classification.stroke_type,
        "context":       context,
        "purpose":       purpose,
        "confidence":    classification.confidence,
        "reason":        classification.reason,
        # 개선된 피드백 구조 (강점 + 개선점 + 상세 설명)
        "feedback":      feedback.get("feedback", ""),
        "strengths":     feedback.get("strengths", []),
        "improvements":  feedback.get("improvements", []),
        "drills":        feedback.get("drills", []),
        "stroke_name":   feedback.get("stroke_name", ""),
        **summary_data,
    })


@router.get("/analyze")
def stream_analyze(video_key: str = "", local_path: str = "", forced_stroke: str = "",
                   context: str = "", purpose: str = "",
                   video_id: int = 0, customer_id: int = 0):
    """
    video_key  : MinIO object key (Docker 환경)
    local_path : 로컬 파일 경로 (개발/테스트용)
    video_id   : 기존 videos 레코드 ID (0이면 자동 생성)
    customer_id: 고객 ID (없으면 NULL)
    """
    def generator():
        if local_path:
            yield from analyze_stream(local_path, forced_stroke=forced_stroke,
                                      context=context, purpose=purpose,
                                      video_id=video_id, customer_id=customer_id)

        elif video_key:
            minio = get_minio()
            with tempfile.TemporaryDirectory() as tmpdir:
                local = os.path.join(tmpdir, "input.mp4")
                minio.fget_object(MINIO_BUCKET, video_key, local)
                yield from analyze_stream(local, forced_stroke=forced_stroke,
                                          context=context, purpose=purpose,
                                          video_id=video_id, customer_id=customer_id)
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
