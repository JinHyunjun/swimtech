# -*- coding: utf-8 -*-
"""SwimMate club, class, and scoped role management."""

import secrets
import string
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from db import get_db as _get_db
from routers.auth import decode_token


router = APIRouter()

_CLUB_ROLES = {"owner", "coach", "assistant", "member"}
_CLASS_ROLES = {"coach", "assistant", "student"}
_STAFF_ROLES = {"coach", "assistant"}


class ClubCreateRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=80)
    description: Optional[str] = Field(default=None, max_length=500)
    default_pool_length: int = 25


class ClubUpdateRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=80)
    description: Optional[str] = Field(default=None, max_length=500)
    default_pool_length: int = 25
    status: str = "active"


class ClassCreateRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=80)
    level: str = Field(default="혼합", min_length=1, max_length=30)
    goal: Optional[str] = Field(default=None, max_length=80)
    pool_length: int = 25
    max_members: int = Field(default=30, ge=1, le=500)


class JoinClassRequest(BaseModel):
    invite_code: str = Field(..., min_length=5, max_length=20)


class RoleUpdateRequest(BaseModel):
    role: str = Field(..., min_length=3, max_length=20)


def _customer_id(request: Request) -> int:
    token = request.cookies.get("swimtech_token")
    payload = decode_token(token) if token else None
    customer_id = payload.get("customer_id") if payload else None
    if not customer_id:
        raise HTTPException(401, "로그인이 필요합니다.")
    return int(customer_id)


def _registered_coach_id(cur, customer_id: int, *, required: bool = True) -> Optional[int]:
    cur.execute("SELECT id FROM coaches WHERE customer_id = %s", (customer_id,))
    row = cur.fetchone()
    if not row and required:
        raise HTTPException(403, "등록 코치만 클럽과 반을 만들 수 있습니다.")
    return int(row[0]) if row else None


def _club_role(cur, club_id: int, customer_id: int, allowed: Optional[set[str]] = None) -> str:
    cur.execute(
        """
        SELECT role FROM swim_club_members
        WHERE club_id = %s AND customer_id = %s AND status = 'active'
        """,
        (club_id, customer_id),
    )
    row = cur.fetchone()
    if not row:
        raise HTTPException(403, "이 클럽에 접근할 권한이 없습니다.")
    role = str(row[0])
    if allowed is not None and role not in allowed:
        raise HTTPException(403, "이 작업을 수행할 클럽 권한이 없습니다.")
    return role


def _unique_code(cur, table: str, prefix: str) -> str:
    if table not in {"swim_clubs", "swim_classes"}:
        raise ValueError("unsupported invite-code table")
    alphabet = string.ascii_uppercase + string.digits
    for _ in range(20):
        code = prefix + "-" + "".join(secrets.choice(alphabet) for _ in range(6))
        cur.execute(f"SELECT 1 FROM {table} WHERE invite_code = %s", (code,))
        if not cur.fetchone():
            return code
    raise HTTPException(503, "초대 코드를 만들지 못했습니다. 잠시 후 다시 시도해주세요.")


def _display_name(row) -> str:
    return row[0] or row[1] or row[2] or "회원"


@router.post("")
def create_club(body: ClubCreateRequest, request: Request):
    customer_id = _customer_id(request)
    if body.default_pool_length not in (25, 50):
        raise HTTPException(400, "수영장 길이는 25m 또는 50m여야 합니다.")
    name = body.name.strip()
    if len(name) < 2:
        raise HTTPException(400, "클럽 이름은 공백을 제외하고 2자 이상 입력해주세요.")
    description = (body.description or "").strip() or None
    conn = _get_db()
    cur = conn.cursor()
    try:
        coach_id = _registered_coach_id(cur, customer_id)
        invite_code = _unique_code(cur, "swim_clubs", "CLUB")
        cur.execute(
            """
            INSERT INTO swim_clubs
                (owner_coach_id, name, description, default_pool_length, invite_code)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id, created_at
            """,
            (coach_id, name, description, body.default_pool_length, invite_code),
        )
        club_id, created_at = cur.fetchone()
        cur.execute(
            """
            INSERT INTO swim_club_members (club_id, customer_id, role, status)
            VALUES (%s, %s, 'owner', 'active')
            """,
            (club_id, customer_id),
        )
        conn.commit()
        return {
            "id": club_id,
            "name": name,
            "description": description,
            "default_pool_length": body.default_pool_length,
            "invite_code": invite_code,
            "my_role": "owner",
            "created_at": str(created_at),
        }
    except HTTPException:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        raise HTTPException(500, f"클럽 생성 오류: {exc}")
    finally:
        cur.close()
        conn.close()


@router.get("/mine")
def list_my_clubs(request: Request):
    customer_id = _customer_id(request)
    conn = _get_db()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT club.id, club.name, club.description, club.default_pool_length,
                   club.invite_code, club.status, member.role, club.created_at,
                   (SELECT COUNT(*) FROM swim_club_members m
                    WHERE m.club_id = club.id AND m.status = 'active') AS member_count,
                   (SELECT COUNT(*) FROM swim_classes cls
                    WHERE cls.club_id = club.id AND cls.status = 'active') AS class_count
            FROM swim_club_members member
            JOIN swim_clubs club ON club.id = member.club_id
            WHERE member.customer_id = %s AND member.status = 'active'
            ORDER BY club.created_at DESC
            """,
            (customer_id,),
        )
        rows = cur.fetchall()
        clubs = [{
            "id": row[0],
            "name": row[1],
            "description": row[2],
            "default_pool_length": row[3],
            "invite_code": row[4] if row[6] in {"owner", "coach"} else None,
            "status": row[5],
            "my_role": row[6],
            "can_manage": row[6] in {"owner", "coach"},
            "created_at": str(row[7]),
            "member_count": int(row[8] or 0),
            "class_count": int(row[9] or 0),
            "classes": [],
        } for row in rows]
        club_ids = [item["id"] for item in clubs]
        if club_ids:
            cur.execute(
                """
                SELECT cls.id, cls.club_id, cls.name, cls.level, cls.goal,
                       cls.pool_length, cls.max_members, cls.invite_code, cls.status,
                       own.role,
                       (SELECT COUNT(*) FROM swim_class_members members
                        WHERE members.class_id = cls.id AND members.status = 'active') AS member_count
                FROM swim_classes cls
                LEFT JOIN swim_class_members own
                  ON own.class_id = cls.id AND own.customer_id = %s AND own.status = 'active'
                WHERE cls.club_id = ANY(%s) AND cls.status = 'active'
                ORDER BY cls.created_at ASC
                """,
                (customer_id, club_ids),
            )
            by_club = {item["id"]: item for item in clubs}
            for row in cur.fetchall():
                club = by_club[row[1]]
                club["classes"].append({
                    "id": row[0],
                    "name": row[2],
                    "level": row[3],
                    "goal": row[4],
                    "pool_length": row[5],
                    "max_members": row[6],
                    "invite_code": row[7] if club["can_manage"] or row[9] in {"coach", "assistant"} else None,
                    "status": row[8],
                    "my_role": row[9],
                    "member_count": int(row[10] or 0),
                })
        return {"clubs": clubs, "count": len(clubs)}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, f"클럽 목록 조회 오류: {exc}")
    finally:
        cur.close()
        conn.close()


@router.get("/{club_id}")
def get_club(club_id: int, request: Request):
    customer_id = _customer_id(request)
    conn = _get_db()
    cur = conn.cursor()
    try:
        my_role = _club_role(cur, club_id, customer_id)
        cur.execute(
            """
            SELECT club.id, club.name, club.description, club.default_pool_length,
                   club.invite_code, club.status, club.created_at
            FROM swim_clubs club WHERE club.id = %s
            """,
            (club_id,),
        )
        club = cur.fetchone()
        if not club:
            raise HTTPException(404, "클럽을 찾을 수 없습니다.")
        cur.execute(
            """
            SELECT member.customer_id, customer.nickname, customer.name, customer.username,
                   member.role, member.status, member.joined_at,
                   EXISTS(SELECT 1 FROM coaches coach WHERE coach.customer_id = member.customer_id)
            FROM swim_club_members member
            JOIN customers customer ON customer.id = member.customer_id
            WHERE member.club_id = %s AND member.status = 'active'
            ORDER BY CASE member.role WHEN 'owner' THEN 0 WHEN 'coach' THEN 1
                                      WHEN 'assistant' THEN 2 ELSE 3 END,
                     member.joined_at
            """,
            (club_id,),
        )
        members = [{
            "customer_id": row[0],
            "display_name": _display_name((row[1], row[2], row[3])),
            "username": row[3],
            "role": row[4],
            "status": row[5],
            "joined_at": str(row[6]),
            "is_registered_coach": bool(row[7]),
        } for row in cur.fetchall()]
        cur.execute(
            """
            SELECT cls.id, cls.name, cls.level, cls.goal, cls.pool_length,
                   cls.max_members, cls.invite_code, cls.status,
                   (SELECT COUNT(*) FROM swim_class_members members
                    WHERE members.class_id = cls.id AND members.status = 'active') AS member_count
            FROM swim_classes cls
            WHERE cls.club_id = %s
            ORDER BY cls.created_at
            """,
            (club_id,),
        )
        classes = [{
            "id": row[0], "name": row[1], "level": row[2], "goal": row[3],
            "pool_length": row[4], "max_members": row[5],
            "invite_code": row[6] if my_role in {"owner", "coach", "assistant"} else None,
            "status": row[7], "member_count": int(row[8] or 0),
        } for row in cur.fetchall()]
        return {
            "club": {
                "id": club[0], "name": club[1], "description": club[2],
                "default_pool_length": club[3],
                "invite_code": club[4] if my_role in {"owner", "coach"} else None,
                "status": club[5], "created_at": str(club[6]),
                "my_role": my_role, "can_manage": my_role in {"owner", "coach"},
            },
            "members": members,
            "classes": classes,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, f"클럽 조회 오류: {exc}")
    finally:
        cur.close()
        conn.close()


@router.put("/{club_id}")
def update_club(club_id: int, body: ClubUpdateRequest, request: Request):
    customer_id = _customer_id(request)
    if body.default_pool_length not in (25, 50):
        raise HTTPException(400, "수영장 길이는 25m 또는 50m여야 합니다.")
    status = body.status.strip().lower()
    if status not in {"active", "archived"}:
        raise HTTPException(400, "클럽 상태 값이 올바르지 않습니다.")
    name = body.name.strip()
    if len(name) < 2:
        raise HTTPException(400, "클럽 이름은 공백을 제외하고 2자 이상 입력해주세요.")
    conn = _get_db()
    cur = conn.cursor()
    try:
        _club_role(cur, club_id, customer_id, {"owner"})
        cur.execute(
            """
            UPDATE swim_clubs
            SET name = %s, description = %s, default_pool_length = %s,
                status = %s, updated_at = NOW()
            WHERE id = %s RETURNING id
            """,
            (name, (body.description or "").strip() or None,
             body.default_pool_length, status, club_id),
        )
        if not cur.fetchone():
            raise HTTPException(404, "클럽을 찾을 수 없습니다.")
        conn.commit()
        return {"status": "updated", "club_id": club_id}
    except HTTPException:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        raise HTTPException(500, f"클럽 수정 오류: {exc}")
    finally:
        cur.close()
        conn.close()


@router.delete("/{club_id}")
def delete_club(club_id: int, request: Request):
    customer_id = _customer_id(request)
    conn = _get_db()
    cur = conn.cursor()
    try:
        _club_role(cur, club_id, customer_id, {"owner"})
        cur.execute("DELETE FROM swim_clubs WHERE id = %s RETURNING id", (club_id,))
        if not cur.fetchone():
            raise HTTPException(404, "클럽을 찾을 수 없습니다.")
        conn.commit()
        return {"status": "deleted", "club_id": club_id}
    except HTTPException:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        raise HTTPException(500, f"클럽 삭제 오류: {exc}")
    finally:
        cur.close()
        conn.close()


@router.post("/{club_id}/classes")
def create_class(club_id: int, body: ClassCreateRequest, request: Request):
    customer_id = _customer_id(request)
    if body.pool_length not in (25, 50):
        raise HTTPException(400, "수영장 길이는 25m 또는 50m여야 합니다.")
    name = body.name.strip()
    level = body.level.strip()
    if len(name) < 2 or not level:
        raise HTTPException(400, "반 이름과 수준을 올바르게 입력해주세요.")
    conn = _get_db()
    cur = conn.cursor()
    try:
        _club_role(cur, club_id, customer_id, {"owner", "coach"})
        _registered_coach_id(cur, customer_id)
        invite_code = _unique_code(cur, "swim_classes", "LANE")
        cur.execute(
            """
            INSERT INTO swim_classes
                (club_id, lead_coach_customer_id, name, level, goal,
                 pool_length, max_members, invite_code)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, created_at
            """,
            (club_id, customer_id, name, level,
             (body.goal or "").strip() or None, body.pool_length,
             body.max_members, invite_code),
        )
        class_id, created_at = cur.fetchone()
        cur.execute(
            """
            INSERT INTO swim_class_members (class_id, customer_id, role, status)
            VALUES (%s, %s, 'coach', 'active')
            """,
            (class_id, customer_id),
        )
        conn.commit()
        return {
            "id": class_id, "club_id": club_id, "name": name,
            "level": level, "goal": (body.goal or "").strip() or None,
            "pool_length": body.pool_length, "max_members": body.max_members,
            "invite_code": invite_code, "my_role": "coach", "created_at": str(created_at),
        }
    except HTTPException:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        raise HTTPException(500, f"반 생성 오류: {exc}")
    finally:
        cur.close()
        conn.close()


@router.post("/classes/join")
def join_class(body: JoinClassRequest, request: Request):
    customer_id = _customer_id(request)
    code = body.invite_code.strip().upper()
    conn = _get_db()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT cls.id, cls.club_id, cls.name, club.name, cls.max_members,
                   (SELECT COUNT(*) FROM swim_class_members members
                    WHERE members.class_id = cls.id AND members.status = 'active')
            FROM swim_classes cls
            JOIN swim_clubs club ON club.id = cls.club_id
            WHERE cls.invite_code = %s AND cls.status = 'active' AND club.status = 'active'
            FOR UPDATE
            """,
            (code,),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "유효한 반 코드를 찾을 수 없습니다.")
        class_id, club_id, class_name, club_name, max_members, member_count = row
        cur.execute(
            "SELECT role, status FROM swim_class_members WHERE class_id = %s AND customer_id = %s",
            (class_id, customer_id),
        )
        existing = cur.fetchone()
        is_active_member = bool(existing and str(existing[1]) == "active")
        if not is_active_member and int(member_count or 0) >= int(max_members):
            raise HTTPException(409, "이 반은 정원이 찼습니다.")
        cur.execute(
            """
            INSERT INTO swim_club_members (club_id, customer_id, role, status)
            VALUES (%s, %s, 'member', 'active')
            ON CONFLICT (club_id, customer_id)
            DO UPDATE SET status = 'active', updated_at = NOW()
            """,
            (club_id, customer_id),
        )
        cur.execute(
            """
            INSERT INTO swim_class_members (class_id, customer_id, role, status)
            VALUES (%s, %s, 'student', 'active')
            ON CONFLICT (class_id, customer_id)
            DO UPDATE SET status = 'active', updated_at = NOW()
            """,
            (class_id, customer_id),
        )
        conn.commit()
        return {
            "status": "joined", "club_id": club_id, "class_id": class_id,
            "club_name": club_name, "class_name": class_name,
        }
    except HTTPException:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        raise HTTPException(500, f"반 참여 오류: {exc}")
    finally:
        cur.close()
        conn.close()


@router.get("/{club_id}/classes/{class_id}")
def get_class(club_id: int, class_id: int, request: Request):
    customer_id = _customer_id(request)
    conn = _get_db()
    cur = conn.cursor()
    try:
        club_role = _club_role(cur, club_id, customer_id)
        cur.execute(
            "SELECT role FROM swim_class_members WHERE class_id = %s AND customer_id = %s AND status = 'active'",
            (class_id, customer_id),
        )
        class_role_row = cur.fetchone()
        if club_role == "member" and not class_role_row:
            raise HTTPException(403, "이 반을 볼 권한이 없습니다.")
        cur.execute(
            """
            SELECT id, name, level, goal, pool_length, max_members, invite_code, status
            FROM swim_classes WHERE id = %s AND club_id = %s
            """,
            (class_id, club_id),
        )
        class_row = cur.fetchone()
        if not class_row:
            raise HTTPException(404, "반을 찾을 수 없습니다.")
        cur.execute(
            """
            SELECT member.customer_id, customer.nickname, customer.name, customer.username,
                   member.role, member.status, member.joined_at,
                   EXISTS(SELECT 1 FROM coaches coach WHERE coach.customer_id = member.customer_id)
            FROM swim_class_members member
            JOIN customers customer ON customer.id = member.customer_id
            WHERE member.class_id = %s AND member.status = 'active'
            ORDER BY CASE member.role WHEN 'coach' THEN 0 WHEN 'assistant' THEN 1 ELSE 2 END,
                     member.joined_at
            """,
            (class_id,),
        )
        members = [{
            "customer_id": row[0], "display_name": _display_name((row[1], row[2], row[3])),
            "username": row[3], "role": row[4], "status": row[5],
            "joined_at": str(row[6]), "is_registered_coach": bool(row[7]),
        } for row in cur.fetchall()]
        class_role = str(class_role_row[0]) if class_role_row else None
        can_manage = club_role in {"owner", "coach"} or class_role == "coach"
        return {
            "class": {
                "id": class_row[0], "club_id": club_id, "name": class_row[1],
                "level": class_row[2], "goal": class_row[3], "pool_length": class_row[4],
                "max_members": class_row[5],
                "invite_code": class_row[6] if can_manage or club_role == "assistant" else None,
                "status": class_row[7],
                "my_role": class_role,
                "can_manage": can_manage,
            },
            "members": members,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, f"반 조회 오류: {exc}")
    finally:
        cur.close()
        conn.close()


@router.put("/{club_id}/members/{member_customer_id}/role")
def update_club_member_role(
    club_id: int,
    member_customer_id: int,
    body: RoleUpdateRequest,
    request: Request,
):
    customer_id = _customer_id(request)
    role = body.role.strip().lower()
    if role not in _CLUB_ROLES or role == "owner":
        raise HTTPException(400, "변경 가능한 클럽 역할이 아닙니다.")
    conn = _get_db()
    cur = conn.cursor()
    try:
        _club_role(cur, club_id, customer_id, {"owner"})
        cur.execute(
            "SELECT role FROM swim_club_members WHERE club_id = %s AND customer_id = %s FOR UPDATE",
            (club_id, member_customer_id),
        )
        target = cur.fetchone()
        if not target:
            raise HTTPException(404, "클럽 회원을 찾을 수 없습니다.")
        if target[0] == "owner":
            raise HTTPException(400, "클럽 소유자 역할은 변경할 수 없습니다.")
        if role in _STAFF_ROLES:
            _registered_coach_id(cur, member_customer_id)
        cur.execute(
            """
            UPDATE swim_club_members SET role = %s, status = 'active', updated_at = NOW()
            WHERE club_id = %s AND customer_id = %s
            """,
            (role, club_id, member_customer_id),
        )
        conn.commit()
        return {"status": "updated", "club_id": club_id, "customer_id": member_customer_id, "role": role}
    except HTTPException:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        raise HTTPException(500, f"클럽 역할 변경 오류: {exc}")
    finally:
        cur.close()
        conn.close()


@router.put("/{club_id}/classes/{class_id}/members/{member_customer_id}/role")
def update_class_member_role(
    club_id: int,
    class_id: int,
    member_customer_id: int,
    body: RoleUpdateRequest,
    request: Request,
):
    customer_id = _customer_id(request)
    role = body.role.strip().lower()
    if role not in _CLASS_ROLES:
        raise HTTPException(400, "변경 가능한 반 역할이 아닙니다.")
    conn = _get_db()
    cur = conn.cursor()
    try:
        club_role = _club_role(cur, club_id, customer_id)
        cur.execute("SELECT 1 FROM swim_classes WHERE id = %s AND club_id = %s", (class_id, club_id))
        if not cur.fetchone():
            raise HTTPException(404, "반을 찾을 수 없습니다.")
        cur.execute(
            "SELECT role FROM swim_class_members WHERE class_id = %s AND customer_id = %s AND status = 'active'",
            (class_id, customer_id),
        )
        actor_class_role = cur.fetchone()
        if club_role not in {"owner", "coach"} and (not actor_class_role or actor_class_role[0] != "coach"):
            raise HTTPException(403, "이 반의 역할을 변경할 권한이 없습니다.")
        cur.execute(
            "SELECT 1 FROM swim_club_members WHERE club_id = %s AND customer_id = %s AND status = 'active'",
            (club_id, member_customer_id),
        )
        if not cur.fetchone():
            raise HTTPException(404, "클럽 회원을 찾을 수 없습니다.")
        if role in _STAFF_ROLES:
            _registered_coach_id(cur, member_customer_id)
        cur.execute(
            "SELECT lead_coach_customer_id FROM swim_classes WHERE id = %s AND club_id = %s",
            (class_id, club_id),
        )
        lead_coach = cur.fetchone()
        if lead_coach and int(lead_coach[0] or 0) == member_customer_id and role != "coach":
            raise HTTPException(400, "담당 코치는 학생이나 보조 코치로 변경할 수 없습니다.")
        cur.execute(
            """
            UPDATE swim_class_members SET role = %s, status = 'active', updated_at = NOW()
            WHERE class_id = %s AND customer_id = %s RETURNING id
            """,
            (role, class_id, member_customer_id),
        )
        if not cur.fetchone():
            raise HTTPException(404, "반 회원을 찾을 수 없습니다.")
        conn.commit()
        return {"status": "updated", "class_id": class_id, "customer_id": member_customer_id, "role": role}
    except HTTPException:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        raise HTTPException(500, f"반 역할 변경 오류: {exc}")
    finally:
        cur.close()
        conn.close()


@router.delete("/{club_id}/classes/{class_id}/me")
def leave_class(club_id: int, class_id: int, request: Request):
    customer_id = _customer_id(request)
    conn = _get_db()
    cur = conn.cursor()
    try:
        _club_role(cur, club_id, customer_id)
        cur.execute(
            "SELECT lead_coach_customer_id FROM swim_classes WHERE id = %s AND club_id = %s",
            (class_id, club_id),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "반을 찾을 수 없습니다.")
        if row[0] == customer_id:
            raise HTTPException(400, "담당 코치는 반에서 나갈 수 없습니다.")
        cur.execute(
            "DELETE FROM swim_class_members WHERE class_id = %s AND customer_id = %s RETURNING id",
            (class_id, customer_id),
        )
        if not cur.fetchone():
            raise HTTPException(404, "참여 중인 반이 아닙니다.")
        conn.commit()
        return {"status": "left", "class_id": class_id}
    except HTTPException:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        raise HTTPException(500, f"반 나가기 오류: {exc}")
    finally:
        cur.close()
        conn.close()


@router.delete("/{club_id}/me")
def leave_club(club_id: int, request: Request):
    customer_id = _customer_id(request)
    conn = _get_db()
    cur = conn.cursor()
    try:
        role = _club_role(cur, club_id, customer_id)
        if role == "owner":
            raise HTTPException(400, "클럽 소유자는 클럽을 삭제하거나 소유권 이전 후 나갈 수 있습니다.")
        cur.execute(
            "SELECT 1 FROM swim_classes WHERE club_id = %s AND lead_coach_customer_id = %s AND status = 'active'",
            (club_id, customer_id),
        )
        if cur.fetchone():
            raise HTTPException(400, "담당 중인 반이 있어 클럽에서 나갈 수 없습니다.")
        cur.execute(
            """
            DELETE FROM swim_class_members class_member
            USING swim_classes cls
            WHERE class_member.class_id = cls.id AND cls.club_id = %s
              AND class_member.customer_id = %s
            """,
            (club_id, customer_id),
        )
        cur.execute(
            "DELETE FROM swim_club_members WHERE club_id = %s AND customer_id = %s RETURNING id",
            (club_id, customer_id),
        )
        if not cur.fetchone():
            raise HTTPException(404, "참여 중인 클럽이 아닙니다.")
        conn.commit()
        return {"status": "left", "club_id": club_id}
    except HTTPException:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        raise HTTPException(500, f"클럽 나가기 오류: {exc}")
    finally:
        cur.close()
        conn.close()
