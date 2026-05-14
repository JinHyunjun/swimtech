import os
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
import psycopg2

router = APIRouter()

DATABASE_URL = os.getenv("DATABASE_URL", "")

def get_db():
    return psycopg2.connect(DATABASE_URL)


class CustomerCreate(BaseModel):
    name: str
    email: str
    phone: Optional[str] = None
    level: Optional[str] = "beginner"   # beginner / intermediate / advanced
    goal: Optional[str] = None


@router.get("/")
def list_customers():
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT id, name, email, phone, level, goal, created_at
            FROM customers ORDER BY id DESC
        """)
        rows = cur.fetchall()
        cur.close(); conn.close()
        return {"customers": [
            {"id": r[0], "name": r[1], "email": r[2],
             "phone": r[3], "level": r[4], "goal": r[5],
             "created_at": str(r[6])}
            for r in rows
        ]}
    except Exception as e:
        raise HTTPException(500, f"DB 오류: {e}")


@router.get("/{customer_id}")
def get_customer(customer_id: int):
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT id, name, email, phone, level, goal, sheets_url, created_at
            FROM customers WHERE id=%s
        """, (customer_id,))
        row = cur.fetchone()
        cur.close(); conn.close()
        if not row:
            raise HTTPException(404, "고객을 찾을 수 없습니다")
        return {"id": row[0], "name": row[1], "email": row[2],
                "phone": row[3], "level": row[4], "goal": row[5],
                "sheets_url": row[6], "created_at": str(row[7])}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"DB 오류: {e}")


@router.post("/")
def create_customer(body: CustomerCreate):
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO customers (name, email, phone, level, goal)
            VALUES (%s, %s, %s, %s, %s) RETURNING id
        """, (body.name, body.email, body.phone, body.level, body.goal))
        new_id = cur.fetchone()[0]
        conn.commit(); cur.close(); conn.close()
        return {"id": new_id, "message": f"고객 '{body.name}' 등록 완료"}
    except Exception as e:
        raise HTTPException(500, f"DB 오류: {e}")
