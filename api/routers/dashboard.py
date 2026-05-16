# -*- coding: utf-8 -*-
import os
from fastapi import APIRouter, HTTPException, Cookie
import psycopg2

from routers.auth import verify_token

router = APIRouter()

DATABASE_URL = os.getenv("DATABASE_URL", "")


def get_db():
    return psycopg2.connect(DATABASE_URL)


def _require_auth(swimtech_token: str | None):
    if not swimtech_token or not verify_token(swimtech_token):
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")


@router.get("/summary")
def dashboard_summary(swimtech_token: str = Cookie(default=None)):
    _require_auth(swimtech_token)
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT id, customer_id, stroke_type, overall_score,
                   l_elbow_avg, r_elbow_avg,
                   arm_symmetry, kick_count, kick_freq_hz,
                   head_angle_avg, analyzed_at
            FROM analysis_results
            ORDER BY analyzed_at ASC
        """)
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return {
            "analyses": [
                {
                    "id": r[0],
                    "customer_id": r[1],
                    "stroke_type": r[2],
                    "overall_score": r[3],
                    "l_elbow_avg": r[4],
                    "r_elbow_avg": r[5],
                    "arm_symmetry": r[6],
                    "kick_count": r[7],
                    "kick_freq_hz": r[8],
                    "head_angle_avg": r[9],
                    "analyzed_at": str(r[10]),
                }
                for r in rows
            ]
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"DB 오류: {e}")


@router.get("/frames/{analysis_id}")
def dashboard_frames(analysis_id: int, swimtech_token: str = Cookie(default=None)):
    _require_auth(swimtech_token)
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT id, frame_number, timestamp_sec,
                   left_elbow_angle, right_elbow_angle,
                   hip_angle, shoulder_angle,
                   body_roll_angle, kick_detected
            FROM frame_metrics
            WHERE analysis_id = %s
            ORDER BY frame_number ASC
        """, (analysis_id,))
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return {
            "analysis_id": analysis_id,
            "frames": [
                {
                    "id": r[0],
                    "frame_number": r[1],
                    "timestamp_sec": r[2],
                    "left_elbow_angle": r[3],
                    "right_elbow_angle": r[4],
                    "hip_angle": r[5],
                    "shoulder_angle": r[6],
                    "body_roll_angle": r[7],
                    "kick_detected": r[8],
                }
                for r in rows
            ],
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"DB 오류: {e}")
