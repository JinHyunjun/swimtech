# -*- coding: utf-8 -*-
"""Privacy-first result cards and public club promotion campaigns."""

from datetime import date, datetime, timezone
from io import BytesIO
import os
import secrets
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field
from psycopg2.extras import Json
import qrcode
import qrcode.image.svg

from db import get_db as _get_db
from rate_limit import limiter
from routers.clubs import _club_role, _customer_id
from routers.report import _calc_monthly_stats


router = APIRouter()


class MonthlyResultShareRequest(BaseModel):
    year: int = Field(..., ge=2000, le=2100)
    month: int = Field(..., ge=1, le=12)
    show_nickname: bool = False


class ClubCampaignRequest(BaseModel):
    headline: str = Field(..., min_length=2, max_length=120)
    class_id: Optional[int] = Field(default=None, ge=1)
    target_distance: int = Field(..., ge=1000, le=100_000_000)
    start_date: date
    end_date: date
    is_public: bool = False
    show_member_count: bool = True


class ClubCampaignConsentRequest(BaseModel):
    include_my_distance: bool = False


def _new_token() -> str:
    return secrets.token_urlsafe(24)


def _iso(value) -> Optional[str]:
    return value.isoformat() if value else None


def _result_snapshot(stats: dict) -> dict:
    """Whitelist only promotion-safe aggregate fields.

    Raw dates, locations, heart rate, memos, screenshots and individual sets are
    intentionally never copied to a public share.
    """
    plan = stats.get("plan_performance") or {}
    benchmark = stats.get("benchmark_performance") or {}
    return {
        "year": int(stats.get("year") or 0),
        "month": int(stats.get("month") or 0),
        "total_distance": int(stats.get("total_distance") or 0),
        "total_count": int(stats.get("total_count") or 0),
        "avg_distance": int(stats.get("avg_distance") or 0),
        "total_time": int(stats.get("total_time") or 0),
        "growth_rate": float(stats.get("growth_rate") or 0),
        "streak": int(stats.get("streak") or 0),
        "by_stroke": {
            key: int((stats.get("by_stroke") or {}).get(key) or 0)
            for key in ("freestyle", "backstroke", "breaststroke", "butterfly", "other")
        },
        "plan_performance": {
            "completed_sessions": int(plan.get("completed_sessions") or 0),
            "plan_distance_rate": int(plan.get("plan_distance_rate") or 0),
            "cycle_adherence_rate": int(plan.get("cycle_adherence_rate") or 0),
            "set_completion_rate": int(plan.get("set_completion_rate") or 0),
            "goal_achievement_rate": int(plan.get("goal_achievement_rate") or 0),
        },
        "benchmark_performance": {
            "attempts": int(benchmark.get("attempts") or 0),
            "personal_bests": int(benchmark.get("personal_bests") or 0),
        },
    }


@router.post("/result-shares/monthly")
@limiter.limit("30/hour")
def create_monthly_result_share(body: MonthlyResultShareRequest, request: Request):
    customer_id = _customer_id(request)
    stats = _calc_monthly_stats(customer_id, body.year, body.month)
    if int(stats.get("total_count") or 0) < 1:
        raise HTTPException(400, "공유할 월간 훈련 기록이 없습니다.")

    conn = _get_db()
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM promotion_result_shares WHERE expires_at <= NOW()")
        display_name = None
        if body.show_nickname:
            cur.execute(
                "SELECT COALESCE(NULLIF(nickname, ''), NULLIF(name, ''), username) "
                "FROM customers WHERE id = %s",
                (customer_id,),
            )
            row = cur.fetchone()
            display_name = str(row[0])[:80] if row and row[0] else None

        token = _new_token()
        cur.execute(
            """
            INSERT INTO promotion_result_shares
                (customer_id, token, period_year, period_month, snapshot,
                 display_name, show_nickname)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING created_at, expires_at
            """,
            (
                customer_id,
                token,
                body.year,
                body.month,
                Json(_result_snapshot(stats)),
                display_name,
                body.show_nickname,
            ),
        )
        created_at, expires_at = cur.fetchone()
        conn.commit()
        return {
            "token": token,
            "public_url": f"/result/{token}",
            "show_nickname": body.show_nickname,
            "created_at": _iso(created_at),
            "expires_at": _iso(expires_at),
            "privacy": "위치·심박·메모·원본 스크린샷은 공유되지 않습니다.",
        }
    except HTTPException:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        raise HTTPException(500, f"결과 카드 생성 오류: {exc}")
    finally:
        cur.close()
        conn.close()


@router.get("/result-shares/mine")
def list_my_result_shares(request: Request):
    customer_id = _customer_id(request)
    conn = _get_db()
    cur = conn.cursor()
    try:
        cur.execute(
            "DELETE FROM promotion_result_shares WHERE customer_id = %s AND expires_at <= NOW()",
            (customer_id,),
        )
        cur.execute(
            """
            SELECT token, period_year, period_month, show_nickname, status,
                   view_count, created_at, expires_at
            FROM promotion_result_shares
            WHERE customer_id = %s
            ORDER BY created_at DESC
            LIMIT 50
            """,
            (customer_id,),
        )
        items = [
            {
                "token": row[0], "year": row[1], "month": row[2],
                "show_nickname": bool(row[3]), "status": row[4],
                "view_count": int(row[5] or 0), "created_at": _iso(row[6]),
                "expires_at": _iso(row[7]), "public_url": f"/result/{row[0]}",
            }
            for row in cur.fetchall()
        ]
        conn.commit()
        return {"items": items, "count": len(items)}
    finally:
        cur.close()
        conn.close()


@router.delete("/result-shares/{token}")
def revoke_result_share(token: str, request: Request):
    customer_id = _customer_id(request)
    conn = _get_db()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            UPDATE promotion_result_shares
            SET status = 'revoked'
            WHERE token = %s AND customer_id = %s AND status = 'active'
            RETURNING id
            """,
            (token, customer_id),
        )
        if not cur.fetchone():
            raise HTTPException(404, "활성 공유 카드를 찾을 수 없습니다.")
        conn.commit()
        return {"revoked": True, "token": token}
    except HTTPException:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


@router.get("/public/results/{token}")
@limiter.limit("60/minute")
def get_public_result_share(token: str, request: Request):
    conn = _get_db()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT snapshot, display_name, show_nickname, status, created_at, expires_at
            FROM promotion_result_shares WHERE token = %s
            """,
            (token,),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "공유 카드를 찾을 수 없습니다.")
        if row[5] and row[5] <= datetime.now(timezone.utc):
            cur.execute("DELETE FROM promotion_result_shares WHERE token = %s", (token,))
            conn.commit()
            raise HTTPException(410, "유효기간이 끝난 카드입니다.")
        if row[3] != "active":
            raise HTTPException(410, "공유가 종료된 카드입니다.")
        cur.execute(
            """
            UPDATE promotion_result_shares
            SET view_count = view_count + 1, last_viewed_at = NOW()
            WHERE token = %s
            """,
            (token,),
        )
        conn.commit()
        return {
            "result": row[0],
            "display_name": row[1] if row[2] else None,
            "created_at": _iso(row[4]),
            "expires_at": _iso(row[5]),
            "privacy": "훈련 위치·심박·메모·원본 스크린샷은 포함되지 않습니다.",
        }
    except HTTPException:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


def _campaign_payload(cur, club_id: int) -> Optional[dict]:
    cur.execute(
        """
        SELECT campaign.public_token, campaign.headline, campaign.class_id,
               cls.name, campaign.target_distance, campaign.start_date,
               campaign.end_date, campaign.is_public, campaign.show_member_count,
               campaign.view_count, campaign.created_at, campaign.updated_at
        FROM club_promotion_campaigns campaign
        LEFT JOIN swim_classes cls ON cls.id = campaign.class_id
        WHERE campaign.club_id = %s
        """,
        (club_id,),
    )
    row = cur.fetchone()
    if not row:
        return None
    return {
        "public_token": row[0], "headline": row[1], "class_id": row[2],
        "class_name": row[3], "target_distance": int(row[4]),
        "start_date": _iso(row[5]), "end_date": _iso(row[6]),
        "is_public": bool(row[7]), "show_member_count": bool(row[8]),
        "view_count": int(row[9] or 0), "created_at": _iso(row[10]),
        "updated_at": _iso(row[11]), "public_url": f"/club/{row[0]}",
        "qr_url": f"/api/promotion/public/clubs/{row[0]}/qr.svg",
    }


@router.get("/clubs/{club_id}/campaign")
def get_club_campaign(club_id: int, request: Request):
    customer_id = _customer_id(request)
    conn = _get_db()
    cur = conn.cursor()
    try:
        _club_role(cur, club_id, customer_id, {"owner", "coach"})
        return {"campaign": _campaign_payload(cur, club_id)}
    finally:
        cur.close()
        conn.close()


@router.put("/clubs/{club_id}/campaign/consent")
def update_club_campaign_consent(club_id: int, body: ClubCampaignConsentRequest, request: Request):
    customer_id = _customer_id(request)
    conn = _get_db()
    cur = conn.cursor()
    try:
        _club_role(cur, club_id, customer_id)
        cur.execute(
            """
            UPDATE swim_club_members
            SET promotion_distance_opt_in = %s
            WHERE club_id = %s AND customer_id = %s AND status = 'active'
            RETURNING promotion_distance_opt_in
            """,
            (body.include_my_distance, club_id, customer_id),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "활성 클럽 멤버십을 찾을 수 없습니다.")
        conn.commit()
        return {"include_my_distance": bool(row[0])}
    except HTTPException:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


@router.put("/clubs/{club_id}/campaign")
def upsert_club_campaign(club_id: int, body: ClubCampaignRequest, request: Request):
    customer_id = _customer_id(request)
    if body.end_date < body.start_date:
        raise HTTPException(400, "종료일은 시작일보다 빠를 수 없습니다.")
    if (body.end_date - body.start_date).days > 365:
        raise HTTPException(400, "캠페인 기간은 최대 365일까지 설정할 수 있습니다.")

    headline = body.headline.strip()
    conn = _get_db()
    cur = conn.cursor()
    try:
        _club_role(cur, club_id, customer_id, {"owner", "coach"})
        if body.class_id:
            cur.execute(
                "SELECT 1 FROM swim_classes WHERE id = %s AND club_id = %s AND status = 'active'",
                (body.class_id, club_id),
            )
            if not cur.fetchone():
                raise HTTPException(400, "이 클럽의 운영 중인 반만 공개할 수 있습니다.")

        cur.execute("SELECT public_token FROM club_promotion_campaigns WHERE club_id = %s", (club_id,))
        row = cur.fetchone()
        public_token = row[0] if row else _new_token()
        cur.execute(
            """
            INSERT INTO club_promotion_campaigns
                (club_id, class_id, public_token, headline, target_distance,
                 start_date, end_date, is_public, show_member_count)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (club_id) DO UPDATE SET
                class_id = EXCLUDED.class_id,
                headline = EXCLUDED.headline,
                target_distance = EXCLUDED.target_distance,
                start_date = EXCLUDED.start_date,
                end_date = EXCLUDED.end_date,
                is_public = EXCLUDED.is_public,
                show_member_count = EXCLUDED.show_member_count,
                updated_at = NOW()
            """,
            (
                club_id, body.class_id, public_token, headline, body.target_distance,
                body.start_date, body.end_date, body.is_public, body.show_member_count,
            ),
        )
        conn.commit()
        return {"campaign": _campaign_payload(cur, club_id)}
    except HTTPException:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        raise HTTPException(500, f"클럽 홍보 페이지 저장 오류: {exc}")
    finally:
        cur.close()
        conn.close()


@router.delete("/clubs/{club_id}/campaign")
def disable_club_campaign(club_id: int, request: Request):
    customer_id = _customer_id(request)
    conn = _get_db()
    cur = conn.cursor()
    try:
        _club_role(cur, club_id, customer_id, {"owner", "coach"})
        cur.execute(
            "UPDATE club_promotion_campaigns SET is_public = FALSE, updated_at = NOW() WHERE club_id = %s",
            (club_id,),
        )
        conn.commit()
        return {"disabled": True}
    finally:
        cur.close()
        conn.close()


def _load_public_club(cur, token: str, *, count_view: bool = True) -> dict:
    cur.execute(
        """
        SELECT campaign.id, campaign.club_id, club.name, club.description,
               club.default_pool_length, campaign.headline, campaign.class_id,
               cls.name, cls.level, cls.goal, cls.pool_length,
               cls.invite_code, campaign.target_distance, campaign.start_date,
               campaign.end_date, campaign.show_member_count
        FROM club_promotion_campaigns campaign
        JOIN swim_clubs club ON club.id = campaign.club_id AND club.status = 'active'
        LEFT JOIN swim_classes cls ON cls.id = campaign.class_id AND cls.status = 'active'
        WHERE campaign.public_token = %s AND campaign.is_public IS TRUE
        """,
        (token,),
    )
    row = cur.fetchone()
    if not row:
        raise HTTPException(404, "공개 중인 클럽 페이지를 찾을 수 없습니다.")

    if row[6]:
        cur.execute(
            """
            SELECT COUNT(DISTINCT member.customer_id), COALESCE(SUM(log.total_distance), 0)
            FROM swim_class_members member
            LEFT JOIN swim_club_members club_member
              ON club_member.club_id = %s AND club_member.customer_id = member.customer_id
             AND club_member.status = 'active'
            LEFT JOIN training_logs log ON log.customer_id = member.customer_id
              AND log.log_date BETWEEN %s AND %s
             AND club_member.promotion_distance_opt_in IS TRUE
            WHERE member.class_id = %s AND member.status = 'active'
            """,
            (row[1], row[13], row[14], row[6]),
        )
    else:
        cur.execute(
            """
            SELECT COUNT(DISTINCT member.customer_id), COALESCE(SUM(log.total_distance), 0)
            FROM swim_club_members member
            LEFT JOIN training_logs log ON log.customer_id = member.customer_id
              AND log.log_date BETWEEN %s AND %s
             AND member.promotion_distance_opt_in IS TRUE
            WHERE member.club_id = %s AND member.status = 'active'
            """,
            (row[13], row[14], row[1]),
        )
    member_count, total_distance = cur.fetchone()
    if count_view:
        cur.execute(
            """
            UPDATE club_promotion_campaigns
            SET view_count = view_count + 1, last_viewed_at = NOW()
            WHERE id = %s
            """,
            (row[0],),
        )
    target = int(row[12] or 0)
    total = int(total_distance or 0)
    return {
        "club": {
            "name": row[2], "description": row[3], "default_pool_length": int(row[4]),
        },
        "campaign": {
            "headline": row[5], "target_distance": target,
            "total_distance": total,
            "progress_rate": round(total / target * 100) if target else 0,
            "start_date": _iso(row[13]), "end_date": _iso(row[14]),
            "member_count": int(member_count or 0) if row[15] else None,
        },
        "class": ({
            "name": row[7], "level": row[8], "goal": row[9],
            "pool_length": int(row[10]), "invite_code": row[11],
        } if row[6] and row[7] else None),
        "privacy": "직접 동의한 회원의 거리만 익명 합산하며 이름과 개인 훈련 상세는 공개하지 않습니다.",
    }


@router.get("/public/clubs/{token}")
@limiter.limit("60/minute")
def get_public_club_campaign(token: str, request: Request):
    conn = _get_db()
    cur = conn.cursor()
    try:
        payload = _load_public_club(cur, token)
        conn.commit()
        return payload
    except HTTPException:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


@router.get("/public/clubs/{token}/qr.svg")
@limiter.limit("60/minute")
def get_public_club_qr(token: str, request: Request):
    conn = _get_db()
    cur = conn.cursor()
    try:
        _load_public_club(cur, token, count_view=False)
        hostname = (request.url.hostname or "").lower()
        origin = (
            str(request.base_url).rstrip("/")
            if hostname in {"localhost", "127.0.0.1", "testserver"}
            else os.getenv("PUBLIC_APP_URL", "https://swimtech.vercel.app").rstrip("/")
        )
        target = f"{origin}/club/{token}"
        image = qrcode.make(target, image_factory=qrcode.image.svg.SvgPathImage, box_size=8, border=2)
        buffer = BytesIO()
        image.save(buffer)
        return Response(
            content=buffer.getvalue(),
            media_type="image/svg+xml",
            headers={"Cache-Control": "public, max-age=300"},
        )
    finally:
        cur.close()
        conn.close()
