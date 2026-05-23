"""
Celery 비동기 작업 태스크
1. MinIO에서 영상 다운로드
2. pose.analyze_video() 실행 (env + stroke_type 전달 → 전처리/보간 적용)
3. classifier.classify_stroke() 실행
4. 결과 PostgreSQL 저장
5. 오버레이 영상 MinIO 업로드
"""
import os, tempfile
from worker import app as celery_app
from minio import Minio
import psycopg2

MINIO_ENDPOINT  = os.getenv("MINIO_ENDPOINT",  "minio:9000")
MINIO_ACCESS    = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET    = os.getenv("MINIO_SECRET_KEY", "minioadmin123")
MINIO_BUCKET    = os.getenv("MINIO_BUCKET",     "swim-videos")
DATABASE_URL    = os.getenv("DATABASE_URL", "")


def get_minio():
    return Minio(MINIO_ENDPOINT, access_key=MINIO_ACCESS,
                 secret_key=MINIO_SECRET, secure=False)

def get_db():
    return psycopg2.connect(DATABASE_URL)


# ── 영법 문자열 정규화 ──────────────────────────────────────────────────────
# 프론트엔드에서 넘어오는 한글/영문 영법값 → pose.py stroke_type 키로 변환
_STROKE_MAP = {
    # 한글
    "자유형": "freestyle",
    "배영":   "backstroke",
    "평영":   "breaststroke",
    "접영":   "butterfly",
    "스타트": "freestyle",
    "플립턴": "freestyle",
    "터치턴": "freestyle",
    # 영문 (이미 올바른 경우)
    "freestyle":    "freestyle",
    "backstroke":   "backstroke",
    "breaststroke": "breaststroke",
    "butterfly":    "butterfly",
}

# 촬영 환경 문자열 정규화
# 프론트엔드 선택값 → pose.py preprocess_frame env 키로 변환
_ENV_MAP = {
    "수중":     "수중",
    "수면위":   "수면위",
    "실내":     "실내",
    "실외":     "실외",
    "자유수영": "실내",
    "강습":     "실내",
    "훈련":     "실내",
    "대회":     "수면위",
    "드릴":          "실내",
    "free_swim":     "실내",
    "lesson":        "실내",
    "training":      "실내",
    "competition_env": "수면위",
    "drill":         "실내",
}


@celery_app.task(name="tasks.analyze.run_analysis", bind=True, max_retries=3)
def run_analysis(
    self,
    object_key: str,
    customer_id: int,
    video_id: int,
    stroke_type: str = "freestyle",   # 프론트에서 선택한 영법
    env: str = "default",             # 프론트에서 선택한 촬영 환경
    purpose: str = "",                # 프론트에서 선택한 수영 목적
):
    """
    영상 분석 메인 태스크

    Args:
        object_key:   MinIO 오브젝트 키
        customer_id:  사용자 ID
        video_id:     videos 테이블 ID
        stroke_type:  영법 (자유형/배영/평영/접영 등)
        env:          촬영 환경 (수중/수면위/실내/실외 등)
        purpose:      수영 목적 (record/health/technique/competition/hobby)
    """
    try:
        minio = get_minio()

        # ── 영법/환경 정규화 ──
        normalized_stroke = _STROKE_MAP.get(stroke_type, "freestyle")
        normalized_env    = _ENV_MAP.get(env, "default")

        # ── 1. 영상 임시 다운로드 ─────────────────────────────────────
        with tempfile.TemporaryDirectory() as tmpdir:
            local_input  = os.path.join(tmpdir, "input.mp4")
            local_output = os.path.join(tmpdir, "output.mp4")

            minio.fget_object(MINIO_BUCKET, object_key, local_input)

            # ── 2. 포즈 분석 (전처리 + 보간 적용) ────────────────────
            import sys
            sys.path.insert(0, "/app/analysis")
            from pose import analyze_video
            from classifier import classify_stroke, generate_rule_based_feedback

            summary = analyze_video(
                local_input,
                output_path=local_output,
                env=normalized_env,          # CLAHE 전처리 파라미터 분기
                stroke_type=normalized_stroke,  # KickDetector 영법 분기
            )

            # ── 3. 영법 분류 ──────────────────────────────────────────
            classification = classify_stroke(summary.frame_metrics)

            # ── 4. 오버레이 영상 업로드 ───────────────────────────────
            result_key = object_key.replace("uploads/", "results/").replace(".mp4", "_analyzed.mp4")
            minio.fput_object(MINIO_BUCKET, result_key, local_output,
                              content_type="video/mp4")

            # ── 5. PostgreSQL 저장 ────────────────────────────────────
            conn = get_db()
            cur  = conn.cursor()

            # purpose가 없으면 DB에서 조회
            if not purpose:
                cur.execute("SELECT goal FROM customers WHERE id = %s", (customer_id,))
                row     = cur.fetchone()
                purpose = row[0] if row else ""

            feedback_data = generate_rule_based_feedback(
                summary,
                classification.stroke_type,
                purpose=purpose,
                frame_metrics=summary.frame_metrics,
            )

            # analysis_results INSERT
            cur.execute("""
                INSERT INTO analysis_results (
                    video_id, customer_id,
                    stroke_type, confidence,
                    purpose, context,
                    l_elbow_avg, r_elbow_avg,
                    l_elbow_min, r_elbow_min,
                    arm_symmetry,
                    kick_count, kick_freq_hz,
                    head_angle_avg, head_rotation_score,
                    overall_score,
                    ai_feedback, drill_recommendations, youtube_recommendations,
                    analysis_duration_sec
                ) VALUES (
                    %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s
                ) RETURNING id
            """, (
                video_id, customer_id,
                classification.stroke_type, classification.confidence,
                purpose, classification.reason,
                summary.left_arm_angle_avg,  summary.right_arm_angle_avg,
                summary.left_arm_angle_min,  summary.right_arm_angle_min,
                summary.arm_symmetry_score,
                summary.kick_count, summary.kick_frequency_hz,
                summary.head_angle_avg, summary.head_rotation_score,
                summary.overall_score,
                feedback_data["feedback"],
                str(feedback_data["drills"]),
                str(feedback_data["youtube_queries"]),
                int(summary.duration_sec),
            ))

            analysis_id = cur.fetchone()[0]

            # frame_metrics 배치 INSERT (10프레임 간격으로 샘플링)
            batch = []
            for m in summary.frame_metrics[::10]:
                batch.append((
                    video_id,
                    m.frame_number, m.timestamp_sec,
                    m.left_elbow_angle,    m.right_elbow_angle,
                    m.left_shoulder_angle, m.right_shoulder_angle,
                    m.head_angle, m.body_roll, m.kick_detected,
                ))

            cur.executemany("""
                INSERT INTO frame_metrics (
                    video_id, frame_number, timestamp_sec,
                    l_elbow_angle, r_elbow_angle,
                    l_shoulder_angle, r_shoulder_angle,
                    head_angle, body_roll, kick_detected
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, batch)

            # videos 테이블 상태 업데이트
            cur.execute(
                "UPDATE videos SET status = 'done', minio_result_key = %s,"
                " duration_sec = %s, processed_at = NOW() WHERE id = %s",
                (result_key, int(summary.duration_sec), video_id),
            )

            conn.commit()
            cur.close()
            conn.close()

            return {
                "status":           "done",
                "analysis_id":      analysis_id,
                "video_id":         video_id,
                "stroke_type":      classification.stroke_type,
                "overall_score":    summary.overall_score,
                "kick_count":       summary.kick_count,
                "result_video_key": result_key,
                "feedback":         feedback_data["feedback"],
                # 보간 통계 (디버깅용)
                "interpolated_frames": getattr(summary, "interpolated_frames", 0),
                "analyzed_frames":     summary.analyzed_frames,
                "total_frames":        summary.total_frames,
            }

    except Exception as exc:
        # videos 테이블을 failed로 표시
        try:
            conn = get_db()
            cur  = conn.cursor()
            cur.execute("UPDATE videos SET status = 'failed' WHERE id = %s", (video_id,))
            conn.commit()
            cur.close()
            conn.close()
        except Exception:
            pass
        raise self.retry(exc=exc, countdown=10)
