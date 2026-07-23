# -*- coding: utf-8 -*-
"""Timed test sets and course-specific personal best history."""

from datetime import date
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from db import get_db as _get_db
from routers.clubs import _customer_id


router = APIRouter()
_STROKES = {"자유형", "배영", "평영", "접영", "혼영"}


class TestResultCreateRequest(BaseModel):
    test_date: date
    stroke_type: str = Field(..., min_length=2, max_length=20)
    distance_m: int = Field(..., ge=25, le=5000)
    pool_length: Literal[25, 50]
    duration_ms: int = Field(..., ge=1000, le=86400000)
    training_log_id: Optional[int] = None
    notes: Optional[str] = Field(default=None, max_length=300)


def _validate_result(body: TestResultCreateRequest) -> tuple[str, Optional[str]]:
    stroke = body.stroke_type.strip()
    notes = (body.notes or "").strip() or None
    if stroke not in _STROKES:
        raise HTTPException(400, "테스트 영법은 자유형·배영·평영·접영·혼영 중에서 선택해주세요.")
    if body.distance_m % body.pool_length:
        raise HTTPException(400, "테스트 거리는 선택한 풀 길이의 배수여야 합니다.")
    return stroke, notes


def _result_payload(row) -> dict:
    previous_best = int(row[11]) if row[11] is not None else None
    duration_ms = int(row[6])
    is_pb = previous_best is None or duration_ms < previous_best
    return {
        "id": int(row[0]),
        "training_log_id": int(row[1]) if row[1] is not None else None,
        "test_date": row[2].isoformat(),
        "stroke_type": row[3],
        "distance_m": int(row[4]),
        "pool_length": int(row[5]),
        "duration_ms": duration_ms,
        "source": row[7],
        "notes": row[8],
        "created_at": row[9].isoformat() if row[9] else None,
        "previous_best_ms": previous_best,
        "is_personal_best": is_pb,
        "improvement_ms": previous_best - duration_ms if is_pb and previous_best is not None else 0,
    }


@router.post("")
def create_test_result(body: TestResultCreateRequest, request: Request):
    customer_id = _customer_id(request)
    stroke, notes = _validate_result(body)
    conn = _get_db()
    cur = conn.cursor()
    try:
        if body.training_log_id is not None:
            cur.execute(
                "SELECT log_date, pool_length FROM training_logs WHERE id = %s AND customer_id = %s",
                (body.training_log_id, customer_id),
            )
            log_row = cur.fetchone()
            if not log_row:
                raise HTTPException(404, "연결할 훈련 일지를 찾을 수 없습니다.")
            if log_row[0] != body.test_date or int(log_row[1] or 25) != body.pool_length:
                raise HTTPException(400, "테스트 날짜와 풀 길이는 연결한 훈련 일지와 같아야 합니다.")

        cur.execute(
            "SELECT pg_advisory_xact_lock(%s, hashtext(%s))",
            (customer_id, f"{body.pool_length}:{stroke}:{body.distance_m}"),
        )
        cur.execute(
            """
            SELECT MIN(duration_ms) FROM swim_test_results
            WHERE customer_id = %s AND stroke_type = %s AND distance_m = %s AND pool_length = %s
            """,
            (customer_id, stroke, body.distance_m, body.pool_length),
        )
        previous_row = cur.fetchone()
        previous_best = int(previous_row[0]) if previous_row and previous_row[0] is not None else None
        cur.execute(
            """
            INSERT INTO swim_test_results
                (customer_id, training_log_id, test_date, stroke_type, distance_m,
                 pool_length, duration_ms, source, notes)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            RETURNING id, created_at
            """,
            (
                customer_id, body.training_log_id, body.test_date, stroke, body.distance_m,
                body.pool_length, body.duration_ms,
                "training_log" if body.training_log_id is not None else "manual", notes,
            ),
        )
        result_id, created_at = cur.fetchone()
        conn.commit()
        is_pb = previous_best is None or body.duration_ms < previous_best
        return {
            "id": int(result_id),
            "test_date": body.test_date.isoformat(),
            "stroke_type": stroke,
            "distance_m": body.distance_m,
            "pool_length": body.pool_length,
            "duration_ms": body.duration_ms,
            "training_log_id": body.training_log_id,
            "source": "training_log" if body.training_log_id is not None else "manual",
            "notes": notes,
            "created_at": created_at.isoformat() if created_at else None,
            "previous_best_ms": previous_best,
            "is_personal_best": is_pb,
            "improvement_ms": previous_best - body.duration_ms if is_pb and previous_best is not None else 0,
        }
    except HTTPException:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        raise HTTPException(500, f"테스트 기록 저장 오류: {exc}")
    finally:
        cur.close()
        conn.close()


@router.get("")
def list_test_results(
    request: Request,
    year: Optional[int] = Query(default=None, ge=2000, le=2100),
    month: Optional[int] = Query(default=None, ge=1, le=12),
    limit: int = Query(default=100, ge=1, le=300),
):
    customer_id = _customer_id(request)
    if month is not None and year is None:
        raise HTTPException(400, "월을 선택할 때는 연도도 함께 입력해주세요.")
    conn = _get_db()
    cur = conn.cursor()
    try:
        params = [customer_id]
        period_sql = ""
        if year is not None:
            period_sql += " AND EXTRACT(YEAR FROM test_date) = %s"
            params.append(year)
        if month is not None:
            period_sql += " AND EXTRACT(MONTH FROM test_date) = %s"
            params.append(month)
        params.append(limit)
        cur.execute(
            f"""
            WITH history AS (
                SELECT id, training_log_id, test_date, stroke_type, distance_m, pool_length,
                       duration_ms, source, notes, created_at,
                       MIN(duration_ms) OVER (
                           PARTITION BY stroke_type, distance_m, pool_length
                           ORDER BY test_date, id ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
                       ) AS previous_best_ms
                FROM swim_test_results
                WHERE customer_id = %s
            )
            SELECT id, training_log_id, test_date, stroke_type, distance_m, pool_length,
                   duration_ms, source, notes, created_at, NULL, previous_best_ms
            FROM history
            WHERE TRUE {period_sql}
            ORDER BY test_date DESC, id DESC
            LIMIT %s
            """,
            tuple(params),
        )
        results = [_result_payload(row) for row in cur.fetchall()]
        cur.execute(
            """
            SELECT DISTINCT ON (stroke_type, distance_m, pool_length)
                   id, training_log_id, test_date, stroke_type, distance_m, pool_length,
                   duration_ms, source, notes, created_at, NULL, NULL
            FROM swim_test_results
            WHERE customer_id = %s
            ORDER BY stroke_type, distance_m, pool_length, duration_ms, test_date, id
            """,
            (customer_id,),
        )
        bests = []
        for row in cur.fetchall():
            item = _result_payload(row)
            item["is_personal_best"] = True
            bests.append(item)
        count_params = [customer_id]
        if year is not None:
            count_params.append(year)
        if month is not None:
            count_params.append(month)
        cur.execute(
            f"""
            WITH history AS (
                SELECT test_date, duration_ms,
                       MIN(duration_ms) OVER (
                           PARTITION BY stroke_type, distance_m, pool_length
                           ORDER BY test_date, id ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
                       ) AS previous_best_ms
                FROM swim_test_results
                WHERE customer_id = %s
            )
            SELECT COUNT(*),
                   COUNT(*) FILTER (WHERE previous_best_ms IS NULL OR duration_ms < previous_best_ms)
            FROM history
            WHERE TRUE {period_sql}
            """,
            tuple(count_params),
        )
        summary_row = cur.fetchone() or (0, 0)
        return {
            "results": results,
            "bests": bests,
            "summary": {
                "attempts": int(summary_row[0] or 0),
                "personal_bests": int(summary_row[1] or 0),
                "events": len(bests),
            },
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, f"테스트 기록 조회 오류: {exc}")
    finally:
        cur.close()
        conn.close()


@router.delete("/{result_id}")
def delete_test_result(result_id: int, request: Request):
    customer_id = _customer_id(request)
    conn = _get_db()
    cur = conn.cursor()
    try:
        cur.execute(
            "DELETE FROM swim_test_results WHERE id = %s AND customer_id = %s RETURNING id",
            (result_id, customer_id),
        )
        if not cur.fetchone():
            raise HTTPException(404, "테스트 기록을 찾을 수 없습니다.")
        conn.commit()
        return {"status": "deleted", "id": result_id}
    except HTTPException:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        raise HTTPException(500, f"테스트 기록 삭제 오류: {exc}")
    finally:
        cur.close()
        conn.close()
