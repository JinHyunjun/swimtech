# -*- coding: utf-8 -*-
"""Class schedules, attendance, and scoped club/class notices."""

from datetime import date, time, timedelta
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from db import get_db as _get_db
from routers.clubs import _club_role, _customer_id


router = APIRouter()


class SessionCreateRequest(BaseModel):
    title: str = Field(..., min_length=2, max_length=100)
    session_date: date
    start_time: time
    end_time: Optional[time] = None
    location: Optional[str] = Field(default=None, max_length=120)
    lane_count: int = Field(default=1, ge=1, le=50)
    training_focus: Optional[str] = Field(default=None, max_length=200)
    notes: Optional[str] = Field(default=None, max_length=2000)


class SessionStatusRequest(BaseModel):
    status: Literal["scheduled", "completed", "cancelled"]


class AttendanceEntry(BaseModel):
    customer_id: int
    status: Literal["present", "late", "absent", "excused"]
    note: Optional[str] = Field(default=None, max_length=300)


class AttendanceSaveRequest(BaseModel):
    records: list[AttendanceEntry] = Field(..., min_length=1, max_length=500)


class NoticeCreateRequest(BaseModel):
    title: str = Field(..., min_length=2, max_length=100)
    content: str = Field(..., min_length=2, max_length=5000)
    class_id: Optional[int] = None
    is_pinned: bool = False


class NoticeStatusRequest(BaseModel):
    status: Literal["active", "archived"]


def _class_access(cur, club_id: int, class_id: int, customer_id: int, *, manage: bool = False):
    club_role = _club_role(cur, club_id, customer_id)
    cur.execute(
        "SELECT id, name, status FROM swim_classes WHERE id = %s AND club_id = %s",
        (class_id, club_id),
    )
    class_row = cur.fetchone()
    if not class_row:
        raise HTTPException(404, "반을 찾을 수 없습니다.")
    cur.execute(
        "SELECT role FROM swim_class_members WHERE class_id = %s AND customer_id = %s AND status = 'active'",
        (class_id, customer_id),
    )
    class_role_row = cur.fetchone()
    class_role = str(class_role_row[0]) if class_role_row else None
    if club_role == "member" and not class_role:
        raise HTTPException(403, "이 반에 접근할 권한이 없습니다.")
    can_manage = club_role in {"owner", "coach"} or class_role == "coach"
    if manage and not can_manage:
        raise HTTPException(403, "이 반을 운영할 권한이 없습니다.")
    return {
        "club_role": club_role,
        "class_role": class_role,
        "class_name": class_row[1],
        "class_status": class_row[2],
        "can_manage": can_manage,
    }


def _session_payload(row, can_manage: bool = False):
    return {
        "id": row[0],
        "class_id": row[1],
        "class_name": row[2],
        "club_id": row[3],
        "club_name": row[4],
        "title": row[5],
        "session_date": row[6].isoformat() if row[6] else None,
        "start_time": row[7].strftime("%H:%M") if row[7] else None,
        "end_time": row[8].strftime("%H:%M") if row[8] else None,
        "location": row[9],
        "lane_count": int(row[10] or 1),
        "training_focus": row[11],
        "notes": row[12],
        "status": row[13],
        "can_manage": can_manage,
    }


def _notice_payload(row):
    return {
        "id": row[0],
        "club_id": row[1],
        "club_name": row[2],
        "class_id": row[3],
        "class_name": row[4],
        "title": row[5],
        "content": row[6],
        "is_pinned": bool(row[7]),
        "status": row[8],
        "published_at": row[9].isoformat() if row[9] else None,
        "author_name": row[10] or row[11] or row[12] or "운영자",
        "is_read": bool(row[13]),
        "read_count": int(row[14] or 0),
    }


@router.get("/operations/mine")
def get_my_class_operations(request: Request):
    customer_id = _customer_id(request)
    conn = _get_db()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT session.id, cls.id, cls.name, club.id, club.name,
                   session.title, session.session_date, session.start_time, session.end_time,
                   session.location, session.lane_count, session.training_focus,
                   session.notes, session.status, club_member.role, class_member.role
            FROM swim_class_sessions session
            JOIN swim_classes cls ON cls.id = session.class_id
            JOIN swim_clubs club ON club.id = cls.club_id
            JOIN swim_club_members club_member
              ON club_member.club_id = club.id AND club_member.customer_id = %s
             AND club_member.status = 'active'
            LEFT JOIN swim_class_members class_member
              ON class_member.class_id = cls.id AND class_member.customer_id = %s
             AND class_member.status = 'active'
            WHERE session.session_date BETWEEN CURRENT_DATE - INTERVAL '7 days'
                                           AND CURRENT_DATE + INTERVAL '90 days'
              AND (class_member.id IS NOT NULL OR club_member.role IN ('owner', 'coach', 'assistant'))
            ORDER BY session.session_date, session.start_time
            LIMIT 100
            """,
            (customer_id, customer_id),
        )
        sessions = []
        for row in cur.fetchall():
            can_manage = row[14] in {"owner", "coach"} or row[15] == "coach"
            sessions.append(_session_payload(row[:14], can_manage))

        cur.execute(
            """
            SELECT notice.id, club.id, club.name, notice.class_id, cls.name,
                   notice.title, notice.content, notice.is_pinned, notice.status,
                   notice.published_at, author.nickname, author.name, author.username,
                   EXISTS(
                       SELECT 1 FROM swim_class_notice_reads reads
                       WHERE reads.notice_id = notice.id AND reads.customer_id = %s
                   ),
                   (SELECT COUNT(*) FROM swim_class_notice_reads reads WHERE reads.notice_id = notice.id)
            FROM swim_class_notices notice
            JOIN swim_clubs club ON club.id = notice.club_id
            JOIN swim_club_members club_member
              ON club_member.club_id = club.id AND club_member.customer_id = %s
             AND club_member.status = 'active'
            LEFT JOIN swim_classes cls ON cls.id = notice.class_id
            LEFT JOIN swim_class_members class_member
              ON class_member.class_id = notice.class_id AND class_member.customer_id = %s
             AND class_member.status = 'active'
            LEFT JOIN customers author ON author.id = notice.author_customer_id
            WHERE notice.status = 'active'
              AND (notice.class_id IS NULL OR class_member.id IS NOT NULL
                   OR club_member.role IN ('owner', 'coach', 'assistant'))
            ORDER BY notice.is_pinned DESC, notice.published_at DESC
            LIMIT 50
            """,
            (customer_id, customer_id, customer_id),
        )
        notices = [_notice_payload(row) for row in cur.fetchall()]
        return {"sessions": sessions, "notices": notices}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, f"반 운영 현황 조회 오류: {exc}")
    finally:
        cur.close()
        conn.close()


@router.post("/{club_id}/classes/{class_id}/sessions")
def create_session(club_id: int, class_id: int, body: SessionCreateRequest, request: Request):
    customer_id = _customer_id(request)
    title = body.title.strip()
    if len(title) < 2:
        raise HTTPException(400, "일정 제목은 공백을 제외하고 2자 이상 입력해주세요.")
    if body.end_time and body.end_time <= body.start_time:
        raise HTTPException(400, "종료 시간은 시작 시간보다 늦어야 합니다.")
    conn = _get_db()
    cur = conn.cursor()
    try:
        access = _class_access(cur, club_id, class_id, customer_id, manage=True)
        cur.execute(
            """
            INSERT INTO swim_class_sessions
                (class_id, created_by_customer_id, title, session_date, start_time,
                 end_time, location, lane_count, training_focus, notes)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            RETURNING id, created_at
            """,
            (
                class_id, customer_id, title, body.session_date, body.start_time,
                body.end_time, (body.location or "").strip() or None, body.lane_count,
                (body.training_focus or "").strip() or None,
                (body.notes or "").strip() or None,
            ),
        )
        session_id, created_at = cur.fetchone()
        conn.commit()
        return {
            "id": session_id,
            "club_id": club_id,
            "class_id": class_id,
            "class_name": access["class_name"],
            "title": title,
            "session_date": body.session_date.isoformat(),
            "start_time": body.start_time.strftime("%H:%M"),
            "end_time": body.end_time.strftime("%H:%M") if body.end_time else None,
            "status": "scheduled",
            "created_at": str(created_at),
        }
    except HTTPException:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        if "uq_swim_class_session_slot" in str(exc):
            raise HTTPException(409, "같은 시작 시간의 일정이 이미 있습니다.")
        raise HTTPException(500, f"반 일정 생성 오류: {exc}")
    finally:
        cur.close()
        conn.close()


@router.get("/{club_id}/classes/{class_id}/sessions")
def list_sessions(
    club_id: int,
    class_id: int,
    request: Request,
    date_from: Optional[date] = Query(default=None),
    date_to: Optional[date] = Query(default=None),
):
    customer_id = _customer_id(request)
    start = date_from or (date.today() - timedelta(days=30))
    end = date_to or (date.today() + timedelta(days=90))
    if end < start or (end - start).days > 366:
        raise HTTPException(400, "일정 조회 기간은 최대 366일입니다.")
    conn = _get_db()
    cur = conn.cursor()
    try:
        access = _class_access(cur, club_id, class_id, customer_id)
        cur.execute(
            """
            SELECT session.id, cls.id, cls.name, club.id, club.name,
                   session.title, session.session_date, session.start_time, session.end_time,
                   session.location, session.lane_count, session.training_focus,
                   session.notes, session.status
            FROM swim_class_sessions session
            JOIN swim_classes cls ON cls.id = session.class_id
            JOIN swim_clubs club ON club.id = cls.club_id
            WHERE session.class_id = %s AND session.session_date BETWEEN %s AND %s
            ORDER BY session.session_date, session.start_time
            """,
            (class_id, start, end),
        )
        sessions = [_session_payload(row, access["can_manage"]) for row in cur.fetchall()]
        return {"sessions": sessions, "count": len(sessions), "can_manage": access["can_manage"]}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, f"반 일정 조회 오류: {exc}")
    finally:
        cur.close()
        conn.close()


@router.patch("/{club_id}/classes/{class_id}/sessions/{session_id}/status")
def update_session_status(
    club_id: int,
    class_id: int,
    session_id: int,
    body: SessionStatusRequest,
    request: Request,
):
    customer_id = _customer_id(request)
    conn = _get_db()
    cur = conn.cursor()
    try:
        _class_access(cur, club_id, class_id, customer_id, manage=True)
        cur.execute(
            """
            UPDATE swim_class_sessions SET status = %s, updated_at = NOW()
            WHERE id = %s AND class_id = %s RETURNING id
            """,
            (body.status, session_id, class_id),
        )
        if not cur.fetchone():
            raise HTTPException(404, "일정을 찾을 수 없습니다.")
        conn.commit()
        return {"status": body.status, "session_id": session_id}
    except HTTPException:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        raise HTTPException(500, f"일정 상태 변경 오류: {exc}")
    finally:
        cur.close()
        conn.close()


@router.get("/{club_id}/classes/{class_id}/sessions/{session_id}/attendance")
def get_attendance(club_id: int, class_id: int, session_id: int, request: Request):
    customer_id = _customer_id(request)
    conn = _get_db()
    cur = conn.cursor()
    try:
        access = _class_access(cur, club_id, class_id, customer_id)
        cur.execute(
            "SELECT title, session_date, start_time, status FROM swim_class_sessions WHERE id = %s AND class_id = %s",
            (session_id, class_id),
        )
        session = cur.fetchone()
        if not session:
            raise HTTPException(404, "일정을 찾을 수 없습니다.")
        params = [session_id, class_id]
        member_filter = ""
        if not access["can_manage"]:
            member_filter = " AND member.customer_id = %s"
            params.append(customer_id)
        cur.execute(
            f"""
            SELECT member.customer_id, customer.nickname, customer.name, customer.username,
                   attendance.status, attendance.note, attendance.checked_at
            FROM swim_class_members member
            JOIN customers customer ON customer.id = member.customer_id
            LEFT JOIN swim_class_attendance attendance
              ON attendance.session_id = %s AND attendance.customer_id = member.customer_id
            WHERE member.class_id = %s AND member.status = 'active' AND member.role = 'student'
            {member_filter}
            ORDER BY member.joined_at
            """,
            tuple(params),
        )
        members = [{
            "customer_id": row[0],
            "display_name": row[1] or row[2] or row[3] or "회원",
            "username": row[3],
            "status": row[4],
            "note": row[5],
            "checked_at": row[6].isoformat() if row[6] else None,
        } for row in cur.fetchall()]
        return {
            "session": {
                "id": session_id,
                "title": session[0],
                "session_date": session[1].isoformat(),
                "start_time": session[2].strftime("%H:%M"),
                "status": session[3],
            },
            "members": members,
            "can_manage": access["can_manage"],
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, f"출석 조회 오류: {exc}")
    finally:
        cur.close()
        conn.close()


@router.put("/{club_id}/classes/{class_id}/sessions/{session_id}/attendance")
def save_attendance(
    club_id: int,
    class_id: int,
    session_id: int,
    body: AttendanceSaveRequest,
    request: Request,
):
    customer_id = _customer_id(request)
    ids = [record.customer_id for record in body.records]
    if len(ids) != len(set(ids)):
        raise HTTPException(400, "같은 회원의 출석이 중복되었습니다.")
    conn = _get_db()
    cur = conn.cursor()
    try:
        _class_access(cur, club_id, class_id, customer_id, manage=True)
        cur.execute(
            "SELECT 1 FROM swim_class_sessions WHERE id = %s AND class_id = %s FOR UPDATE",
            (session_id, class_id),
        )
        if not cur.fetchone():
            raise HTTPException(404, "일정을 찾을 수 없습니다.")
        cur.execute(
            """
            SELECT customer_id FROM swim_class_members
            WHERE class_id = %s AND status = 'active' AND role = 'student' AND customer_id = ANY(%s)
            """,
            (class_id, ids),
        )
        allowed_ids = {int(row[0]) for row in cur.fetchall()}
        if allowed_ids != set(ids):
            raise HTTPException(400, "현재 반 학생만 출석 처리할 수 있습니다.")
        for record in body.records:
            cur.execute(
                """
                INSERT INTO swim_class_attendance
                    (session_id, customer_id, status, note, checked_by_customer_id)
                VALUES (%s,%s,%s,%s,%s)
                ON CONFLICT (session_id, customer_id)
                DO UPDATE SET status = EXCLUDED.status, note = EXCLUDED.note,
                              checked_by_customer_id = EXCLUDED.checked_by_customer_id,
                              checked_at = NOW()
                """,
                (
                    session_id, record.customer_id, record.status,
                    (record.note or "").strip() or None, customer_id,
                ),
            )
        conn.commit()
        return {"status": "saved", "session_id": session_id, "saved_count": len(body.records)}
    except HTTPException:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        raise HTTPException(500, f"출석 저장 오류: {exc}")
    finally:
        cur.close()
        conn.close()


@router.post("/{club_id}/notices")
def create_notice(club_id: int, body: NoticeCreateRequest, request: Request):
    customer_id = _customer_id(request)
    title = body.title.strip()
    content = body.content.strip()
    if len(title) < 2 or len(content) < 2:
        raise HTTPException(400, "공지 제목과 내용을 올바르게 입력해주세요.")
    conn = _get_db()
    cur = conn.cursor()
    try:
        if body.class_id is None:
            _club_role(cur, club_id, customer_id, {"owner", "coach"})
        else:
            _class_access(cur, club_id, body.class_id, customer_id, manage=True)
        cur.execute(
            """
            INSERT INTO swim_class_notices
                (club_id, class_id, author_customer_id, title, content, is_pinned)
            VALUES (%s,%s,%s,%s,%s,%s)
            RETURNING id, published_at
            """,
            (club_id, body.class_id, customer_id, title, content, body.is_pinned),
        )
        notice_id, published_at = cur.fetchone()
        if body.class_id is None:
            cur.execute(
                """
                SELECT customer_id FROM swim_club_members
                WHERE club_id = %s AND status = 'active' AND customer_id <> %s
                """,
                (club_id, customer_id),
            )
        else:
            cur.execute(
                """
                SELECT customer_id FROM swim_class_members
                WHERE class_id = %s AND status = 'active' AND customer_id <> %s
                """,
                (body.class_id, customer_id),
            )
        recipients = [int(row[0]) for row in cur.fetchall()]
        for recipient_id in recipients:
            cur.execute(
                "INSERT INTO notifications (customer_id, type, message, target_id) VALUES (%s,%s,%s,%s)",
                (recipient_id, "class_notice", title, notice_id),
            )
        conn.commit()
        return {
            "id": notice_id,
            "club_id": club_id,
            "class_id": body.class_id,
            "title": title,
            "recipient_count": len(recipients),
            "published_at": published_at.isoformat() if published_at else None,
        }
    except HTTPException:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        raise HTTPException(500, f"공지 등록 오류: {exc}")
    finally:
        cur.close()
        conn.close()


@router.get("/{club_id}/notices")
def list_notices(
    club_id: int,
    request: Request,
    class_id: Optional[int] = Query(default=None),
):
    customer_id = _customer_id(request)
    conn = _get_db()
    cur = conn.cursor()
    try:
        club_role = _club_role(cur, club_id, customer_id)
        if class_id is not None:
            _class_access(cur, club_id, class_id, customer_id)
        params = [customer_id, club_id]
        scope_sql = ""
        if class_id is not None:
            scope_sql = " AND (notice.class_id IS NULL OR notice.class_id = %s)"
            params.append(class_id)
        elif club_role == "member":
            scope_sql = """
              AND (notice.class_id IS NULL OR EXISTS(
                  SELECT 1 FROM swim_class_members own
                  WHERE own.class_id = notice.class_id AND own.customer_id = %s AND own.status = 'active'
              ))
            """
            params.append(customer_id)
        cur.execute(
            f"""
            SELECT notice.id, club.id, club.name, notice.class_id, cls.name,
                   notice.title, notice.content, notice.is_pinned, notice.status,
                   notice.published_at, author.nickname, author.name, author.username,
                   EXISTS(
                       SELECT 1 FROM swim_class_notice_reads reads
                       WHERE reads.notice_id = notice.id AND reads.customer_id = %s
                   ),
                   (SELECT COUNT(*) FROM swim_class_notice_reads reads WHERE reads.notice_id = notice.id)
            FROM swim_class_notices notice
            JOIN swim_clubs club ON club.id = notice.club_id
            LEFT JOIN swim_classes cls ON cls.id = notice.class_id
            LEFT JOIN customers author ON author.id = notice.author_customer_id
            WHERE notice.club_id = %s AND notice.status = 'active'
            {scope_sql}
            ORDER BY notice.is_pinned DESC, notice.published_at DESC
            LIMIT 100
            """,
            tuple(params),
        )
        notices = [_notice_payload(row) for row in cur.fetchall()]
        return {"notices": notices, "count": len(notices)}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, f"공지 조회 오류: {exc}")
    finally:
        cur.close()
        conn.close()


@router.post("/{club_id}/notices/{notice_id}/read")
def mark_notice_read(club_id: int, notice_id: int, request: Request):
    customer_id = _customer_id(request)
    conn = _get_db()
    cur = conn.cursor()
    try:
        club_role = _club_role(cur, club_id, customer_id)
        cur.execute(
            "SELECT class_id FROM swim_class_notices WHERE id = %s AND club_id = %s AND status = 'active'",
            (notice_id, club_id),
        )
        notice = cur.fetchone()
        if not notice:
            raise HTTPException(404, "공지를 찾을 수 없습니다.")
        if notice[0] is not None and club_role == "member":
            _class_access(cur, club_id, int(notice[0]), customer_id)
        cur.execute(
            """
            INSERT INTO swim_class_notice_reads (notice_id, customer_id)
            VALUES (%s,%s)
            ON CONFLICT (notice_id, customer_id) DO UPDATE SET read_at = NOW()
            RETURNING read_at
            """,
            (notice_id, customer_id),
        )
        read_at = cur.fetchone()[0]
        conn.commit()
        return {"status": "read", "notice_id": notice_id, "read_at": read_at.isoformat()}
    except HTTPException:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        raise HTTPException(500, f"공지 읽음 처리 오류: {exc}")
    finally:
        cur.close()
        conn.close()


@router.patch("/{club_id}/notices/{notice_id}/status")
def update_notice_status(
    club_id: int,
    notice_id: int,
    body: NoticeStatusRequest,
    request: Request,
):
    customer_id = _customer_id(request)
    conn = _get_db()
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT class_id FROM swim_class_notices WHERE id = %s AND club_id = %s",
            (notice_id, club_id),
        )
        notice = cur.fetchone()
        if not notice:
            raise HTTPException(404, "공지를 찾을 수 없습니다.")
        if notice[0] is None:
            _club_role(cur, club_id, customer_id, {"owner", "coach"})
        else:
            _class_access(cur, club_id, int(notice[0]), customer_id, manage=True)
        cur.execute(
            "UPDATE swim_class_notices SET status = %s, updated_at = NOW() WHERE id = %s RETURNING id",
            (body.status, notice_id),
        )
        conn.commit()
        return {"status": body.status, "notice_id": notice_id}
    except HTTPException:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        raise HTTPException(500, f"공지 상태 변경 오류: {exc}")
    finally:
        cur.close()
        conn.close()
