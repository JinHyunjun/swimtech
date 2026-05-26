"""
SwimTech — 커뮤니티 라우터
게시글/댓글 CRUD, 좋아요 토글
"""
import logging
import os
import re
from typing import Optional

import psycopg2
from fastapi import APIRouter, Cookie, HTTPException, Query
from pydantic import BaseModel

from routers.auth import decode_token

router = APIRouter()
logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "")
ADMIN_ID = os.getenv("ADMIN_ID", "admin")

VALID_CATEGORIES = {"자유", "질문", "훈련후기", "공지"}
_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _get_db():
    return psycopg2.connect(DATABASE_URL)


def _strip(text: str) -> str:
    return _HTML_TAG_RE.sub("", text).strip() if text else ""


def _require_login(token: Optional[str]) -> dict:
    if not token:
        raise HTTPException(401, "로그인이 필요합니다.")
    payload = decode_token(token)
    if not payload.get("sub"):
        raise HTTPException(401, "세션이 만료되었습니다. 다시 로그인해주세요.")
    return payload


# ── Pydantic 모델 ─────────────────────────────────────────────────────────────

class PostCreate(BaseModel):
    category: str
    title: str
    content: str


class PostUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    category: Optional[str] = None


class CommentCreate(BaseModel):
    content: str
    parent_id: Optional[int] = None


# ── 댓글 좋아요 토글 (/comments/ 경로는 /{post_id} 보다 먼저 정의) ──────────

@router.post("/comments/{comment_id}/like")
def toggle_comment_like(
    comment_id: int,
    swimtech_token: str = Cookie(default=None),
):
    payload = _require_login(swimtech_token)
    me_id = payload.get("customer_id")
    if not me_id:
        raise HTTPException(403, "일반 계정으로 로그인해주세요.")

    conn = _get_db()
    cur = conn.cursor()
    try:
        cur.execute("SELECT id FROM comments WHERE id = %s", (comment_id,))
        if not cur.fetchone():
            raise HTTPException(404, "댓글을 찾을 수 없습니다.")

        cur.execute(
            "SELECT 1 FROM comment_likes WHERE comment_id=%s AND customer_id=%s",
            (comment_id, me_id),
        )
        if cur.fetchone():
            cur.execute(
                "DELETE FROM comment_likes WHERE comment_id=%s AND customer_id=%s",
                (comment_id, me_id),
            )
            cur.execute(
                "UPDATE comments SET likes = GREATEST(0, likes-1) WHERE id=%s RETURNING likes",
                (comment_id,),
            )
            liked = False
        else:
            cur.execute(
                "INSERT INTO comment_likes (comment_id, customer_id) VALUES (%s,%s) ON CONFLICT DO NOTHING",
                (comment_id, me_id),
            )
            cur.execute(
                "UPDATE comments SET likes = likes+1 WHERE id=%s RETURNING likes",
                (comment_id,),
            )
            liked = True

        likes = cur.fetchone()[0]
        conn.commit()
        return {"liked": liked, "likes": likes}
    except HTTPException:
        raise
    except Exception:
        conn.rollback()
        logger.error("toggle_comment_like: DB error", exc_info=True)
        raise HTTPException(500, "내부 오류가 발생했습니다.")
    finally:
        cur.close(); conn.close()


# ── 댓글 삭제 (/{post_id} 보다 먼저 정의해야 라우팅 충돌 방지) ──────────────

@router.delete("/comments/{comment_id}")
def delete_comment(
    comment_id: int,
    swimtech_token: str = Cookie(default=None),
):
    payload = _require_login(swimtech_token)
    me_id = payload.get("customer_id")
    username = payload.get("sub")

    conn = _get_db()
    cur = conn.cursor()
    try:
        cur.execute("SELECT customer_id FROM comments WHERE id = %s", (comment_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "댓글을 찾을 수 없습니다.")
        if row[0] != me_id and username != ADMIN_ID:
            raise HTTPException(403, "삭제 권한이 없습니다.")
        cur.execute("DELETE FROM comments WHERE id = %s", (comment_id,))
        conn.commit()
        return {"status": "ok"}
    except HTTPException:
        raise
    except Exception:
        conn.rollback()
        logger.error("delete_comment: DB error", exc_info=True)
        raise HTTPException(500, "내부 오류가 발생했습니다.")
    finally:
        cur.close(); conn.close()


# ── 게시글 목록 ──────────────────────────────────────────────────────────────

@router.get("")
def list_posts(
    category: str = Query("전체"),
    page: int = Query(1, ge=1),
    search: str = Query(""),
):
    limit = 20
    offset = (page - 1) * limit

    conditions: list[str] = []
    params: list = []

    if category and category != "전체":
        conditions.append("p.category = %s")
        params.append(category)
    if search:
        conditions.append("(p.title ILIKE %s OR p.content ILIKE %s)")
        params.extend([f"%{search}%", f"%{search}%"])

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    conn = _get_db()
    cur = conn.cursor()
    try:
        cur.execute(f"SELECT COUNT(*) FROM posts p {where}", params)
        total = cur.fetchone()[0]

        cur.execute(
            f"""
            SELECT p.id, p.category, p.title,
                   COALESCE(c.nickname, c.username, '익명') AS author,
                   p.likes, p.views, p.created_at,
                   (SELECT COUNT(*) FROM comments cm WHERE cm.post_id = p.id) AS comment_count
            FROM posts p
            LEFT JOIN customers c ON c.id = p.customer_id
            {where}
            ORDER BY p.created_at DESC
            LIMIT %s OFFSET %s
            """,
            params + [limit, offset],
        )
        rows = cur.fetchall()
        posts = [
            {
                "id": r[0],
                "category": r[1],
                "title": r[2],
                "author": r[3],
                "likes": r[4],
                "views": r[5],
                "created_at": r[6].isoformat() if r[6] else None,
                "comment_count": r[7],
            }
            for r in rows
        ]
        return {"posts": posts, "total": total, "page": page, "limit": limit}
    except Exception:
        logger.error("list_posts: DB error", exc_info=True)
        raise HTTPException(500, "내부 오류가 발생했습니다.")
    finally:
        cur.close(); conn.close()


# ── 게시글 작성 ──────────────────────────────────────────────────────────────

@router.post("")
def create_post(
    body: PostCreate,
    swimtech_token: str = Cookie(default=None),
):
    payload = _require_login(swimtech_token)
    me_id = payload.get("customer_id")
    if not me_id:
        raise HTTPException(403, "일반 계정으로 로그인해주세요.")

    category = _strip(body.category)
    if category not in VALID_CATEGORIES:
        raise HTTPException(400, "올바르지 않은 카테고리입니다.")

    title = _strip(body.title)
    if not title or len(title) > 200:
        raise HTTPException(400, "제목은 1~200자여야 합니다.")

    content = _strip(body.content)
    if not content or len(content) > 10000:
        raise HTTPException(400, "내용은 1~10000자여야 합니다.")

    conn = _get_db()
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO posts (customer_id, category, title, content) VALUES (%s,%s,%s,%s) RETURNING id",
            (me_id, category, title, content),
        )
        post_id = cur.fetchone()[0]
        conn.commit()
        return {"status": "ok", "id": post_id}
    except Exception:
        conn.rollback()
        logger.error("create_post: DB error", exc_info=True)
        raise HTTPException(500, "내부 오류가 발생했습니다.")
    finally:
        cur.close(); conn.close()


# ── 게시글 상세 + 댓글 ───────────────────────────────────────────────────────

@router.get("/{post_id}")
def get_post(post_id: int, swimtech_token: str = Cookie(default=None)):
    conn = _get_db()
    cur = conn.cursor()
    try:
        cur.execute("UPDATE posts SET views = views + 1 WHERE id = %s", (post_id,))
        conn.commit()

        cur.execute(
            """
            SELECT p.id, p.category, p.title, p.content,
                   COALESCE(c.nickname, c.username, '익명') AS author,
                   p.customer_id, p.likes, p.views, p.created_at, p.updated_at
            FROM posts p
            LEFT JOIN customers c ON c.id = p.customer_id
            WHERE p.id = %s
            """,
            (post_id,),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "게시글을 찾을 수 없습니다.")

        payload = decode_token(swimtech_token) if swimtech_token else {}
        me_id = payload.get("customer_id")

        liked = False
        if me_id:
            cur.execute(
                "SELECT 1 FROM post_likes WHERE post_id = %s AND customer_id = %s",
                (post_id, me_id),
            )
            liked = cur.fetchone() is not None

        post = {
            "id": row[0], "category": row[1], "title": row[2], "content": row[3],
            "author": row[4], "customer_id": row[5], "likes": row[6], "views": row[7],
            "created_at": row[8].isoformat() if row[8] else None,
            "updated_at": row[9].isoformat() if row[9] else None,
            "liked": liked, "is_mine": me_id == row[5],
        }

        cur.execute(
            """
            SELECT cm.id, cm.parent_id, cm.content,
                   COALESCE(c.nickname, c.username, '익명') AS author,
                   cm.customer_id, cm.likes, cm.created_at
            FROM comments cm
            LEFT JOIN customers c ON c.id = cm.customer_id
            WHERE cm.post_id = %s
            ORDER BY cm.created_at ASC
            """,
            (post_id,),
        )
        comment_rows = cur.fetchall()

        liked_ids: set = set()
        if me_id and comment_rows:
            c_ids = [r[0] for r in comment_rows]
            placeholders = ",".join(["%s"] * len(c_ids))
            cur.execute(
                f"SELECT comment_id FROM comment_likes WHERE customer_id=%s AND comment_id IN ({placeholders})",
                [me_id] + c_ids,
            )
            liked_ids = {r[0] for r in cur.fetchall()}

        comments = [
            {
                "id": r[0], "parent_id": r[1], "content": r[2], "author": r[3],
                "customer_id": r[4], "likes": r[5],
                "created_at": r[6].isoformat() if r[6] else None,
                "liked": r[0] in liked_ids, "is_mine": me_id == r[4],
            }
            for r in comment_rows
        ]
        return {"post": post, "comments": comments}
    except HTTPException:
        raise
    except Exception:
        logger.error("get_post: DB error", exc_info=True)
        raise HTTPException(500, "내부 오류가 발생했습니다.")
    finally:
        cur.close(); conn.close()


# ── 게시글 수정 ──────────────────────────────────────────────────────────────

@router.put("/{post_id}")
def update_post(
    post_id: int,
    body: PostUpdate,
    swimtech_token: str = Cookie(default=None),
):
    payload = _require_login(swimtech_token)
    me_id = payload.get("customer_id")
    username = payload.get("sub")

    conn = _get_db()
    cur = conn.cursor()
    try:
        cur.execute("SELECT customer_id FROM posts WHERE id = %s", (post_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "게시글을 찾을 수 없습니다.")
        if row[0] != me_id and username != ADMIN_ID:
            raise HTTPException(403, "수정 권한이 없습니다.")

        updates: list[str] = []
        params: list = []
        if body.title is not None:
            title = _strip(body.title)
            if not title or len(title) > 200:
                raise HTTPException(400, "제목은 1~200자여야 합니다.")
            updates.append("title = %s"); params.append(title)
        if body.content is not None:
            content = _strip(body.content)
            if not content or len(content) > 10000:
                raise HTTPException(400, "내용은 1~10000자여야 합니다.")
            updates.append("content = %s"); params.append(content)
        if body.category is not None:
            cat = _strip(body.category)
            if cat not in VALID_CATEGORIES:
                raise HTTPException(400, "올바르지 않은 카테고리입니다.")
            updates.append("category = %s"); params.append(cat)

        if not updates:
            return {"status": "ok"}

        updates.append("updated_at = NOW()")
        cur.execute(
            f"UPDATE posts SET {', '.join(updates)} WHERE id = %s",
            params + [post_id],
        )
        conn.commit()
        return {"status": "ok"}
    except HTTPException:
        raise
    except Exception:
        conn.rollback()
        logger.error("update_post: DB error", exc_info=True)
        raise HTTPException(500, "내부 오류가 발생했습니다.")
    finally:
        cur.close(); conn.close()


# ── 게시글 삭제 ──────────────────────────────────────────────────────────────

@router.delete("/{post_id}")
def delete_post(
    post_id: int,
    swimtech_token: str = Cookie(default=None),
):
    payload = _require_login(swimtech_token)
    me_id = payload.get("customer_id")
    username = payload.get("sub")

    conn = _get_db()
    cur = conn.cursor()
    try:
        cur.execute("SELECT customer_id FROM posts WHERE id = %s", (post_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "게시글을 찾을 수 없습니다.")
        if row[0] != me_id and username != ADMIN_ID:
            raise HTTPException(403, "삭제 권한이 없습니다.")
        cur.execute("DELETE FROM posts WHERE id = %s", (post_id,))
        conn.commit()
        return {"status": "ok"}
    except HTTPException:
        raise
    except Exception:
        conn.rollback()
        logger.error("delete_post: DB error", exc_info=True)
        raise HTTPException(500, "내부 오류가 발생했습니다.")
    finally:
        cur.close(); conn.close()


# ── 게시글 좋아요 토글 ───────────────────────────────────────────────────────

@router.post("/{post_id}/like")
def toggle_post_like(
    post_id: int,
    swimtech_token: str = Cookie(default=None),
):
    payload = _require_login(swimtech_token)
    me_id = payload.get("customer_id")
    if not me_id:
        raise HTTPException(403, "일반 계정으로 로그인해주세요.")

    conn = _get_db()
    cur = conn.cursor()
    try:
        cur.execute("SELECT id FROM posts WHERE id = %s", (post_id,))
        if not cur.fetchone():
            raise HTTPException(404, "게시글을 찾을 수 없습니다.")

        cur.execute(
            "SELECT 1 FROM post_likes WHERE post_id=%s AND customer_id=%s",
            (post_id, me_id),
        )
        if cur.fetchone():
            cur.execute(
                "DELETE FROM post_likes WHERE post_id=%s AND customer_id=%s",
                (post_id, me_id),
            )
            cur.execute(
                "UPDATE posts SET likes = GREATEST(0, likes-1) WHERE id=%s RETURNING likes",
                (post_id,),
            )
            liked = False
        else:
            cur.execute(
                "INSERT INTO post_likes (post_id, customer_id) VALUES (%s,%s) ON CONFLICT DO NOTHING",
                (post_id, me_id),
            )
            cur.execute(
                "UPDATE posts SET likes = likes+1 WHERE id=%s RETURNING likes",
                (post_id,),
            )
            liked = True

        likes = cur.fetchone()[0]
        conn.commit()
        return {"liked": liked, "likes": likes}
    except HTTPException:
        raise
    except Exception:
        conn.rollback()
        logger.error("toggle_post_like: DB error", exc_info=True)
        raise HTTPException(500, "내부 오류가 발생했습니다.")
    finally:
        cur.close(); conn.close()


# ── 댓글 작성 ────────────────────────────────────────────────────────────────

@router.post("/{post_id}/comments")
def create_comment(
    post_id: int,
    body: CommentCreate,
    swimtech_token: str = Cookie(default=None),
):
    payload = _require_login(swimtech_token)
    me_id = payload.get("customer_id")
    if not me_id:
        raise HTTPException(403, "일반 계정으로 로그인해주세요.")

    content = _strip(body.content)
    if not content or len(content) > 2000:
        raise HTTPException(400, "댓글은 1~2000자여야 합니다.")

    conn = _get_db()
    cur = conn.cursor()
    try:
        cur.execute("SELECT id FROM posts WHERE id = %s", (post_id,))
        if not cur.fetchone():
            raise HTTPException(404, "게시글을 찾을 수 없습니다.")

        if body.parent_id is not None:
            cur.execute(
                "SELECT id FROM comments WHERE id=%s AND post_id=%s",
                (body.parent_id, post_id),
            )
            if not cur.fetchone():
                raise HTTPException(400, "부모 댓글을 찾을 수 없습니다.")

        cur.execute(
            "INSERT INTO comments (post_id, customer_id, parent_id, content) VALUES (%s,%s,%s,%s) RETURNING id",
            (post_id, me_id, body.parent_id, content),
        )
        comment_id = cur.fetchone()[0]
        conn.commit()
        return {"status": "ok", "id": comment_id}
    except HTTPException:
        raise
    except Exception:
        conn.rollback()
        logger.error("create_comment: DB error", exc_info=True)
        raise HTTPException(500, "내부 오류가 발생했습니다.")
    finally:
        cur.close(); conn.close()
