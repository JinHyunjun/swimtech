# -*- coding: utf-8 -*-
import os
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from routers.auth import verify_token, decode_token
from db import DATABASE_URL, get_db as _get_db

router = APIRouter()

def _get_username(request: Request) -> str:
    token = request.cookies.get("swimtech_token")
    if not token:
        return "guest"
    return verify_token(token) or "guest"


class FromPlanRequest(BaseModel):
    plan_name: str
    log_date: Optional[str] = None
    notes: Optional[str] = None
    plan_data: Dict[str, Any] = Field(default_factory=dict)


class GoalRequest(BaseModel):
    year: int
    month: int
    goal_distance: int


class PlanCompletionRequest(BaseModel):
    """A preset-plan session that was saved as an actual training log."""
    plan_key: str
    week_index: int
    day_label: str


class TrainingSetRequest(BaseModel):
    """One planned set and the swimmer's actual execution of that set."""

    phase: str = "main"
    stroke_type: Optional[str] = None
    description: str
    target_reps: int = 1
    target_distance_m: int
    target_cycle_seconds: Optional[int] = None
    completed_reps: int = 0
    completed_distance_m: Optional[int] = None
    actual_cycle_seconds: Optional[int] = None
    rpe: Optional[int] = None
    status: str = "pending"
    notes: Optional[str] = None


class TrainingSetCollectionRequest(BaseModel):
    sets: List[TrainingSetRequest] = Field(default_factory=list)
    sync_total_distance: bool = True


_SET_PHASES = {"warmup", "drill", "main", "cooldown", "other"}
_SET_STATUSES = {"pending", "completed", "skipped", "modified"}


def _normalize_training_sets(items: Optional[List[TrainingSetRequest]]) -> List[dict]:
    if items is None:
        return []
    if len(items) > 100:
        raise HTTPException(400, "한 훈련에는 세트를 최대 100개까지 저장할 수 있습니다.")

    normalized = []
    for order, item in enumerate(items):
        phase = (item.phase or "main").strip().lower()
        status = (item.status or "pending").strip().lower()
        description = (item.description or "").strip()
        stroke_type = (item.stroke_type or "").strip() or None
        notes = (item.notes or "").strip() or None
        target_reps = int(item.target_reps or 0)
        target_distance = int(item.target_distance_m or 0)
        completed_reps = int(item.completed_reps or 0)
        completed_distance = (
            completed_reps * target_distance
            if item.completed_distance_m is None
            else int(item.completed_distance_m)
        )

        if phase not in _SET_PHASES:
            raise HTTPException(400, f"{order + 1}번째 세트의 구간 값이 올바르지 않습니다.")
        if status not in _SET_STATUSES:
            raise HTTPException(400, f"{order + 1}번째 세트의 상태 값이 올바르지 않습니다.")
        if not description or len(description) > 200:
            raise HTTPException(400, f"{order + 1}번째 세트 설명은 1~200자로 입력해주세요.")
        if stroke_type and len(stroke_type) > 20:
            raise HTTPException(400, f"{order + 1}번째 세트 영법이 너무 깁니다.")
        if not 1 <= target_reps <= 200:
            raise HTTPException(400, f"{order + 1}번째 세트 반복 횟수는 1~200이어야 합니다.")
        if not 1 <= target_distance <= 50000:
            raise HTTPException(400, f"{order + 1}번째 세트 거리는 1~50,000m여야 합니다.")
        if not 0 <= completed_reps <= 300:
            raise HTTPException(400, f"{order + 1}번째 완료 횟수는 0~300이어야 합니다.")
        if not 0 <= completed_distance <= 200000:
            raise HTTPException(400, f"{order + 1}번째 완료 거리는 0~200,000m여야 합니다.")
        if item.target_cycle_seconds is not None and not 1 <= int(item.target_cycle_seconds) <= 7200:
            raise HTTPException(400, f"{order + 1}번째 목표 사이클이 올바르지 않습니다.")
        if item.actual_cycle_seconds is not None and not 1 <= int(item.actual_cycle_seconds) <= 7200:
            raise HTTPException(400, f"{order + 1}번째 실제 사이클이 올바르지 않습니다.")
        if item.rpe is not None and not 1 <= int(item.rpe) <= 10:
            raise HTTPException(400, f"{order + 1}번째 체감 강도는 1~10이어야 합니다.")
        if notes and len(notes) > 500:
            raise HTTPException(400, f"{order + 1}번째 세트 메모는 500자 이하여야 합니다.")

        normalized.append({
            "set_order": order,
            "phase": phase,
            "stroke_type": stroke_type,
            "description": description,
            "target_reps": target_reps,
            "target_distance_m": target_distance,
            "target_cycle_seconds": int(item.target_cycle_seconds) if item.target_cycle_seconds is not None else None,
            "completed_reps": completed_reps,
            "completed_distance_m": completed_distance,
            "actual_cycle_seconds": int(item.actual_cycle_seconds) if item.actual_cycle_seconds is not None else None,
            "rpe": int(item.rpe) if item.rpe is not None else None,
            "status": status,
            "notes": notes,
        })
    return normalized


def _replace_training_sets(cur, customer_id: int, training_log_id: int, items: List[dict]) -> None:
    cur.execute("DELETE FROM training_log_sets WHERE training_log_id = %s", (training_log_id,))
    for item in items:
        cur.execute(
            """
            INSERT INTO training_log_sets (
                training_log_id, customer_id, set_order, phase, stroke_type, description,
                target_reps, target_distance_m, target_cycle_seconds,
                completed_reps, completed_distance_m, actual_cycle_seconds,
                rpe, status, notes
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                training_log_id, customer_id, item["set_order"], item["phase"],
                item["stroke_type"], item["description"], item["target_reps"],
                item["target_distance_m"], item["target_cycle_seconds"],
                item["completed_reps"], item["completed_distance_m"],
                item["actual_cycle_seconds"], item["rpe"], item["status"], item["notes"],
            ),
        )


def _fetch_training_sets(cur, training_log_ids: List[int]) -> Dict[int, List[dict]]:
    if not training_log_ids:
        return {}
    cur.execute(
        """
        SELECT id, training_log_id, set_order, phase, stroke_type, description,
               target_reps, target_distance_m, target_cycle_seconds,
               completed_reps, completed_distance_m, actual_cycle_seconds,
               rpe, status, notes
        FROM training_log_sets
        WHERE training_log_id = ANY(%s)
        ORDER BY training_log_id, set_order
        """,
        (training_log_ids,),
    )
    result: Dict[int, List[dict]] = {}
    for row in cur.fetchall():
        item = {
            "id": row[0],
            "set_order": row[2],
            "phase": row[3],
            "stroke_type": row[4],
            "description": row[5],
            "target_reps": row[6],
            "target_distance_m": row[7],
            "planned_distance_m": int(row[6] or 0) * int(row[7] or 0),
            "target_cycle_seconds": row[8],
            "completed_reps": row[9],
            "completed_distance_m": row[10],
            "actual_cycle_seconds": row[11],
            "rpe": row[12],
            "status": row[13],
            "notes": row[14],
        }
        result.setdefault(row[1], []).append(item)
    return result


def _set_summary(items: List[dict]) -> dict:
    planned = sum(int(item.get("planned_distance_m") or item["target_reps"] * item["target_distance_m"]) for item in items)
    completed = sum(int(item.get("completed_distance_m") or 0) for item in items)
    completed_sets = sum(1 for item in items if item.get("status") == "completed")
    return {
        "set_count": len(items),
        "completed_sets": completed_sets,
        "planned_distance_m": planned,
        "completed_distance_m": completed,
        "completion_rate": round(completed / planned * 100) if planned else 0,
    }


def _get_customer_id(request: Request) -> Optional[int]:
    token = request.cookies.get("swimtech_token")
    if not token:
        return None
    payload = decode_token(token)
    return payload.get("customer_id")


def _ensure_log_columns():
    """기존에 배포된 training_logs 테이블에 used_fins 컬럼이 없을 수 있어 추가 보장."""
    conn = _get_db()
    cur = conn.cursor()
    cur.execute("ALTER TABLE training_logs ADD COLUMN IF NOT EXISTS used_fins BOOLEAN DEFAULT FALSE")
    conn.commit()
    cur.close()
    conn.close()


def _ensure_goals_table():
    conn = _get_db()
    cur = conn.cursor()
    # 구버전(username 컬럼) 테이블이 있으면 삭제 후 재생성
    cur.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name='training_goals' AND column_name='username'
    """)
    if cur.fetchone():
        cur.execute("DROP TABLE IF EXISTS training_goals")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS training_goals (
            id            SERIAL PRIMARY KEY,
            customer_id   INTEGER NOT NULL,
            year          INTEGER NOT NULL,
            month         INTEGER NOT NULL,
            goal_distance INTEGER NOT NULL DEFAULT 0,
            created_at    TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE (customer_id, year, month)
        )
    """)
    conn.commit()
    cur.close()
    conn.close()


class LogRequest(BaseModel):
    log_date:         str
    stroke_type:      str = "자유형"
    pool_length:      int = 25
    total_distance:   int
    duration_minutes: int = 0
    intensity:        str = "보통"
    mood:             Optional[str] = None
    memo:             Optional[str] = None
    used_fins:        bool = False
    plan_completion:  Optional[PlanCompletionRequest] = None
    sets:              Optional[List[TrainingSetRequest]] = None


@router.post("")
def create_log(req: LogRequest, request: Request):
    cid = _get_customer_id(request)
    if not cid:
        raise HTTPException(401, "로그인이 필요합니다")
    try:
        ld = date.fromisoformat(req.log_date)
    except Exception:
        raise HTTPException(400, "날짜 형식 오류 (YYYY-MM-DD)")
    dist = int(req.total_distance or 0)
    if dist <= 0:
        raise HTTPException(400, "거리를 입력하세요")
    training_sets = _normalize_training_sets(req.sets)
    memo = (req.memo or "").strip() or None
    conn = _get_db()
    cur = conn.cursor()
    try:
        _ensure_log_columns()
        cur.execute("""INSERT INTO training_logs
            (customer_id, log_date, stroke_type, total_distance, duration_minutes, pool_length, intensity, memo, mood, used_fins)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
            (cid, ld, req.stroke_type, dist, int(req.duration_minutes or 0),
             int(req.pool_length or 25), req.intensity, memo, req.mood, req.used_fins))
        nid = cur.fetchone()[0]
        if req.sets is not None:
            _replace_training_sets(cur, cid, nid, training_sets)

        # A plan session is complete only after its training log has been saved.
        # Keeping this relation in the DB makes it consistent across devices.
        if req.plan_completion:
            completion = req.plan_completion
            plan_key = completion.plan_key.strip()
            day_label = completion.day_label.strip()
            if not plan_key or len(plan_key) > 50 or not day_label or len(day_label) > 20:
                raise HTTPException(400, "플랜 완료 정보가 올바르지 않습니다.")
            if completion.week_index < 0 or completion.week_index > 51:
                raise HTTPException(400, "플랜 주차 정보가 올바르지 않습니다.")
            cur.execute(
                """
                INSERT INTO plan_completions
                    (customer_id, plan_key, week_index, day_label, training_log_id)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (customer_id, plan_key, week_index, day_label)
                DO UPDATE SET training_log_id = EXCLUDED.training_log_id,
                              completed_at = NOW()
                """,
                (cid, plan_key, completion.week_index, day_label, nid),
            )
        conn.commit()
        return {
            "id": nid,
            "status": "created",
            "plan_completed": bool(req.plan_completion),
            "set_summary": _set_summary(training_sets),
        }
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(500, f"저장 오류: {e}")
    finally:
        cur.close(); conn.close()


@router.get("/plan-completions")
def get_plan_completions(request: Request):
    """Return preset-plan sessions completed through a saved training log."""
    cid = _get_customer_id(request)
    if not cid:
        return {"completions": []}
    conn = _get_db()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT plan_key, week_index, day_label, training_log_id, completed_at
            FROM plan_completions
            WHERE customer_id = %s
            ORDER BY completed_at DESC
            """,
            (cid,),
        )
        return {"completions": [
            {
                "plan_key": row[0],
                "week_index": row[1],
                "day_label": row[2],
                "training_log_id": row[3],
                "completed_at": str(row[4]),
            }
            for row in cur.fetchall()
        ]}
    except Exception as e:
        raise HTTPException(500, f"플랜 완료 기록 조회 오류: {e}")
    finally:
        cur.close()
        conn.close()


@router.get("/{log_id}/sets")
def get_log_sets(log_id: int, request: Request):
    """Return the ordered set execution data for one owned training log."""
    cid = _get_customer_id(request)
    if not cid:
        raise HTTPException(401, "로그인이 필요합니다.")
    conn = _get_db()
    cur = conn.cursor()
    try:
        cur.execute("SELECT customer_id FROM training_logs WHERE id = %s", (log_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "훈련 기록을 찾을 수 없습니다.")
        if row[0] != cid:
            raise HTTPException(403, "이 훈련 기록을 볼 권한이 없습니다.")
        items = _fetch_training_sets(cur, [log_id]).get(log_id, [])
        return {"training_log_id": log_id, "sets": items, "summary": _set_summary(items)}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, f"세트 기록 조회 오류: {exc}")
    finally:
        cur.close()
        conn.close()


@router.put("/{log_id}/sets")
def replace_log_sets(log_id: int, req: TrainingSetCollectionRequest, request: Request):
    """Replace a log's set results atomically and optionally sync its total distance."""
    cid = _get_customer_id(request)
    if not cid:
        raise HTTPException(401, "로그인이 필요합니다.")
    items = _normalize_training_sets(req.sets)
    conn = _get_db()
    cur = conn.cursor()
    try:
        cur.execute("SELECT customer_id FROM training_logs WHERE id = %s FOR UPDATE", (log_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "훈련 기록을 찾을 수 없습니다.")
        if row[0] != cid:
            raise HTTPException(403, "이 훈련 기록을 수정할 권한이 없습니다.")
        _replace_training_sets(cur, cid, log_id, items)
        summary = _set_summary(items)
        if req.sync_total_distance and summary["completed_distance_m"] > 0:
            cur.execute(
                "UPDATE training_logs SET total_distance = %s, updated_at = NOW() WHERE id = %s",
                (summary["completed_distance_m"], log_id),
            )
        conn.commit()
        return {"status": "updated", "training_log_id": log_id, "summary": summary}
    except HTTPException:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        raise HTTPException(500, f"세트 기록 수정 오류: {exc}")
    finally:
        cur.close()
        conn.close()


@router.put("/{log_id}")
def update_log(log_id: int, req: LogRequest, request: Request):
    cid = _get_customer_id(request)
    if not cid:
        raise HTTPException(401, "로그인이 필요합니다")
    try:
        ld = date.fromisoformat(req.log_date)
    except Exception:
        raise HTTPException(400, "날짜 형식 오류 (YYYY-MM-DD)")
    dist = int(req.total_distance or 0)
    if dist <= 0:
        raise HTTPException(400, "거리를 입력하세요")
    training_sets = _normalize_training_sets(req.sets)
    memo = (req.memo or "").strip() or None
    conn = _get_db()
    cur = conn.cursor()
    try:
        _ensure_log_columns()
        cur.execute("SELECT customer_id FROM training_logs WHERE id = %s", (log_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "기록을 찾을 수 없습니다")
        if row[0] != cid:
            raise HTTPException(403, "권한이 없습니다")
        cur.execute("""UPDATE training_logs SET
            log_date=%s, stroke_type=%s, total_distance=%s, duration_minutes=%s,
            pool_length=%s, intensity=%s, memo=%s, mood=%s, used_fins=%s, updated_at=NOW()
            WHERE id=%s""",
            (ld, req.stroke_type, dist, int(req.duration_minutes or 0),
             int(req.pool_length or 25), req.intensity, memo, req.mood, req.used_fins, log_id))
        if req.sets is not None:
            _replace_training_sets(cur, cid, log_id, training_sets)
        conn.commit()
        return {
            "status": "updated",
            "set_summary": _set_summary(training_sets) if req.sets is not None else None,
        }
    except HTTPException:
        conn.rollback(); raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(500, f"수정 오류: {e}")
    finally:
        cur.close(); conn.close()


@router.delete("/{log_id}")
def delete_log(log_id: int, request: Request):
    cid = _get_customer_id(request)
    if not cid:
        raise HTTPException(401, "로그인이 필요합니다")
    conn = _get_db()
    cur = conn.cursor()
    try:
        cur.execute("SELECT customer_id FROM training_logs WHERE id = %s", (log_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "기록을 찾을 수 없습니다")
        if row[0] != cid:
            raise HTTPException(403, "권한이 없습니다")
        # A completion represents this saved log; deleting the log should not
        # leave a completed-looking plan session behind.
        cur.execute("DELETE FROM plan_completions WHERE training_log_id = %s", (log_id,))
        cur.execute("DELETE FROM training_logs WHERE id = %s", (log_id,))
        conn.commit()
        return {"status": "deleted"}
    except HTTPException:
        conn.rollback(); raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(500, f"삭제 오류: {e}")
    finally:
        cur.close(); conn.close()


@router.get("/stats")
def get_stats(request: Request, year: int, month: int):
    cid = _get_customer_id(request)
    if not cid:
        return {"count": 0, "total_distance": 0, "avg_distance": 0}
    conn = _get_db()
    cur = conn.cursor()
    try:
        cur.execute("""SELECT COUNT(*), COALESCE(SUM(total_distance),0), COALESCE(AVG(total_distance),0)
            FROM training_logs WHERE customer_id=%s
              AND EXTRACT(YEAR FROM log_date)=%s AND EXTRACT(MONTH FROM log_date)=%s""",
            (cid, year, month))
        r = cur.fetchone()
        cur.close()
        return {"count": int(r[0] or 0), "total_distance": int(r[1] or 0), "avg_distance": round(float(r[2] or 0))}
    except Exception as e:
        raise HTTPException(500, f"통계 오류: {e}")
    finally:
        conn.close()


@router.get("/streak")
def get_streak(request: Request):
    cid = _get_customer_id(request)
    if not cid:
        return {"streak": 0}
    conn = _get_db()
    cur = conn.cursor()
    try:
        cur.execute("SELECT DISTINCT log_date FROM training_logs WHERE customer_id=%s", (cid,))
        dates = set(r[0] for r in cur.fetchall())
        cur.close()
        if not dates:
            return {"streak": 0}
        today = date.today()
        cursor_day = today if today in dates else today - timedelta(days=1)
        if cursor_day not in dates:
            return {"streak": 0}
        streak = 0
        while cursor_day in dates:
            streak += 1
            cursor_day = cursor_day - timedelta(days=1)
        return {"streak": streak}
    except Exception as e:
        raise HTTPException(500, f"연속출석 오류: {e}")
    finally:
        conn.close()

@router.post("/from-plan")
def create_log_from_plan(req: FromPlanRequest, request: Request):
    username = _get_username(request)
    cid = _get_customer_id(request)
    if not cid:
        raise HTTPException(401, "로그인이 필요합니다")
    log_date = req.log_date or str(date.today())
    try:
        parsed_date = date.fromisoformat(log_date)
    except ValueError:
        raise HTTPException(400, "날짜 형식은 YYYY-MM-DD여야 합니다.")
    pd = req.plan_data or {}
    raw_sets = pd.get("sets") or []
    try:
        set_requests = [TrainingSetRequest(**item) for item in raw_sets]
    except Exception as exc:
        raise HTTPException(400, f"플랜 세트 형식이 올바르지 않습니다: {exc}")
    training_sets = _normalize_training_sets(set_requests)
    dist = int(pd.get("total_distance") or pd.get("distance") or 0)
    if dist <= 0:
        raise HTTPException(400, "훈련 거리는 1m 이상이어야 합니다.")
    stroke = pd.get("stroke_type") or pd.get("stroke") or "자유형"
    duration = int(pd.get("duration_minutes") or pd.get("duration") or 0)
    pool_length = int(pd.get("pool_length") or 25)
    intensity = pd.get("intensity") or "보통"
    memo = (str(req.plan_name or "") + ((" - " + req.notes) if req.notes else "")).strip() or None

    conn = _get_db()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            INSERT INTO training_logs (customer_id, log_date, stroke_type, total_distance, duration_minutes, pool_length, intensity, memo)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, created_at
            """,
            (cid, parsed_date, stroke, dist, duration, pool_length, intensity, memo),
        )
        row = cur.fetchone()
        if raw_sets:
            _replace_training_sets(cur, cid, row[0], training_sets)
        conn.commit()
    except Exception as exc:
        conn.rollback()
        raise HTTPException(500, f"DB 저장 오류: {exc}")
    finally:
        cur.close()
        conn.close()

    # 참여 중인 챌린지에 거리 자동 반영
    try:
        from routers.challenge import update_challenge_progress
        update_challenge_progress(username, dist)
    except Exception:
        pass

    # 훈련 일지 뱃지 자동 체크
    try:
        from routers.badge import check_badges_on_log
        check_badges_on_log(username)
    except Exception:
        pass

    return {
        "id": row[0],
        "plan_name": req.plan_name,
        "log_date": log_date,
        "created_at": str(row[1]),
        "set_summary": _set_summary(training_sets),
    }


@router.post("/goal")
def set_goal(req: GoalRequest, request: Request):
    customer_id = _get_customer_id(request)
    if not customer_id:
        raise HTTPException(401, "로그인이 필요합니다.")
    try:
        _ensure_goals_table()
        conn = _get_db()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO training_goals (customer_id, year, month, goal_distance)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (customer_id, year, month)
            DO UPDATE SET goal_distance = EXCLUDED.goal_distance, created_at = NOW()
            RETURNING id
        """, (customer_id, req.year, req.month, req.goal_distance))
        row = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()
        return {"id": row[0], "goal_distance": req.goal_distance}
    except Exception as e:
        raise HTTPException(500, f"DB 오류: {e}")


@router.get("/goal")
def get_goal(year: int, month: int, request: Request):
    customer_id = _get_customer_id(request)
    if not customer_id:
        return {"goal_distance": 0, "achieved_distance": 0}
    try:
        _ensure_goals_table()
        conn = _get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT goal_distance FROM training_goals
            WHERE customer_id = %s AND year = %s AND month = %s
        """, (customer_id, year, month))
        row = cur.fetchone()
        goal = row[0] if row else 0
        cur.execute("""
            SELECT COALESCE(SUM(total_distance), 0) FROM training_logs
            WHERE customer_id = %s
              AND EXTRACT(YEAR FROM log_date) = %s
              AND EXTRACT(MONTH FROM log_date) = %s
        """, (customer_id, year, month))
        achieved = int(cur.fetchone()[0])
        cur.close()
        conn.close()
        return {"goal_distance": goal, "achieved_distance": achieved}
    except Exception as e:
        raise HTTPException(500, f"DB 오류: {e}")


@router.get("/recent")
def get_most_recent_log(request: Request):
    """빠른 기록 작성에 사용할 가장 최근 훈련 기록을 반환한다."""
    cid = _get_customer_id(request)
    if not cid:
        raise HTTPException(401, "로그인이 필요합니다")
    conn = _get_db()
    cur = conn.cursor()
    try:
        _ensure_log_columns()
        cur.execute(
            """SELECT id, log_date, stroke_type, total_distance, duration_minutes,
                      pool_length, intensity, mood, memo, created_at, used_fins
                 FROM training_logs
                WHERE customer_id = %s
                ORDER BY log_date DESC, created_at DESC
                LIMIT 1""",
            (cid,),
        )
        row = cur.fetchone()
        if not row:
            return {"log": None}
        sets = _fetch_training_sets(cur, [row[0]]).get(row[0], [])
        return {"log": {
            "id": row[0],
            "log_date": str(row[1]),
            "stroke_type": row[2],
            "total_distance": row[3],
            "duration_minutes": row[4],
            "pool_length": row[5],
            "intensity": row[6],
            "mood": row[7],
            "memo": row[8],
            "created_at": str(row[9]),
            "used_fins": row[10],
            "sets": sets,
            "set_summary": _set_summary(sets),
        }}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"최근 기록 조회 오류: {e}")
    finally:
        cur.close()
        conn.close()


@router.get("")
def list_logs(request: Request, year: Optional[int] = None, month: Optional[int] = None):
    cid = _get_customer_id(request)
    if not cid:
        return {"logs": []}
    conn = _get_db()
    cur = conn.cursor()
    try:
        _ensure_log_columns()
        if year and month:
            cur.execute("""SELECT id, log_date, stroke_type, total_distance, duration_minutes,
                       pool_length, intensity, mood, memo, created_at, used_fins
                FROM training_logs WHERE customer_id=%s
                  AND EXTRACT(YEAR FROM log_date)=%s AND EXTRACT(MONTH FROM log_date)=%s
                ORDER BY log_date DESC, created_at DESC""",
                (cid, year, month))
        else:
            cur.execute("""SELECT id, log_date, stroke_type, total_distance, duration_minutes,
                       pool_length, intensity, mood, memo, created_at, used_fins
                FROM training_logs WHERE customer_id=%s
                ORDER BY log_date DESC, created_at DESC LIMIT 100""",
                (cid,))
        rows = cur.fetchall()
        sets_by_log = _fetch_training_sets(cur, [row[0] for row in rows])
        cur.close(); conn.close()
        return {"logs": [
            {
                "id": r[0],
                "log_date": str(r[1]),
                "stroke_type": r[2],
                "total_distance": r[3],
                "duration_minutes": r[4],
                "pool_length": r[5],
                "intensity": r[6],
                "mood": r[7],
                "memo": r[8],
                "created_at": str(r[9]),
                "used_fins": r[10],
                "sets": sets_by_log.get(r[0], []),
                "set_summary": _set_summary(sets_by_log.get(r[0], [])),
            }
            for r in rows
        ]}
    except Exception as e:
        raise HTTPException(500, f"DB 오류: {e}")
