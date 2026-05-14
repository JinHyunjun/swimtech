"""
Celery 비동기 태스크
1. MinIO에서 영상 다운로드
2. pose.analyze_video() 실행
3. classifier.classify_stroke() 실행
4. 결과 PostgreSQL 저장
5. 오버레이 영상 MinIO 재업로드
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


@celery_app.task(name="tasks.analyze.run_analysis", bind=True, max_retries=3)
def run_analysis(self, object_key: str, customer_id: int):
    """
    영상 분석 메인 태스크
    """
    try:
        minio = get_minio()

        # ── 1. 영상 임시 다운로드 ─────────────────────
        with tempfile.TemporaryDirectory() as tmpdir:
            local_input  = os.path.join(tmpdir, "input.mp4")
            local_output = os.path.join(tmpdir, "output.mp4")

            minio.fget_object(MINIO_BUCKET, object_key, local_input)

            # ── 2. 포즈 분석 ──────────────────────────
            import sys
            sys.path.insert(0, "/app/analysis")
            from pose import analyze_video
            from classifier import classify_stroke, generate_rule_based_feedback

            summary = analyze_video(local_input, output_path=local_output)

            # ── 3. 영법 분류 ──────────────────────────
            classification = classify_stroke(summary.frame_metrics)
            feedback_data  = generate_rule_based_feedback(summary, classification.stroke_type)

            # ── 4. 오버레이 영상 업로드 ───────────────
            result_key = object_key.replace("uploads/", "results/").replace(".mp4", "_analyzed.mp4")
            minio.fput_object(MINIO_BUCKET, result_key, local_output,
                              content_type="video/mp4")

            # ── 5. PostgreSQL 저장 ────────────────────
            conn = get_db()
            cur  = conn.cursor()

            cur.execute("""
                INSERT INTO analysis_results (
                    customer_id,
                    stroke_type, confidence,
                    left_arm_angle_avg, right_arm_angle_avg,
                    left_arm_angle_min, right_arm_angle_min,
                    arm_symmetry_score,
                    kick_count, kick_frequency_hz,
                    head_angle_avg, head_rotation_score,
                    overall_score,
                    ai_feedback, drill_recommendations, youtube_recommendations,
                    analysis_duration_sec
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s
                ) RETURNING id
            """, (
                customer_id,
                classification.stroke_type, classification.confidence,
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

            # 프레임 상세 데이터 배치 저장 (10프레임 간격으로 축약)
            batch = []
            for m in summary.frame_metrics[::10]:
                batch.append((
                    analysis_id,
                    m.frame_number, m.timestamp_sec,
                    m.left_elbow_angle,  m.right_elbow_angle,
                    m.left_shoulder_angle, m.right_shoulder_angle,
                    m.head_angle, m.kick_detected
                ))

            cur.executemany("""
                INSERT INTO frame_metrics (
                    video_id, frame_number, timestamp_sec,
                    left_elbow_angle, right_elbow_angle,
                    left_shoulder_angle, right_shoulder_angle,
                    head_angle, kick_detected
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, batch)

            conn.commit()
            cur.close()
            conn.close()

            return {
                "status": "done",
                "analysis_id": analysis_id,
                "stroke_type": classification.stroke_type,
                "overall_score": summary.overall_score,
                "kick_count": summary.kick_count,
                "result_video_key": result_key,
                "feedback": feedback_data["feedback"],
            }

    except Exception as exc:
        raise self.retry(exc=exc, countdown=10)
