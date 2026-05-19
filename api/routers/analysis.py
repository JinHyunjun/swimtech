import os
import uuid
from fastapi import APIRouter, HTTPException, Request
import psycopg2
from routers.auth import decode_token, verify_token

router = APIRouter()

DATABASE_URL = os.getenv("DATABASE_URL", "")

def get_db():
    return psycopg2.connect(DATABASE_URL)


@router.get("/{video_id}")
def get_analysis(video_id: int):
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT id, customer_id, stroke_type, confidence,
                   left_arm_angle_avg, right_arm_angle_avg,
                   arm_symmetry_score, kick_count, kick_frequency_hz,
                   head_angle_avg, overall_score,
                   ai_feedback, drill_recommendations, created_at
            FROM analysis_results WHERE video_id=%s
            ORDER BY created_at DESC LIMIT 1
        """, (video_id,))
        row = cur.fetchone()
        cur.close(); conn.close()
        if not row:
            raise HTTPException(404, "분석 결과가 없습니다")
        return {
            "id": row[0], "customer_id": row[1],
            "stroke_type": row[2], "confidence": row[3],
            "left_arm_angle_avg": row[4], "right_arm_angle_avg": row[5],
            "arm_symmetry_score": row[6],
            "kick_count": row[7], "kick_frequency_hz": row[8],
            "head_angle_avg": row[9], "overall_score": row[10],
            "feedback": row[11], "drills": row[12],
            "created_at": str(row[13])
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"DB 오류: {e}")


@router.post("/{analysis_id}/share")
def create_share_link(analysis_id: int, request: Request):
    """분석 결과 공유 링크 생성 (JWT 인증 필요)"""
    token_cookie = request.cookies.get("swimtech_token")
    if not token_cookie or not verify_token(token_cookie):
        raise HTTPException(401, "로그인이 필요합니다.")
    payload = decode_token(token_cookie)
    customer_id = payload.get("customer_id")

    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "SELECT customer_id, share_token FROM analysis_results WHERE id=%s",
            (analysis_id,),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "분석 결과가 없습니다.")
        if row[0] != customer_id:
            raise HTTPException(403, "본인의 분석만 공유할 수 있습니다.")

        share_token = row[1]
        if not share_token:
            share_token = uuid.uuid4().hex
            cur.execute(
                "UPDATE analysis_results SET share_token=%s WHERE id=%s",
                (share_token, analysis_id),
            )
            conn.commit()

        cur.close(); conn.close()
        return {"share_url": f"/share/{share_token}"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"DB 오류: {e}")


@router.get("/customer/{customer_id}")
def get_customer_analyses(customer_id: int):
    """고객의 전체 분석 이력 조회"""
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT id, stroke_type, overall_score, kick_count,
                   arm_symmetry_score, created_at
            FROM analysis_results WHERE customer_id=%s
            ORDER BY created_at DESC
        """, (customer_id,))
        rows = cur.fetchall()
        cur.close(); conn.close()
        return {"customer_id": customer_id, "analyses": [
            {"id": r[0], "stroke_type": r[1], "overall_score": r[2],
             "kick_count": r[3], "arm_symmetry_score": r[4],
             "created_at": str(r[5])}
            for r in rows
        ]}
    except Exception as e:
        raise HTTPException(500, f"DB 오류: {e}")
