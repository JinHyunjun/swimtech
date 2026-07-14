# -*- coding: utf-8 -*-
"""SwimMate — 공통 DB 유틸리티.

모든 라우터는 이 모듈에서 get_db() 또는 db_conn()을 가져다 쓴다.
개별 라우터에서 DATABASE_URL / _get_db() 를 직접 정의하지 않는다.
"""
import os
from contextlib import contextmanager

import psycopg2

DATABASE_URL: str = os.getenv("DATABASE_URL", "")


def get_db():
    """새 psycopg2 커넥션을 반환한다. 호출자가 close() 책임."""
    return psycopg2.connect(DATABASE_URL)


@contextmanager
def db_conn():
    """with db_conn() as (conn, cur): 패턴으로 사용.

    블록 정상 종료 시 commit, 예외 발생 시 rollback 후 re-raise.
    항상 커넥션을 닫는다.
    """
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    try:
        yield conn, cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()
