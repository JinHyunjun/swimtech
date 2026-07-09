# -*- coding: utf-8 -*-
"""SwimMate — 코치 코드 기반 수강생 연동 및 선택 자격 확인 라우터."""
import os
import random
import string
import time
from typing import Any, Dict, List, Optional

import psycopg2
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from datetime import date, datetime, timedelta, timezone
import json
from integrations.jira_client import JiraApiError, JiraClient, JiraConfigurationError
from routers.auth import verify_token

router = APIRouter()
DATABASE_URL = os.getenv("DATABASE_URL", "")
_JIRA_ANALYTICS_TTL_SECONDS = 60
_JIRA_ANALYTICS_CACHE: Dict[str, tuple[float, Dict[str, Any]]] = {}
_JIRA_CATEGORY_LABELS = {
    "technique": "영법 교정",
    "recovery": "회복 확인",
    "attendance": "출석 확인",
    "training-plan": "훈련 계획",
    "other": "기타",
}


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
        CREATE TABLE IF NOT EXISTS coach_action_items (
            id              SERIAL PRIMARY KEY,
            coach_id        INTEGER NOT NULL REFERENCES coaches(id) ON DELETE CASCADE,
            student_id      INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
            category        VARCHAR(30) NOT NULL,
            title           VARCHAR(200) NOT NULL,
            description     TEXT,
            status          VARCHAR(20) NOT NULL DEFAULT 'open',
            sync_status     VARCHAR(20) NOT NULL DEFAULT 'pending',
            jira_issue_key  VARCHAR(40),
            jira_issue_url  TEXT,
            sync_error      TEXT,
            created_at      TIMESTAMPTZ DEFAULT NOW(),
            updated_at      TIMESTAMPTZ DEFAULT NOW()
        );
    """)
    cur.execute("ALTER TABLE coaches ADD COLUMN IF NOT EXISTS credential_type VARCHAR(60)")
    cur.execute("ALTER TABLE coaches ADD COLUMN IF NOT EXISTS credential_number VARCHAR(120)")
    cur.execute("ALTER TABLE coaches ADD COLUMN IF NOT EXISTS credential_organization VARCHAR(120)")
    cur.execute("ALTER TABLE coaches ADD COLUMN IF NOT EXISTS verification_status VARCHAR(12) NOT NULL DEFAULT 'unverified'")
    cur.execute("ALTER TABLE coaches ALTER COLUMN verification_status SET DEFAULT 'unverified'")
    cur.execute("ALTER TABLE coaches ADD COLUMN IF NOT EXISTS verification_note TEXT")
    cur.execute("ALTER TABLE coaches ADD COLUMN IF NOT EXISTS verified_at TIMESTAMPTZ")
    cur.execute("ALTER TABLE coaches ADD COLUMN IF NOT EXISTS verified_by VARCHAR(100)")
    cur.execute("""CREATE UNIQUE INDEX IF NOT EXISTS idx_coaches_unique_credential
                   ON coaches(credential_organization, credential_number)
                   WHERE credential_organization IS NOT NULL AND credential_number IS NOT NULL""")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_coach_action_items_coach ON coach_action_items(coach_id, created_at DESC)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_coach_action_items_student ON coach_action_items(student_id, created_at DESC)")
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


def _require_coach(cur, customer_id: int) -> int:
    """코치 등록 여부만 확인한다. 자격 인증은 기능 권한이 아닌 신뢰 배지다."""
    cur.execute("SELECT id FROM coaches WHERE customer_id = %s", (customer_id,))
    row = cur.fetchone()
    if not row:
        raise HTTPException(403, "코치 프로필이 없습니다.")
    return int(row[0])


# ── Pydantic models ───────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    specialty: Optional[str] = Field(default="", max_length=100)
    career:    Optional[str] = Field(default="", max_length=500)
    intro:     Optional[str] = Field(default="", max_length=1000)
    credential_type: Optional[str] = Field(default="", max_length=60)
    credential_number: Optional[str] = Field(default="", max_length=120)
    credential_organization: Optional[str] = Field(default="", max_length=120)


class VerificationRequest(BaseModel):
    credential_type: str = Field(..., min_length=2, max_length=60)
    credential_number: str = Field(..., min_length=2, max_length=120)
    credential_organization: str = Field(..., min_length=2, max_length=120)


class JoinRequest(BaseModel):
    invite_code: str


class FeedbackRequest(BaseModel):
    student_id:      int
    training_log_id: Optional[int] = None
    content:         str


class PlanRequest(BaseModel):
    student_id: int
    content:    str
    plan_meta:  Optional[Dict[str, Any]] = None


class CoachActionItemRequest(BaseModel):
    student_id: int
    category: str = Field(default="technique", pattern="^(technique|recovery|attendance|training-plan)$")
    title: str = Field(..., min_length=3, max_length=200)
    description: str = Field(default="", max_length=3000)


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
    cur.execute("ALTER TABLE swim_shares ADD COLUMN IF NOT EXISTS strokes JSONB")
    conn.commit()
    cur.close()
    conn.close()


class StrokeEntry(BaseModel):
    stroke:     str = ""
    distance_m: int


class ShareSwimRequest(BaseModel):
    entries:      List[StrokeEntry] = []
    duration_min: Optional[int] = None
    notes:        Optional[str] = ""
    swim_date:    Optional[str] = None   # YYYY-MM-DD


@router.post("/share-swim")
def share_swim(req: ShareSwimRequest, request: Request):
    """수강생: 자유수영 운동량을 연결된 코치에게 공유 (+코치 알림)."""
    username = _require_user(request)
    if not req.entries:
        raise HTTPException(400, "영법을 1개 이상 입력하세요")
    clean_entries = []
    total = 0
    for ent in req.entries:
        d = int(ent.distance_m or 0)
        if d <= 0:
            continue
        clean_entries.append({"stroke": (ent.stroke or "").strip()[:20] or "자유형", "distance_m": d})
        total += d
    if not clean_entries:
        raise HTTPException(400, "거리를 입력하세요")
    if total > 200000:
        raise HTTPException(400, "총 거리가 너무 큽니다")
    _ensure_swim_shares()
    conn = _get_db()
    cur = conn.cursor()
    try:
        sid = _get_customer_id(conn, username)
        cur.execute(
            """SELECT cs.coach_id FROM coach_students cs
               JOIN coaches co ON co.id = cs.coach_id
               WHERE cs.student_id = %s AND cs.status = 'active'
               LIMIT 1""",
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
        notes = (req.notes or "").strip()[:1000]
        primary = clean_entries[0]["stroke"]
        cur.execute(
            """INSERT INTO swim_shares (coach_id, student_id, swim_date, stroke, distance_m, duration_min, notes, strokes)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
            (coach_id, sid, sdate, primary, total, req.duration_min, notes,
             json.dumps(clean_entries, ensure_ascii=False)),
        )
        share_id = cur.fetchone()[0]
        cur.execute("SELECT customer_id FROM coaches WHERE id = %s", (coach_id,))
        crow = cur.fetchone()
        cur.execute("SELECT name FROM customers WHERE id = %s", (sid,))
        nrow = cur.fetchone()
        sname = nrow[0] if nrow else "수강생"
        if crow:
            km = total / 1000
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
        coach_id = _require_coach(cur, cid)
        cur.execute(
            """SELECT s.id, c.name, s.swim_date, s.stroke, s.distance_m, s.duration_min, s.notes, s.created_at, s.strokes
               FROM swim_shares s JOIN customers c ON c.id = s.student_id
               WHERE s.coach_id = %s ORDER BY s.created_at DESC LIMIT 30""",
            (coach_id,),
        )
        shares = [
            {"id": r[0], "student_name": r[1], "swim_date": str(r[2]), "stroke": r[3],
             "distance_m": r[4], "duration_min": r[5], "notes": r[6], "created_at": str(r[7]), "strokes": r[8]}
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


def _ensure_lessons():
    conn = _get_db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS coach_lessons (
            id          SERIAL PRIMARY KEY,
            coach_id    INTEGER NOT NULL REFERENCES coaches(id) ON DELETE CASCADE,
            lesson_date DATE NOT NULL DEFAULT CURRENT_DATE,
            kind        VARCHAR(20) NOT NULL DEFAULT '공지',
            content     TEXT NOT NULL,
            created_at  TIMESTAMP DEFAULT NOW()
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_coach_lessons_coach ON coach_lessons(coach_id)")
    conn.commit(); cur.close(); conn.close()


class LessonRequest(BaseModel):
    kind:        str = "공지"
    lesson_date: Optional[str] = None
    content:     str


@router.post("/lesson")
def create_lesson(req: LessonRequest, request: Request):
    """코치: 강습 일지를 작성해 연동된 전 수강생에게 일괄 공유 (+각자 알림)."""
    username = _require_user(request)
    content = (req.content or "").strip()
    if not content:
        raise HTTPException(400, "내용을 입력하세요")
    if len(content) > 2000:
        raise HTTPException(400, "내용이 너무 깁니다 (최대 2000자)")
    kind = (req.kind or "공지").strip()[:20]
    _ensure_lessons()
    conn = _get_db()
    cur = conn.cursor()
    try:
        cid = _get_customer_id(conn, username)
        coach_id = _require_coach(cur, cid)
        if req.lesson_date:
            try:
                ldate = date.fromisoformat(req.lesson_date)
            except Exception:
                raise HTTPException(400, "날짜 형식 오류 (YYYY-MM-DD)")
        else:
            ldate = date.today()
        cur.execute(
            """INSERT INTO coach_lessons (coach_id, lesson_date, kind, content)
               VALUES (%s,%s,%s,%s) RETURNING id""",
            (coach_id, ldate, kind, content),
        )
        lesson_id = cur.fetchone()[0]
        cur.execute(
            "SELECT student_id FROM coach_students WHERE coach_id = %s AND status = 'active'",
            (coach_id,),
        )
        students = [r[0] for r in cur.fetchall()]
        msg = f"코치가 강습 일지를 공유했어요: [{kind}]"
        for sid in students:
            cur.execute(
                "INSERT INTO notifications (customer_id, type, message, target_id) VALUES (%s,%s,%s,%s)",
                (sid, "lesson_broadcast", msg, lesson_id),
            )
        conn.commit()
        return {"status": "broadcast", "id": lesson_id, "count": len(students)}
    except HTTPException:
        conn.rollback(); raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(500, f"공유 오류: {e}")
    finally:
        cur.close(); conn.close()


def _fetch_lessons(cur, coach_id):
    cur.execute(
        """SELECT id, lesson_date, kind, content, created_at
           FROM coach_lessons WHERE coach_id = %s ORDER BY created_at DESC LIMIT 20""",
        (coach_id,),
    )
    return [
        {"id": r[0], "lesson_date": str(r[1]), "kind": r[2], "content": r[3], "created_at": str(r[4])}
        for r in cur.fetchall()
    ]


@router.get("/lessons")
def list_lessons(request: Request):
    """코치: 내가 공유한 강습 일지 목록."""
    username = _require_user(request)
    _ensure_lessons()
    conn = _get_db()
    cur = conn.cursor()
    try:
        cid = _get_customer_id(conn, username)
        coach_id = _require_coach(cur, cid)
        lessons = _fetch_lessons(cur, coach_id)
        cur.close()
        return {"lessons": lessons}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"DB 오류: {e}")
    finally:
        conn.close()


@router.get("/my-lessons")
def my_lessons(request: Request):
    """수강생: 내 코치가 공유한 강습 일지."""
    username = _require_user(request)
    _ensure_lessons()
    conn = _get_db()
    cur = conn.cursor()
    try:
        sid = _get_customer_id(conn, username)
        cur.execute(
            """SELECT cs.coach_id FROM coach_students cs
               JOIN coaches co ON co.id = cs.coach_id
               WHERE cs.student_id = %s AND cs.status = 'active'
               LIMIT 1""",
            (sid,),
        )
        row = cur.fetchone()
        if not row:
            cur.close()
            return {"lessons": []}
        lessons = _fetch_lessons(cur, row[0])
        cur.close()
        return {"lessons": lessons}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"DB 오류: {e}")
    finally:
        conn.close()


@router.post("/register")
def register_coach(req: RegisterRequest, request: Request):
    """코치 프로필을 등록하고 학생 연동용 코치 코드를 즉시 발급한다."""
    _ensure_tables()
    username = _require_user(request)
    conn = _get_db()
    try:
        cid = _get_customer_id(conn, username)
        cur = conn.cursor()
        cur.execute(
            "SELECT id, invite_code, COALESCE(verification_status, 'unverified') "
            "FROM coaches WHERE customer_id = %s",
            (cid,),
        )
        existing = cur.fetchone()
        if existing:
            credential_values = [
                (req.credential_type or "").strip(),
                (req.credential_number or "").strip(),
                (req.credential_organization or "").strip(),
            ]
            if any(credential_values) and not all(credential_values):
                raise HTTPException(400, "자격 인증을 요청하려면 종류, 번호, 발급 기관을 모두 입력해주세요.")
            next_status = existing[2]
            if all(credential_values) and existing[2] != "verified":
                cur.execute(
                    """SELECT id FROM coaches
                       WHERE credential_organization = %s AND credential_number = %s AND id <> %s""",
                    (credential_values[2], credential_values[1], existing[0]),
                )
                if cur.fetchone():
                    raise HTTPException(409, "이미 다른 계정에서 검토 중이거나 등록된 자격 정보입니다.")
                cur.execute(
                    """
                    UPDATE coaches SET specialty = %s, career = %s, intro = %s,
                        credential_type = %s, credential_number = %s,
                        credential_organization = %s, verification_status = 'pending',
                        verification_note = NULL, verified_at = NULL, verified_by = NULL
                    WHERE id = %s
                    """,
                    (
                        (req.specialty or "").strip(), (req.career or "").strip(),
                        (req.intro or "").strip(), *credential_values, existing[0],
                    ),
                )
                next_status = "pending"
            else:
                cur.execute(
                    "UPDATE coaches SET specialty = %s, career = %s, intro = %s WHERE id = %s",
                    (
                        (req.specialty or "").strip(), (req.career or "").strip(),
                        (req.intro or "").strip(), existing[0],
                    ),
                )
            conn.commit()
            cur.close()
            return {
                "coach_id": existing[0],
                "invite_code": existing[1],
                "verification_status": next_status,
                "already_exists": True,
            }

        credential_type = (req.credential_type or "").strip()
        credential_number = (req.credential_number or "").strip()
        credential_organization = (req.credential_organization or "").strip()
        credential_values = (credential_type, credential_number, credential_organization)
        if any(credential_values) and not all(credential_values):
            raise HTTPException(400, "자격 인증을 요청하려면 종류, 번호, 발급 기관을 모두 입력해주세요.")
        verification_status = "pending" if all(credential_values) else "unverified"
        if verification_status == "pending":
            cur.execute(
                "SELECT id FROM coaches WHERE credential_organization = %s AND credential_number = %s",
                (credential_organization, credential_number),
            )
            if cur.fetchone():
                raise HTTPException(409, "이미 다른 계정에서 검토 중이거나 등록된 자격 정보입니다.")

        invite_code = _gen_invite_code()
        for _ in range(10):
            cur.execute("SELECT 1 FROM coaches WHERE invite_code = %s", (invite_code,))
            if not cur.fetchone():
                break
            invite_code = _gen_invite_code()

        cur.execute(
            """INSERT INTO coaches
                   (customer_id, specialty, career, intro, invite_code,
                    credential_type, credential_number, credential_organization,
                    verification_status)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
            (
                cid, (req.specialty or "").strip(), (req.career or "").strip(),
                (req.intro or "").strip(), invite_code, credential_type or None,
                credential_number or None, credential_organization or None, verification_status,
            ),
        )
        coach_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        return {"coach_id": coach_id, "invite_code": invite_code, "verification_status": verification_status}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(500, f"DB 오류: {e}")
    finally:
        conn.close()


@router.put("/verification")
def resubmit_coach_verification(req: VerificationRequest, request: Request):
    """반려되었거나 대기 중인 코치가 자격 정보를 수정해 다시 검토 요청한다."""
    _ensure_tables()
    username = _require_user(request)
    conn = _get_db()
    cur = conn.cursor()
    try:
        cid = _get_customer_id(conn, username)
        cur.execute("SELECT id, verification_status FROM coaches WHERE customer_id = %s", (cid,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "코치 프로필이 없습니다.")
        if row[1] == "verified":
            raise HTTPException(400, "이미 본인 확인이 완료된 코치입니다.")
        cur.execute(
            """SELECT id FROM coaches
               WHERE credential_organization = %s AND credential_number = %s AND id <> %s""",
            (req.credential_organization.strip(), req.credential_number.strip(), row[0]),
        )
        if cur.fetchone():
            raise HTTPException(409, "이미 다른 계정에서 검토 중이거나 등록된 자격 정보입니다.")
        cur.execute(
            """
            UPDATE coaches SET credential_type = %s, credential_number = %s,
                credential_organization = %s, verification_status = 'pending',
                verification_note = NULL, verified_at = NULL, verified_by = NULL
            WHERE id = %s
            """,
            (
                req.credential_type.strip(), req.credential_number.strip(),
                req.credential_organization.strip(), row[0],
            ),
        )
        conn.commit()
        return {"coach_id": row[0], "verification_status": "pending"}
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(500, f"DB 오류: {e}")
    finally:
        cur.close()
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
            """SELECT id, specialty, career, intro, invite_code, created_at,
                      COALESCE(verification_status, 'unverified'), verification_note,
                      credential_type, credential_organization, verified_at
               FROM coaches WHERE customer_id = %s""",
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
            "verification_status": coach[6],
            "verification_note": coach[7],
            "credential_type": coach[8],
            "credential_organization": coach[9],
            "verified_at": str(coach[10]) if coach[10] else None,
            "students": students,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"DB 오류: {e}")
    finally:
        conn.close()


def _crew_member_signal(
    *,
    last_training_date: date | None,
    readiness_score: int | None,
    hard_sessions_14d: int,
) -> dict[str, str]:
    if readiness_score is not None and readiness_score < 50:
        return {"level": "attention", "label": "회복 확인"}
    if hard_sessions_14d >= 2:
        return {"level": "attention", "label": "고강도 연속"}
    if last_training_date is None:
        return {"level": "watch", "label": "훈련 기록 없음"}
    if (date.today() - last_training_date).days >= 10:
        return {"level": "watch", "label": "10일 이상 공백"}
    return {"level": "steady", "label": "안정적"}


def _parse_jira_datetime(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    clean = value.replace("Z", "+00:00")
    if len(clean) >= 5 and clean[-5] in ("+", "-") and clean[-3] != ":":
        clean = f"{clean[:-2]}:{clean[-2:]}"
    try:
        parsed = datetime.fromisoformat(clean)
    except ValueError:
        try:
            parsed = datetime.strptime(value[:19], "%Y-%m-%dT%H:%M:%S")
        except ValueError:
            return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


def _week_label(day: date) -> str:
    return f"{day.month}/{day.day:02d}"


def _jira_category_from_labels(labels: Any) -> str:
    label_set = {str(label) for label in (labels or [])}
    for key in ("technique", "recovery", "attendance", "training-plan"):
        if key in label_set:
            return key
    return "other"


def _empty_jira_analytics(
    project_key: str | None = None,
    *,
    available: bool = False,
    error: str | None = None,
) -> Dict[str, Any]:
    today = date.today()
    week_starts = [_week_start(today) - timedelta(days=7 * offset) for offset in range(5, -1, -1)]
    return {
        "available": available,
        "project_key": project_key,
        "error": error,
        "open_count": 0,
        "done_count": 0,
        "done_this_week": 0,
        "average_resolution_days": None,
        "category_counts": [
            {"key": key, "label": label, "count": 0}
            for key, label in _JIRA_CATEGORY_LABELS.items()
        ],
        "status_counts": [],
        "weekly_flow": [
            {"week": _week_label(week), "created": 0, "done": 0}
            for week in week_starts
        ],
        "stale_items": [],
        "cache": {"hit": False, "ttl_seconds": _JIRA_ANALYTICS_TTL_SECONDS},
    }


def _build_jira_analytics(
    issues: List[Dict[str, Any]],
    project_key: str,
    base_url: str = "",
) -> Dict[str, Any]:
    today = date.today()
    current_week = _week_start(today)
    week_starts = [_week_start(today) - timedelta(days=7 * offset) for offset in range(5, -1, -1)]
    weekly = {week: {"week": _week_label(week), "created": 0, "done": 0} for week in week_starts}
    category_counts = {key: 0 for key in _JIRA_CATEGORY_LABELS}
    status_counts: Dict[str, Dict[str, Any]] = {}
    stale_candidates = []
    open_count = 0
    done_count = 0
    done_this_week = 0
    resolution_days: List[float] = []

    for issue in issues:
        fields = issue.get("fields") or {}
        status = fields.get("status") or {}
        status_category = (status.get("statusCategory") or {}).get("key") or ""
        status_key = str(status_category).lower()
        status_name = status.get("name") or "상태 없음"
        is_done = status_key == "done" or bool(fields.get("resolutiondate"))

        status_bucket = status_counts.setdefault(
            status_name,
            {"name": status_name, "category": status_key or "unknown", "count": 0},
        )
        status_bucket["count"] += 1

        category_key = _jira_category_from_labels(fields.get("labels"))
        category_counts[category_key] = category_counts.get(category_key, 0) + 1

        created_at = _parse_jira_datetime(fields.get("created"))
        updated_at = _parse_jira_datetime(fields.get("updated"))
        resolved_at = _parse_jira_datetime(fields.get("resolutiondate"))

        if created_at:
            created_week = _week_start(created_at.date())
            if created_week in weekly:
                weekly[created_week]["created"] += 1
        if resolved_at:
            resolved_week = _week_start(resolved_at.date())
            if resolved_week in weekly:
                weekly[resolved_week]["done"] += 1
            if resolved_week >= current_week:
                done_this_week += 1
            if created_at:
                resolution_days.append(max((resolved_at - created_at).total_seconds() / 86400, 0))

        if is_done:
            done_count += 1
        else:
            open_count += 1
            last_touched = updated_at or created_at
            if last_touched and (datetime.now(timezone.utc) - last_touched).days >= 7:
                key = issue.get("key") or ""
                stale_candidates.append({
                    "key": key,
                    "title": fields.get("summary") or key,
                    "status": status_name,
                    "updated": last_touched.date().isoformat(),
                    "url": f"{base_url}/browse/{key}" if base_url and key else None,
                })

    status_order = {"new": 0, "indeterminate": 1, "done": 2}
    ordered_statuses = sorted(
        status_counts.values(),
        key=lambda item: (status_order.get(str(item["category"]), 99), item["name"]),
    )

    return {
        "available": True,
        "project_key": project_key,
        "error": None,
        "open_count": open_count,
        "done_count": done_count,
        "done_this_week": done_this_week,
        "average_resolution_days": round(sum(resolution_days) / len(resolution_days), 1) if resolution_days else None,
        "category_counts": [
            {"key": key, "label": label, "count": category_counts.get(key, 0)}
            for key, label in _JIRA_CATEGORY_LABELS.items()
        ],
        "status_counts": ordered_statuses,
        "weekly_flow": list(weekly.values()),
        "stale_items": stale_candidates[:5],
        "cache": {"hit": False, "ttl_seconds": _JIRA_ANALYTICS_TTL_SECONDS},
    }


def _safe_jira_issue_keys(keys: List[str]) -> List[str]:
    safe_keys = []
    for key in keys:
        value = str(key or "").strip().upper()
        if value and "-" in value and value.replace("-", "").replace("_", "").isalnum():
            safe_keys.append(value)
    return safe_keys[:100]


def _get_jira_analytics(issue_keys: List[str] | None = None) -> Dict[str, Any]:
    try:
        client = JiraClient()
        safe_keys = _safe_jira_issue_keys(issue_keys or [])
        key_part = ",".join(sorted(safe_keys)) or "project-labels"
        cache_key = f"{client.settings.base_url}|{client.settings.project_key}|{key_part}"
        now = time.time()
        cached = _JIRA_ANALYTICS_CACHE.get(cache_key)
        if cached and now - cached[0] < _JIRA_ANALYTICS_TTL_SECONDS:
            cached_value = dict(cached[1])
            cached_value["cache"] = {"hit": True, "ttl_seconds": _JIRA_ANALYTICS_TTL_SECONDS}
            return cached_value

        if safe_keys:
            jql = f"issuekey in ({','.join(safe_keys)}) ORDER BY created DESC"
        else:
            jql = f"project = {client.settings.project_key} AND labels = swimmate ORDER BY created DESC"
        result = client.search_issues(
            jql=jql,
            fields=["summary", "status", "labels", "created", "updated", "resolutiondate"],
            max_results=100,
        )
        analytics = _build_jira_analytics(
            result.get("issues", []),
            client.settings.project_key,
            client.settings.base_url,
        )
        _JIRA_ANALYTICS_CACHE[cache_key] = (now, analytics)
        return analytics
    except JiraConfigurationError as exc:
        return _empty_jira_analytics(error=str(exc))
    except JiraApiError as exc:
        return _empty_jira_analytics(error=str(exc))


def _invalidate_jira_analytics_cache() -> None:
    _JIRA_ANALYTICS_CACHE.clear()


@router.get("/crew-dashboard")
def get_crew_dashboard(request: Request):
    """Coach-facing roster snapshot built from the canonical training logs."""
    _ensure_tables()
    username = _require_user(request)
    conn = _get_db()
    cur = conn.cursor()
    try:
        customer_id = _get_customer_id(conn, username)
        coach_id = _require_coach(cur, customer_id)
        cur.execute(
            """
            SELECT cs.student_id,
                   COALESCE(NULLIF(c.nickname, ''), NULLIF(c.name, ''), c.username),
                   c.username,
                   COUNT(tl.id) FILTER (WHERE tl.log_date >= CURRENT_DATE - INTERVAL '30 days'),
                   COALESCE(SUM(tl.total_distance) FILTER (WHERE tl.log_date >= CURRENT_DATE - INTERVAL '30 days'), 0),
                   MAX(tl.log_date),
                   COUNT(tl.id) FILTER (
                       WHERE tl.log_date >= CURRENT_DATE - INTERVAL '14 days'
                         AND tl.intensity = '힘듦'
                   )
            FROM coach_students cs
            JOIN customers c ON c.id = cs.student_id
            LEFT JOIN training_logs tl ON tl.customer_id = cs.student_id
            WHERE cs.coach_id = %s AND cs.status = 'active'
            GROUP BY cs.student_id, c.nickname, c.name, c.username, cs.created_at
            ORDER BY cs.created_at DESC
            """,
            (coach_id,),
        )
        rows = cur.fetchall()

        cur.execute("SELECT to_regclass('public.training_readiness')")
        has_readiness = bool(cur.fetchone()[0])
        members = []
        for row in rows:
            readiness_score = None
            if has_readiness:
                cur.execute(
                    """SELECT readiness_score FROM training_readiness
                       WHERE customer_id = %s ORDER BY check_date DESC LIMIT 1""",
                    (row[0],),
                )
                readiness_row = cur.fetchone()
                readiness_score = int(readiness_row[0]) if readiness_row else None
            signal = _crew_member_signal(
                last_training_date=row[5],
                readiness_score=readiness_score,
                hard_sessions_14d=int(row[6] or 0),
            )
            members.append({
                "student_id": int(row[0]),
                "display_name": row[1] or row[2],
                "sessions_30d": int(row[3] or 0),
                "distance_30d": int(row[4] or 0),
                "last_training_date": str(row[5]) if row[5] else None,
                "readiness_score": readiness_score,
                "hard_sessions_14d": int(row[6] or 0),
                "signal": signal,
            })

        members.sort(key=lambda item: {"attention": 0, "watch": 1, "steady": 2}[item["signal"]["level"]])
        cur.execute(
            """
            SELECT cai.id, cai.student_id,
                   COALESCE(NULLIF(c.nickname, ''), NULLIF(c.name, ''), c.username),
                   cai.category, cai.title, cai.status, cai.sync_status,
                   cai.jira_issue_key, cai.jira_issue_url, cai.created_at
            FROM coach_action_items cai
            JOIN customers c ON c.id = cai.student_id
            WHERE cai.coach_id = %s
            ORDER BY cai.created_at DESC LIMIT 8
            """,
            (coach_id,),
        )
        action_items = [{
            "id": int(row[0]), "student_id": int(row[1]), "student_name": row[2],
            "category": row[3], "title": row[4], "status": row[5],
            "sync_status": row[6], "jira_issue_key": row[7], "jira_issue_url": row[8],
            "created_at": str(row[9]),
        } for row in cur.fetchall()]
        cur.execute(
            """
            SELECT jira_issue_key
            FROM coach_action_items
            WHERE coach_id = %s AND jira_issue_key IS NOT NULL
            ORDER BY created_at DESC LIMIT 100
            """,
            (coach_id,),
        )
        jira_issue_keys = [row[0] for row in cur.fetchall()]

        return {
            "summary": {
                "member_count": len(members),
                "sessions_30d": sum(item["sessions_30d"] for item in members),
                "distance_30d": sum(item["distance_30d"] for item in members),
                "attention_count": sum(item["signal"]["level"] != "steady" for item in members),
            },
            "members": members,
            "action_items": action_items,
            "jira_analytics": _get_jira_analytics(jira_issue_keys),
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, f"크루 현황을 불러오지 못했습니다: {exc}") from exc
    finally:
        cur.close()
        conn.close()


@router.post("/action-items", status_code=201)
def create_coach_action_item(body: CoachActionItemRequest, request: Request):
    """Persist a coach task first, then mirror it to Jira when configured."""
    _ensure_tables()
    username = _require_user(request)
    conn = _get_db()
    cur = conn.cursor()
    try:
        customer_id = _get_customer_id(conn, username)
        coach_id = _require_coach(cur, customer_id)
        cur.execute(
            """SELECT COALESCE(NULLIF(c.nickname, ''), NULLIF(c.name, ''), c.username)
               FROM coach_students cs JOIN customers c ON c.id = cs.student_id
               WHERE cs.coach_id = %s AND cs.student_id = %s AND cs.status = 'active'""",
            (coach_id, body.student_id),
        )
        student = cur.fetchone()
        if not student:
            raise HTTPException(403, "연동된 수강생에게만 코칭 과제를 만들 수 있습니다.")

        title = body.title.strip()
        description = body.description.strip()
        cur.execute(
            """INSERT INTO coach_action_items
                   (coach_id, student_id, category, title, description, sync_status)
               VALUES (%s, %s, %s, %s, %s, 'pending') RETURNING id""",
            (coach_id, body.student_id, body.category, title, description or None),
        )
        action_id = int(cur.fetchone()[0])
        conn.commit()

        category_names = {
            "technique": "영법 교정",
            "recovery": "회복 확인",
            "attendance": "출석 확인",
            "training-plan": "훈련 계획",
        }
        jira_description = (
            "SwimMate 크루 코칭 과제\n"
            f"회원: {student[0]}\n"
            f"분류: {category_names[body.category]}\n\n"
            f"{description or '코치가 SwimMate에서 생성한 확인 과제입니다.'}"
        )
        try:
            issue = JiraClient().create_issue(
                summary=title,
                description=jira_description,
                labels=["swimmate", body.category],
            )
            cur.execute(
                """UPDATE coach_action_items
                   SET sync_status = 'synced', jira_issue_key = %s, jira_issue_url = %s,
                       sync_error = NULL, updated_at = NOW()
                   WHERE id = %s""",
                (issue["key"], issue["url"], action_id),
            )
            conn.commit()
            _invalidate_jira_analytics_cache()
            return {
                "id": action_id, "sync_status": "synced",
                "jira_issue_key": issue["key"], "jira_issue_url": issue["url"],
            }
        except (JiraApiError, JiraConfigurationError) as exc:
            cur.execute(
                """UPDATE coach_action_items
                   SET sync_status = 'failed', sync_error = %s, updated_at = NOW()
                   WHERE id = %s""",
                (str(exc)[:500], action_id),
            )
            conn.commit()
            return {
                "id": action_id, "sync_status": "failed",
                "message": "SwimMate에는 저장했지만 Jira 동기화에 실패했습니다.",
            }
    except HTTPException:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        raise HTTPException(500, f"코칭 과제를 만들지 못했습니다: {exc}") from exc
    finally:
        cur.close()
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
        cur.execute(
            "SELECT id, customer_id FROM coaches WHERE invite_code = %s",
            (code,),
        )
        coach_row = cur.fetchone()
        if not coach_row:
            raise HTTPException(404, "유효하지 않은 초대코드입니다.")
        coach_id = coach_row[0]
        if coach_row[1] == student_cid:
            raise HTTPException(400, "자신의 초대코드로는 연동할 수 없습니다.")

        # 내 코치 화면과 기록 공유 대상은 한 명으로 유지한다. 새 코드를 입력하면 기존 관계를 교체한다.
        cur.execute(
            "DELETE FROM coach_students WHERE student_id = %s AND coach_id <> %s",
            (student_cid, coach_id),
        )
        cur.execute(
            "SELECT id, status FROM coach_students WHERE coach_id = %s AND student_id = %s",
            (coach_id, student_cid),
        )
        existing = cur.fetchone()
        if existing:
            conn.commit()
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


@router.delete("/my-coach")
def disconnect_my_coach(request: Request):
    """학생이 자신의 현재 코치 연동을 직접 해제한다."""
    _ensure_tables()
    username = _require_user(request)
    conn = _get_db()
    cur = conn.cursor()
    try:
        student_id = _get_customer_id(conn, username)
        cur.execute(
            """DELETE FROM coach_students
               WHERE id = (
                   SELECT id FROM coach_students
                   WHERE student_id = %s AND status = 'active'
                   ORDER BY created_at DESC LIMIT 1
               ) RETURNING id""",
            (student_id,),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "연동된 코치가 없습니다.")
        conn.commit()
        return {"disconnected": True, "relation_id": row[0]}
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(500, f"연동 해제 오류: {e}")
    finally:
        cur.close()
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
        coach_id = _require_coach(cur, cid)
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
        coach_id = _require_coach(cur, cid)
        cur.execute(
            "SELECT 1 FROM coach_students WHERE coach_id = %s AND student_id = %s AND status = 'active'",
            (coach_id, student_id),
        )
        if not cur.fetchone():
            raise HTTPException(403, "열람 권한이 없습니다.")
        cur.execute(
            """SELECT id, log_date, stroke_type, total_distance, duration_minutes, intensity, memo, mood
               FROM training_logs
               WHERE customer_id = %s
               ORDER BY log_date DESC LIMIT 20""",
            (student_id,),
        )
        logs = []
        for r in cur.fetchall():
            _pn = (str(r[2] or "") + " " + str(r[3] or 0) + "m").strip()
            if r[4]:
                _pn += " · " + str(r[4]) + "분"
            if r[5]:
                _pn += " · " + str(r[5])
            logs.append({"id": r[0], "plan_name": _pn, "log_date": str(r[1]),
                         "notes": r[6], "created_at": ""})
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
        coach_id = _require_coach(cur, cid)
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
            """SELECT cs.coach_id, c2.username, c2.name, co.specialty, co.career, co.intro, cs.status,
                      COALESCE(co.verification_status, 'unverified')
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
            """SELECT cf.id, cf.content, cf.training_log_id, cf.created_at,
                      tl.log_date, tl.stroke_type, tl.total_distance, tl.duration_minutes, tl.intensity
               FROM coach_feedbacks cf
               LEFT JOIN training_logs tl ON cf.training_log_id = tl.id
               WHERE cf.coach_id = %s AND cf.student_id = %s
               ORDER BY cf.created_at DESC LIMIT 20""",
            (coach_id, cid),
        )
        feedbacks = []
        for r in cur.fetchall():
            _ls = None
            if r[2] and r[5] is not None:
                _ls = str(r[5]) + " " + str(r[6] or 0) + "m"
                if r[7]:
                    _ls += " · " + str(r[7]) + "분"
                if r[8]:
                    _ls += " · " + str(r[8])
            feedbacks.append({
                "id": r[0], "content": r[1], "training_log_id": r[2],
                "created_at": str(r[3]),
                "log_summary": _ls,
                "log_date": str(r[4]) if r[4] else None,
            })
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
            "coach_verified": coach_row[7] == "verified",
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
        coach_id = _require_coach(cur, cid)
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
        cur.execute("SELECT to_regclass('public.notifications')")
        if cur.fetchone()[0]:
            meta = req.plan_meta or {}
            goal = str(meta.get("goal") or "훈련")
            pool = meta.get("pool_length")
            suffix = f" · {pool}m 풀" if pool else ""
            cur.execute(
                "INSERT INTO notifications (customer_id, type, message, target_id) VALUES (%s,%s,%s,%s)",
                (req.student_id, "coach_plan", f"코치가 {goal} 플랜을 보냈어요{suffix}", row[0]),
            )
        conn.commit()
        cur.close()
        return {"plan_id": row[0], "created_at": str(row[1]), "plan_meta": req.plan_meta or {}}
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
        coach_id = _require_coach(cur, cid)
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
