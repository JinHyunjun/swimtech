# -*- coding: utf-8 -*-
"""SwimTech — 코치-수강생 연동 라우터 (v2.5.2)"""
import os
import random
import string
from typing import Optional

import psycopg2
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from datetime import date
from routers.auth import verify_token

router = APIRouter()
DATABASE_URL = os.getenv("DATABASE_URL", "")


def _get_db():
    return psycopg2.connect(DATABASE_URL)


def _ensure_tables():
    if not DATABASE_URL:
        return
    conn = _get_db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS coaches (
            id          SERIAL PRIMARY KEY,
            customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE UNIQUE,
            specialty   VARCHAR(100),
            career      TEXT,
            intro       TEXT,
            invite_code VARCHAR(20) UNIQUE NOT NULL,
            created_at  TIMESTAMP DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS coach_students (
            id          SERIAL PRIMARY KEY,
            coach_id    INTEGER NOT NULL REFERENCES coaches(id) ON DELETE CASCADE,
            student_id  INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
            status      VARCHAR(10) NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'active')),
            created_at  TIMESTAMP DEFAULT NOW(),
            UNIQUE (coach_id, student_id)
        );
        CREATE TABLE IF NOT EXISTS coach_feedbacks (
            id              SERIAL PRIMARY KEY,
            coach_id        INTEGER NOT NULL REFERENCES coaches(id) ON DELETE CASCADE,
            student_id      INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
            training_log_id INTEGER REFERENCES training_logs(id) ON DELETE SET NULL,
            content         TEXT NOT NULL,
            created_at      TIMESTAMP DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS coach_plans (
            id          SERIAL PRIMARY KEY,
            coach_id    INTEGER NOT NULL REFERENCES coaches(id) ON DELETE CASCADE,
            student_id  INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
            content     TEXT NOT NULL,
            created_at  TIMESTAMP DEFAULT NOW()
        );
    """)
    conn.commit()
    cur.close()
    conn.close()


def _require_user(request: Request) -> str:
    token = request.cookies.get("swimtech_token")
    if not token:
        raise HTTPException(401, "로그인이 필요합니다.")
    username = verify_token(token)
    if not username:
        raise HTTPException(401, "유효하지 않은 토큰입니다.")
    return username


def _get_customer_id(conn, username: str) -> int:
    cur = conn.cursor()
    cur.execute("SELECT id FROM customers WHERE username = %s", (username,))
    row = cur.fetchone()
    cur.close()
    if not row:
        raise HTTPException(404, "사용자를 찾을 수 없습니다.")
    return row[0]


def _gen_invite_code() -> str:
    chars = string.ascii_uppercase + string.digits
    return "SWIM-" + "".join(random.choices(chars, k=4))


# ── Pydantic models ───────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    specialty: Optional[str] = ""
    career:    Optional[str] = ""
    intro:     Optional[str] = ""


class JoinRequest(BaseModel):
    invite_code: str


class FeedbackRequest(BaseModel):
    student_id:      int
    training_log_id: Optional[int] = None
    content:         str


class PlanRequest(BaseModel):
    student_id: int
    content:    str


# ── Endpoints ─────────────────────────────────────────────────────────────────

def _ensure_swim_shares():
    conn = _get_db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS swim_shares (
            id           SERIAL PRIMARY KEY,
            coach_id     INTEGER NOT NULL REFERENCES coaches(id) ON DELETE CASCADE,
            student_id   INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
            swim_date    DATE NOT NULL DEFAULT CURRENT_DATE,
            stroke       VARCHAR(20),
            distance_m   INTEGER NOT NULL DEFAULT 0,
            duration_min INTEGER,
            notes        TEXT,
            created_at   TIMESTAMP DEFAULT NOW()
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_swim_shares_coach ON swim_shares(coach_id)")
    conn.commit()
    cur.close()
    conn.close()


class ShareSwimRequest(BaseModel):
    stroke:       Optional[str] = ""
    distance_m:   int
    duration_min: Optional[int] = None
    notes:        Optional[str] = ""
    swim_date:    Optional[str] = None   # YYYY-MM-DD


@router.post("/share-swim")
def share_swim(req: ShareSwimRequest, request: Request):
    """수강생: 자유수영 운동량을 연결된 코치에게 공유 (+코치 알림)."""
    username = _require_user(request)
    if req.distance_m is None or req.distance_m <= 0:
        raise HTTPException(400, "거리를 입력하세요")
    if req.distance_m > 100000:
        raise HTTPException(400, "거리가 너무 큽니다")
    _ensure_swim_shares()
    conn = _get_db()
    cur = conn.cursor()
    try:
        sid = _get_customer_id(conn, username)
        cur.execute(
            "SELECT coach_id FROM coach_students WHERE student_id = %s AND status = 'active' LIMIT 1",
            (sid,),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(400, "연결된 코치가 없습니다")
        coach_id = row[0]
        if req.swim_date:
            try:
                sdate = date.fromisoformat(req.swim_date)
            except Exception:
                raise HTTPException(400, "날짜 형식 오류 (YYYY-MM-DD)")
        else:
            sdate = date.today()
        stroke = (req.stroke or "").strip()[:20]
        notes = (req.notes or "").strip()[:1000]
        cur.execute(
            """INSERT INTO swim_shares (coach_id, student_id, swim_date, stroke, distance_m, duration_min, notes)
               VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
            (coach_id, sid, sdate, stroke, req.distance_m, req.duration_min, notes),
        )
        share_id = cur.fetchone()[0]
        cur.execute("SELECT customer_id FROM coaches WHERE id = %s", (coach_id,))
        crow = cur.fetchone()
        cur.execute("SELECT name FROM customers WHERE id = %s", (sid,))
        nrow = cur.fetchone()
        sname = nrow[0] if nrow else "수강생"
        if crow:
            km = req.distance_m / 1000
            msg = f"{sname}님이 자유수영 {km:.1f}km를 공유했어요"
            cur.execute(
                "INSERT INTO notifications (customer_id, type, message, target_id) VALUES (%s,%s,%s,%s)",
                (crow[0], "swim_share", msg, share_id),
            )
        conn.commit()
        return {"status": "shared", "id": share_id}
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(500, f"공유 오류: {e}")
    finally:
        cur.close()
        conn.close()


@router.get("/shares")
def list_swim_shares(request: Request):
    """코치: 수강생들이 공유한 자유수영 목록."""
    username = _require_user(request)
    _ensure_swim_shares()
    conn = _get_db()
    cur = conn.cursor()
    try:
        cid = _get_customer_id(conn, username)
        cur.execute("SELECT id FROM coaches WHERE customer_id = %s", (cid,))
        crow = cur.fetchone()
        if not crow:
            raise HTTPException(403, "코치 프로필이 없습니다")
        coach_id = crow[0]
        cur.execute(
            """SELECT s.id, c.name, s.swim_date, s.stroke, s.distance_m, s.duration_min, s.notes, s.created_at
               FROM swim_shares s JOIN customers c ON c.id = s.student_id
               WHERE s.coach_id = %s ORDER BY s.created_at DESC LIMIT 30""",
            (coach_id,),
        )
        shares = [
            {"id": r[0], "student_name": r[1], "swim_date": str(r[2]), "stroke": r[3],
             "distance_m": r[4], "duration_min": r[5], "notes": r[6], "created_at": str(r[7])}
            for r in cur.fetchall()
        ]
        cur.close()
        return {"shares": shares}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"DB 오류: {e}")
    finally:
        conn.close()


@router.post("/register")
def register_coach(req: RegisterRequest, request: Request):
    """코치 프로필 등록 + 초대코드 발급."""
    _ensure_tables()
    username = _require_user(request)
    conn = _get_db()
    try:
        cid = _get_customer_id(conn, username)
        cur = conn.cursor()
        cur.execute("SELECT id, invite_code FROM coaches WHERE customer_id = %s", (cid,))
        existing = cur.fetchone()
        if existing:
            cur.close()
            return {"coach_id": existing[0], "invite_code": existing[1], "already_exists": True}

        invite_code = _gen_invite_code()
        for _ in range(10):
            cur.execute("SELECT 1 FROM coaches WHERE invite_code = %s", (invite_code,))
            if not cur.fetchone():
                break
            invite_code = _gen_invite_code()

        cur.execute(
            """INSERT INTO coaches (customer_id, specialty, career, intro, invite_code)
               VALUES (%s, %s, %s, %s, %s) RETURNING id""",
            (cid, req.specialty, req.career, req.intro, invite_code),
        )
        coach_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        return {"coach_id": coach_id, "invite_code": invite_code}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(500, f"DB 오류: {e}")
    finally:
        conn.close()


@router.get("/me")
def get_my_coach_profile(request: Request):
    """내 코치 프로필 + 수강생 목록."""
    _ensure_tables()
    username = _require_user(request)
    conn = _get_db()
    try:
        cid = _get_customer_id(conn, username)
        cur = conn.cursor()
        cur.execute(
            "SELECT id, specialty, career, intro, invite_code, created_at FROM coaches WHERE customer_id = %s",
            (cid,),
        )
        coach = cur.fetchone()
        if not coach:
            cur.close()
            return {"is_coach": False}

        coach_id = coach[0]
        cur.execute(
            """SELECT cs.id, cs.student_id, c.username, c.name, cs.status, cs.created_at
               FROM coach_students cs
               JOIN customers c ON cs.student_id = c.id
               WHERE cs.coach_id = %s ORDER BY cs.created_at DESC""",
            (coach_id,),
        )
        students = [
            {"relation_id": r[0], "student_id": r[1], "username": r[2],
             "name": r[3], "status": r[4], "joined_at": str(r[5])}
            for r in cur.fetchall()
        ]
        cur.close()
        return {
            "is_coach": True,
            "coach_id": coach_id,
            "specialty": coach[1],
            "career": coach[2],
            "intro": coach[3],
            "invite_code": coach[4],
            "created_at": str(coach[5]),
            "students": students,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"DB 오류: {e}")
    finally:
        conn.close()


@router.post("/join")
def join_coach(req: JoinRequest, request: Request):
    """수강생이 초대코드로 코치 연동."""
    _ensure_tables()
    username = _require_user(request)
    conn = _get_db()
    try:
        student_cid = _get_customer_id(conn, username)
        cur = conn.cursor()
        code = req.invite_code.strip().upper()
        cur.execute("SELECT id, customer_id FROM coaches WHERE invite_code = %s", (code,))
        coach_row = cur.fetchone()
        if not coach_row:
            raise HTTPException(404, "유효하지 않은 초대코드입니다.")
        coach_id = coach_row[0]
        if coach_row[1] == student_cid:
            raise HTTPException(400, "자신의 초대코드로는 연동할 수 없습니다.")

        cur.execute(
            "SELECT id, status FROM coach_students WHERE coach_id = %s AND student_id = %s",
            (coach_id, student_cid),
        )
        existing = cur.fetchone()
        if existing:
            cur.close()
            return {"relation_id": existing[0], "status": existing[1], "already_exists": True}

        cur.execute(
            "INSERT INTO coach_students (coach_id, student_id, status) VALUES (%s, %s, 'active') RETURNING id",
            (coach_id, student_cid),
        )
        relation_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        return {"relation_id": relation_id, "status": "active"}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(500, f"DB 오류: {e}")
    finally:
        conn.close()


@router.get("/students")
def list_students(request: Request):
    """코치: 수강생 목록."""
    _ensure_tables()
    username = _require_user(request)
    conn = _get_db()
    try:
        cid = _get_customer_id(conn, username)
        cur = conn.cursor()
        cur.execute("SELECT id FROM coaches WHERE customer_id = %s", (cid,))
        coach_row = cur.fetchone()
        if not coach_row:
            raise HTTPException(403, "코치 프로필이 없습니다.")
        coach_id = coach_row[0]
        cur.execute(
            """SELECT cs.student_id, c.username, c.name, cs.status, cs.created_at
               FROM coach_students cs JOIN customers c ON cs.student_id = c.id
               WHERE cs.coach_id = %s ORDER BY cs.created_at DESC""",
            (coach_id,),
        )
        students = [
            {"student_id": r[0], "username": r[1], "name": r[2],
             "status": r[3], "joined_at": str(r[4])}
            for r in cur.fetchall()
        ]
        cur.close()
        return {"students": students}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"DB 오류: {e}")
    finally:
        conn.close()


@router.get("/students/{student_id}/logs")
def get_student_logs(student_id: int, request: Request):
    """코치: 수강생 훈련 일지 열람."""
    _ensure_tables()
    username = _require_user(request)
    conn = _get_db()
    try:
        cid = _get_customer_id(conn, username)
        cur = conn.cursor()
        cur.execute("SELECT id FROM coaches WHERE customer_id = %s", (cid,))
        coach_row = cur.fetchone()
        if not coach_row:
            raise HTTPException(403, "코치 프로필이 없습니다.")
        coach_id = coach_row[0]
        cur.execute(
            "SELECT 1 FROM coach_students WHERE coach_id = %s AND student_id = %s AND status = 'active'",
            (coach_id, student_id),
        )
        if not cur.fetchone():
            raise HTTPException(403, "열람 권한이 없습니다.")
        cur.execute(
            """SELECT id, plan_name, log_date, notes, created_at
               FROM training_logs
               WHERE username = (SELECT username FROM customers WHERE id = %s)
               ORDER BY log_date DESC LIMIT 20""",
            (student_id,),
        )
        logs = [
            {"id": r[0], "plan_name": r[1], "log_date": str(r[2]),
             "notes": r[3], "created_at": str(r[4])}
            for r in cur.fetchall()
        ]
        cur.close()
        return {"logs": logs}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"DB 오류: {e}")
    finally:
        conn.close()


@router.post("/feedback")
def post_feedback(req: FeedbackRequest, request: Request):
    """코치: 수강생 훈련 일지에 피드백 작성."""
    _ensure_tables()
    username = _require_user(request)
    conn = _get_db()
    try:
        cid = _get_customer_id(conn, username)
        cur = conn.cursor()
        cur.execute("SELECT id FROM coaches WHERE customer_id = %s", (cid,))
        coach_row = cur.fetchone()
        if not coach_row:
            raise HTTPException(403, "코치 프로필이 없습니다.")
        coach_id = coach_row[0]
        cur.execute(
            "SELECT 1 FROM coach_students WHERE coach_id = %s AND student_id = %s AND status = 'active'",
            (coach_id, req.student_id),
        )
        if not cur.fetchone():
            raise HTTPException(403, "피드백 작성 권한이 없습니다.")
        if not req.content.strip():
            raise HTTPException(400, "피드백 내용을 입력해주세요.")
        cur.execute(
            """INSERT INTO coach_feedbacks (coach_id, student_id, training_log_id, content)
               VALUES (%s, %s, %s, %s) RETURNING id, created_at""",
            (coach_id, req.student_id, req.training_log_id, req.content.strip()),
        )
        row = cur.fetchone()
        conn.commit()
        cur.close()
        return {"feedback_id": row[0], "created_at": str(row[1])}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(500, f"DB 오류: {e}")
    finally:
        conn.close()


@router.get("/my-coach")
def get_my_coach(request: Request):
    """수강생: 내 코치 정보 + 피드백 목록."""
    _ensure_tables()
    username = _require_user(request)
    conn = _get_db()
    try:
        cid = _get_customer_id(conn, username)
        cur = conn.cursor()
        cur.execute(
            """SELECT cs.coach_id, c2.username, c2.name, co.specialty, co.career, co.intro, cs.status
               FROM coach_students cs
               JOIN coaches co ON cs.coach_id = co.id
               JOIN customers c2 ON co.customer_id = c2.id
               WHERE cs.student_id = %s AND cs.status = 'active'
               ORDER BY cs.created_at DESC LIMIT 1""",
            (cid,),
        )
        coach_row = cur.fetchone()
        if not coach_row:
            cur.close()
            return {"has_coach": False}
        coach_id = coach_row[0]
        cur.execute(
            """SELECT id, content, training_log_id, created_at
               FROM coach_feedbacks WHERE coach_id = %s AND student_id = %s
               ORDER BY created_at DESC LIMIT 20""",
            (coach_id, cid),
        )
        feedbacks = [
            {"id": r[0], "content": r[1], "training_log_id": r[2], "created_at": str(r[3])}
            for r in cur.fetchall()
        ]
        cur.close()
        return {
            "has_coach": True,
            "coach_id": coach_id,
            "coach_username": coach_row[1],
            "coach_name": coach_row[2],
            "specialty": coach_row[3],
            "career": coach_row[4],
            "intro": coach_row[5],
            "status": coach_row[6],
            "feedbacks": feedbacks,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"DB 오류: {e}")
    finally:
        conn.close()


@router.get("/plan")
def get_coach_plan(request: Request):
    """수강생: 코치가 보낸 플랜 확인."""
    _ensure_tables()
    username = _require_user(request)
    conn = _get_db()
    try:
        cid = _get_customer_id(conn, username)
        cur = conn.cursor()
        cur.execute(
            """SELECT cp.id, cp.content, cp.created_at, c2.name
               FROM coach_plans cp
               JOIN coaches co ON cp.coach_id = co.id
               JOIN customers c2 ON co.customer_id = c2.id
               WHERE cp.student_id = %s ORDER BY cp.created_at DESC LIMIT 10""",
            (cid,),
        )
        plans = [
            {"id": r[0], "content": r[1], "created_at": str(r[2]), "coach_name": r[3]}
            for r in cur.fetchall()
        ]
        cur.close()
        return {"plans": plans}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"DB 오류: {e}")
    finally:
        conn.close()


@router.post("/plan")
def send_coach_plan(req: PlanRequest, request: Request):
    """코치: 수강생에게 플랜 전달."""
    _ensure_tables()
    username = _require_user(request)
    conn = _get_db()
    try:
        cid = _get_customer_id(conn, username)
        cur = conn.cursor()
        cur.execute("SELECT id FROM coaches WHERE customer_id = %s", (cid,))
        coach_row = cur.fetchone()
        if not coach_row:
            raise HTTPException(403, "코치 프로필이 없습니다.")
        coach_id = coach_row[0]
        cur.execute(
            "SELECT 1 FROM coach_students WHERE coach_id = %s AND student_id = %s AND status = 'active'",
            (coach_id, req.student_id),
        )
        if not cur.fetchone():
            raise HTTPException(403, "플랜 전달 권한이 없습니다.")
        if not req.content.strip():
            raise HTTPException(400, "플랜 내용을 입력해주세요.")
        cur.execute(
            "INSERT INTO coach_plans (coach_id, student_id, content) VALUES (%s, %s, %s) RETURNING id, created_at",
            (coach_id, req.student_id, req.content.strip()),
        )
        row = cur.fetchone()
        conn.commit()
        cur.close()
        return {"plan_id": row[0], "created_at": str(row[1])}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(500, f"DB 오류: {e}")
    finally:
        conn.close()


@router.delete("/students/{student_id}")
def remove_student(student_id: int, request: Request):
    """코치: 수강생 연동 해제."""
    _ensure_tables()
    username = _require_user(request)
    conn = _get_db()
    try:
        cid = _get_customer_id(conn, username)
        cur = conn.cursor()
        cur.execute("SELECT id FROM coaches WHERE customer_id = %s", (cid,))
        coach_row = cur.fetchone()
        if not coach_row:
            raise HTTPException(403, "코치 프로필이 없습니다.")
        coach_id = coach_row[0]
        cur.execute(
            "DELETE FROM coach_students WHERE coach_id = %s AND student_id = %s RETURNING id",
            (coach_id, student_id),
        )
        deleted = cur.fetchone()
        conn.commit()
        cur.close()
        if not deleted:
            raise HTTPException(404, "해당 수강생을 찾을 수 없습니다.")
        return {"deleted": True}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(500, f"DB 오류: {e}")
    finally:
        conn.close()
