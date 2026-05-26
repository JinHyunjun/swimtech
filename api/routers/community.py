"""
SwimTech — 커뮤니티 라우터
게시글/댓글 CRUD, 좋아요/북마크/신고/태그/이미지/알림
"""
import io
import logging
import os
import re
import uuid
from typing import List, Optional

import psycopg2
from fastapi import APIRouter, Cookie, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from minio import Minio
from pydantic import BaseModel

from routers.auth import decode_token

router = APIRouter()
logger = logging.getLogger(__name__)

DATABASE_URL     = os.getenv("DATABASE_URL", "")
ADMIN_ID         = os.getenv("ADMIN_ID", "admin")
MINIO_ENDPOINT   = os.getenv("MINIO_ENDPOINT",  "minio:9000")
MINIO_ACCESS     = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET     = os.getenv("MINIO_SECRET_KEY", "minioadmin123")
COMMUNITY_BUCKET = "swim-community"

VALID_CATEGORIES  = {"자유", "질문", "훈련후기", "공지"}
VALID_SORT        = {"latest", "popular", "views"}
VALID_REASONS     = {"욕설", "스팸", "부적절한내용", "광고", "기타"}
ALLOWED_IMG_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_IMAGE_SIZE    = 5 * 1024 * 1024  # 5 MB
MAX_IMAGES        = 3
MAX_TAGS          = 10

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_MENTION_RE  = re.compile(r"@(\w+)")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_db():
    return psycopg2.connect(DATABASE_URL)


def init_db() -> None:
    if not DATABASE_URL:
        return
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS posts (
                id          SERIAL PRIMARY KEY,
                customer_id INTEGER REFERENCES customers(id) ON DELETE SET NULL,
                category    VARCHAR(20) NOT NULL DEFAULT '자유',
                title       VARCHAR(200) NOT NULL,
                content     TEXT NOT NULL,
                likes       INTEGER NOT NULL DEFAULT 0,
                views       INTEGER NOT NULL DEFAULT 0,
                is_hidden   BOOLEAN NOT NULL DEFAULT FALSE,
                created_at  TIMESTAMP DEFAULT NOW(),
                updated_at  TIMESTAMP DEFAULT NOW()
            );
            CREATE TABLE IF NOT EXISTS comments (
                id          SERIAL PRIMARY KEY,
                post_id     INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
                customer_id INTEGER REFERENCES customers(id) ON DELETE SET NULL,
                parent_id   INTEGER REFERENCES comments(id) ON DELETE CASCADE,
                content     TEXT NOT NULL,
                likes       INTEGER NOT NULL DEFAULT 0,
                created_at  TIMESTAMP DEFAULT NOW()
            );
            CREATE TABLE IF NOT EXISTS post_likes (
                post_id     INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
                customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
                PRIMARY KEY (post_id, customer_id)
            );
            CREATE TABLE IF NOT EXISTS comment_likes (
                comment_id  INTEGER NOT NULL REFERENCES comments(id) ON DELETE CASCADE,
                customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
                PRIMARY KEY (comment_id, customer_id)
            );
            CREATE TABLE IF NOT EXISTS reports (
                id          SERIAL PRIMARY KEY,
                reporter_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
                target_type VARCHAR(10) NOT NULL CHECK (target_type IN ('post','comment')),
                target_id   INTEGER NOT NULL,
                reason      VARCHAR(50) NOT NULL,
                created_at  TIMESTAMP DEFAULT NOW(),
                UNIQUE (reporter_id, target_type, target_id)
            );
            CREATE TABLE IF NOT EXISTS post_images (
                id         SERIAL PRIMARY KEY,
                post_id    INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
                minio_key  VARCHAR(500) NOT NULL,
                sort_order INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS notifications (
                id          SERIAL PRIMARY KEY,
                customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
                type        VARCHAR(30) NOT NULL,
                message     TEXT NOT NULL,
                target_id   INTEGER,
                is_read     BOOLEAN NOT NULL DEFAULT FALSE,
                created_at  TIMESTAMP DEFAULT NOW()
            );
            CREATE TABLE IF NOT EXISTS bookmarks (
                customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
                post_id     INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
                created_at  TIMESTAMP DEFAULT NOW(),
                PRIMARY KEY (customer_id, post_id)
            );
            CREATE TABLE IF NOT EXISTS post_tags (
                post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
                tag     VARCHAR(50) NOT NULL,
                PRIMARY KEY (post_id, tag)
            );
            ALTER TABLE posts ADD COLUMN IF NOT EXISTS is_hidden BOOLEAN NOT NULL DEFAULT FALSE;
            CREATE INDEX IF NOT EXISTS idx_posts_customer   ON posts(customer_id);
            CREATE INDEX IF NOT EXISTS idx_posts_category   ON posts(category);
            CREATE INDEX IF NOT EXISTS idx_posts_created    ON posts(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_comments_post    ON comments(post_id);
            CREATE INDEX IF NOT EXISTS idx_comments_parent  ON comments(parent_id);
            CREATE INDEX IF NOT EXISTS idx_reports_target   ON reports(target_type, target_id);
            CREATE INDEX IF NOT EXISTS idx_notifications_cid
                ON notifications(customer_id, is_read, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_bookmarks_cid    ON bookmarks(customer_id);
            CREATE INDEX IF NOT EXISTS idx_post_tags_tag    ON post_tags(tag);
            CREATE INDEX IF NOT EXISTS idx_post_images_post ON post_images(post_id);
        """)
        conn.commit()
        cur.close(); conn.close()
        logger.info("community 테이블 초기화 완료")
    except Exception:
        logger.warning("community init_db 실패", exc_info=True)


def _get_minio():
    return Minio(MINIO_ENDPOINT, access_key=MINIO_ACCESS, secret_key=MINIO_SECRET, secure=False)

def _strip(text: str) -> str:
    return _HTML_TAG_RE.sub("", text).strip() if text else ""

def _require_login(token: Optional[str]) -> dict:
    if not token:
        raise HTTPException(401, "로그인이 필요합니다.")
    payload = decode_token(token)
    if not payload.get("sub"):
        raise HTTPException(401, "세션이 만료되었습니다. 다시 로그인해주세요.")
    return payload

def _notify(cur, customer_id: int, ntype: str, message: str, target_id: Optional[int] = None):
    try:
        cur.execute(
            "INSERT INTO notifications (customer_id, type, message, target_id) VALUES (%s,%s,%s,%s)",
            (customer_id, ntype, message, target_id),
        )
    except Exception:
        logger.warning("_notify: 알림 생성 실패", exc_info=True)

def _ensure_community_bucket(minio: Minio):
    if not minio.bucket_exists(COMMUNITY_BUCKET):
        minio.make_bucket(COMMUNITY_BUCKET)

def _img_ext(content_type: str) -> str:
    return {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}.get(content_type, "jpg")


# ── Pydantic Models ───────────────────────────────────────────────────────────

class PostCreate(BaseModel):
    category: str
    title: str
    content: str
    tags: Optional[List[str]] = []
    image_keys: Optional[List[str]] = []

class PostUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    category: Optional[str] = None
    tags: Optional[List[str]] = None
    image_keys: Optional[List[str]] = None

class CommentCreate(BaseModel):
    content: str
    parent_id: Optional[int] = None

class ReportCreate(BaseModel):
    target_type: str
    target_id: int
    reason: str


# ── 이미지 서빙 (/images/{key} — /{post_id} 보다 먼저 정의) ─────────────────

@router.get("/images/{image_key:path}")
def serve_image(image_key: str):
    if ".." in image_key or image_key.startswith("/"):
        raise HTTPException(400, "잘못된 경로입니다.")
    safe_key = image_key.lstrip("/")
    try:
        minio = _get_minio()
        obj = minio.get_object(COMMUNITY_BUCKET, safe_key)
        content_type = "image/jpeg"
        if safe_key.endswith(".png"):
            content_type = "image/png"
        elif safe_key.endswith(".webp"):
            content_type = "image/webp"
        return StreamingResponse(obj, media_type=content_type)
    except Exception:
        raise HTTPException(404, "이미지를 찾을 수 없습니다.")


# ── 댓글 좋아요 (/comments/{} — /{post_id} 보다 먼저 정의) ──────────────────

@router.post("/comments/{comment_id}/like")
def toggle_comment_like(
    comment_id: int,
    swimtech_token: str = Cookie(default=None),
):
    payload = _require_login(swimtech_token)
    me_id = payload.get("customer_id")
    if not me_id:
        raise HTTPException(403, "일반 계정으로 로그인해주세요.")
    conn = _get_db(); cur = conn.cursor()
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
                "UPDATE comments SET likes=GREATEST(0,likes-1) WHERE id=%s RETURNING likes",
                (comment_id,),
            )
            liked = False
        else:
            cur.execute(
                "INSERT INTO comment_likes (comment_id,customer_id) VALUES(%s,%s) ON CONFLICT DO NOTHING",
                (comment_id, me_id),
            )
            cur.execute(
                "UPDATE comments SET likes=likes+1 WHERE id=%s RETURNING likes",
                (comment_id,),
            )
            liked = True
        likes = cur.fetchone()[0]
        conn.commit()
        return {"liked": liked, "likes": likes}
    except HTTPException:
        raise
    except Exception:
        conn.rollback(); logger.error("toggle_comment_like error", exc_info=True)
        raise HTTPException(500, "내부 오류가 발생했습니다.")
    finally:
        cur.close(); conn.close()


# ── 댓글 삭제 ─────────────────────────────────────────────────────────────────

@router.delete("/comments/{comment_id}")
def delete_comment(
    comment_id: int,
    swimtech_token: str = Cookie(default=None),
):
    payload = _require_login(swimtech_token)
    me_id = payload.get("customer_id"); username = payload.get("sub")
    conn = _get_db(); cur = conn.cursor()
    try:
        cur.execute("SELECT customer_id FROM comments WHERE id=%s", (comment_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "댓글을 찾을 수 없습니다.")
        if row[0] != me_id and username != ADMIN_ID:
            raise HTTPException(403, "삭제 권한이 없습니다.")
        cur.execute("DELETE FROM comments WHERE id=%s", (comment_id,))
        conn.commit()
        return {"status": "ok"}
    except HTTPException:
        raise
    except Exception:
        conn.rollback(); logger.error("delete_comment error", exc_info=True)
        raise HTTPException(500, "내부 오류가 발생했습니다.")
    finally:
        cur.close(); conn.close()


# ── 주간 인기글 (static routes — /{post_id} 보다 먼저 정의) ─────────────────

@router.get("/top-posts")
def top_posts():
    conn = _get_db(); cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT p.id, p.category, p.title,
                   COALESCE(c.nickname, c.username, '익명') AS author,
                   p.likes, p.views, p.created_at,
                   (SELECT COUNT(*) FROM comments cm WHERE cm.post_id=p.id) AS comment_count
            FROM posts p
            LEFT JOIN customers c ON c.id=p.customer_id
            WHERE p.is_hidden = FALSE
              AND p.created_at >= NOW() - INTERVAL '7 days'
            ORDER BY p.likes DESC, p.views DESC
            LIMIT 3
            """,
        )
        rows = cur.fetchall()
        return {"posts": [
            {
                "id": r[0], "category": r[1], "title": r[2], "author": r[3],
                "likes": r[4], "views": r[5],
                "created_at": r[6].isoformat() if r[6] else None,
                "comment_count": r[7],
            }
            for r in rows
        ]}
    except Exception:
        logger.error("top_posts error", exc_info=True)
        raise HTTPException(500, "내부 오류가 발생했습니다.")
    finally:
        cur.close(); conn.close()


# ── 신고 접수 ─────────────────────────────────────────────────────────────────

@router.post("/report")
def submit_report(
    body: ReportCreate,
    swimtech_token: str = Cookie(default=None),
):
    payload = _require_login(swimtech_token)
    me_id = payload.get("customer_id")
    if not me_id:
        raise HTTPException(403, "일반 계정으로 로그인해주세요.")
    if body.target_type not in ("post", "comment"):
        raise HTTPException(400, "target_type은 post 또는 comment여야 합니다.")
    if body.reason not in VALID_REASONS:
        raise HTTPException(400, "올바르지 않은 신고 사유입니다.")
    conn = _get_db(); cur = conn.cursor()
    try:
        cur.execute(
            "SELECT 1 FROM reports WHERE reporter_id=%s AND target_type=%s AND target_id=%s",
            (me_id, body.target_type, body.target_id),
        )
        if cur.fetchone():
            raise HTTPException(409, "이미 신고한 대상입니다.")
        cur.execute(
            "INSERT INTO reports (reporter_id,target_type,target_id,reason) VALUES(%s,%s,%s,%s)",
            (me_id, body.target_type, body.target_id, body.reason),
        )
        if body.target_type == "post":
            cur.execute(
                "SELECT COUNT(*) FROM reports WHERE target_type='post' AND target_id=%s",
                (body.target_id,),
            )
            if cur.fetchone()[0] >= 3:
                cur.execute("UPDATE posts SET is_hidden=TRUE WHERE id=%s", (body.target_id,))
        conn.commit()
        return {"status": "ok"}
    except HTTPException:
        raise
    except Exception:
        conn.rollback(); logger.error("submit_report error", exc_info=True)
        raise HTTPException(500, "내부 오류가 발생했습니다.")
    finally:
        cur.close(); conn.close()


# ── 신고 목록 (관리자) ────────────────────────────────────────────────────────

@router.get("/reports")
def list_reports(swimtech_token: str = Cookie(default=None)):
    payload = _require_login(swimtech_token)
    if payload.get("sub") != ADMIN_ID:
        raise HTTPException(403, "관리자만 접근 가능합니다.")
    conn = _get_db(); cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT r.id, r.reporter_id, r.target_type, r.target_id, r.reason, r.created_at,
                   COALESCE(c.nickname, c.username, '익명') AS reporter
            FROM reports r
            LEFT JOIN customers c ON c.id=r.reporter_id
            ORDER BY r.created_at DESC
            LIMIT 200
            """,
        )
        return {"reports": [
            {
                "id": r[0], "reporter_id": r[1], "target_type": r[2],
                "target_id": r[3], "reason": r[4],
                "created_at": r[5].isoformat() if r[5] else None,
                "reporter": r[6],
            }
            for r in cur.fetchall()
        ]}
    except Exception:
        logger.error("list_reports error", exc_info=True)
        raise HTTPException(500, "내부 오류가 발생했습니다.")
    finally:
        cur.close(); conn.close()


# ── 이미지 업로드 ─────────────────────────────────────────────────────────────

@router.post("/upload-image")
async def upload_image(
    file: UploadFile = File(...),
    swimtech_token: str = Cookie(default=None),
):
    _require_login(swimtech_token)
    if file.content_type not in ALLOWED_IMG_TYPES:
        raise HTTPException(400, "지원하지 않는 형식입니다. (jpg/png/webp)")
    content = await file.read()
    if len(content) > MAX_IMAGE_SIZE:
        raise HTTPException(400, "파일 크기는 5MB 이하여야 합니다.")
    ext = _img_ext(file.content_type)
    key = f"{uuid.uuid4().hex}.{ext}"
    try:
        minio = _get_minio()
        _ensure_community_bucket(minio)
        minio.put_object(
            COMMUNITY_BUCKET, key,
            io.BytesIO(content), len(content),
            content_type=file.content_type,
        )
    except Exception:
        logger.error("upload_image: MinIO error", exc_info=True)
        raise HTTPException(503, "이미지 업로드 서비스를 사용할 수 없습니다.")
    return {"key": key, "url": f"/api/community/images/{key}"}


# ── 내 북마크 목록 ───────────────────────────────────────────────────────────

@router.get("/bookmarks")
def my_bookmarks(
    swimtech_token: str = Cookie(default=None),
    page: int = Query(1, ge=1),
):
    payload = _require_login(swimtech_token)
    me_id = payload.get("customer_id")
    if not me_id:
        raise HTTPException(403, "일반 계정으로 로그인해주세요.")
    limit = 20; offset = (page - 1) * limit
    conn = _get_db(); cur = conn.cursor()
    try:
        cur.execute("SELECT COUNT(*) FROM bookmarks WHERE customer_id=%s", (me_id,))
        total = cur.fetchone()[0]
        cur.execute(
            """
            SELECT p.id, p.category, p.title,
                   COALESCE(c.nickname, c.username, '익명') AS author,
                   p.likes, p.views, p.created_at,
                   (SELECT COUNT(*) FROM comments cm WHERE cm.post_id=p.id) AS comment_count
            FROM bookmarks b
            JOIN posts p ON p.id=b.post_id
            LEFT JOIN customers c ON c.id=p.customer_id
            WHERE b.customer_id=%s AND p.is_hidden=FALSE
            ORDER BY b.created_at DESC
            LIMIT %s OFFSET %s
            """,
            (me_id, limit, offset),
        )
        return {
            "posts": [
                {
                    "id": r[0], "category": r[1], "title": r[2], "author": r[3],
                    "likes": r[4], "views": r[5],
                    "created_at": r[6].isoformat() if r[6] else None,
                    "comment_count": r[7], "bookmarked": True,
                }
                for r in cur.fetchall()
            ],
            "total": total, "page": page, "limit": limit,
        }
    except Exception:
        logger.error("my_bookmarks error", exc_info=True)
        raise HTTPException(500, "내부 오류가 발생했습니다.")
    finally:
        cur.close(); conn.close()


# ── 인기 태그 ─────────────────────────────────────────────────────────────────

@router.get("/tags")
def popular_tags():
    conn = _get_db(); cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT pt.tag, COUNT(*) AS cnt
            FROM post_tags pt
            JOIN posts p ON p.id=pt.post_id
            WHERE p.is_hidden=FALSE
            GROUP BY pt.tag
            ORDER BY cnt DESC
            LIMIT 20
            """,
        )
        return {"tags": [{"tag": r[0], "count": r[1]} for r in cur.fetchall()]}
    except Exception:
        logger.error("popular_tags error", exc_info=True)
        return {"tags": []}
    finally:
        cur.close(); conn.close()


# ── 멘션 자동완성 ─────────────────────────────────────────────────────────────

@router.get("/mentions")
def mention_suggestions(q: str = Query("", max_length=30)):
    conn = _get_db(); cur = conn.cursor()
    try:
        pattern = f"{q}%" if q else "%"
        cur.execute(
            """
            SELECT DISTINCT COALESCE(nickname, username) AS name
            FROM customers
            WHERE (nickname ILIKE %s OR username ILIKE %s)
              AND (nickname IS NOT NULL OR username IS NOT NULL)
            ORDER BY name
            LIMIT 10
            """,
            (pattern, pattern),
        )
        return {"users": [r[0] for r in cur.fetchall() if r[0]]}
    except Exception:
        return {"users": []}
    finally:
        cur.close(); conn.close()


# ── 게시글 목록 ──────────────────────────────────────────────────────────────

@router.get("")
def list_posts(
    category: str = Query("전체"),
    page: int = Query(1, ge=1),
    search: str = Query(""),
    sort: str = Query("latest"),
    tag: str = Query(""),
    swimtech_token: str = Cookie(default=None),
):
    limit = 20; offset = (page - 1) * limit
    if sort not in VALID_SORT:
        sort = "latest"

    payload = decode_token(swimtech_token) if swimtech_token else {}
    me_id = payload.get("customer_id")

    conditions: list[str] = ["p.is_hidden = FALSE"]
    params: list = []

    if category and category != "전체":
        conditions.append("p.category = %s"); params.append(category)
    if search:
        conditions.append("(p.title ILIKE %s OR p.content ILIKE %s)")
        params.extend([f"%{search}%", f"%{search}%"])
    if tag:
        conditions.append(
            "EXISTS (SELECT 1 FROM post_tags pt WHERE pt.post_id=p.id AND pt.tag=%s)"
        )
        params.append(tag)

    where = "WHERE " + " AND ".join(conditions)
    order_map = {
        "latest":  "p.created_at DESC",
        "popular": "p.likes DESC, p.created_at DESC",
        "views":   "p.views DESC, p.created_at DESC",
    }
    order_by = order_map[sort]

    conn = _get_db(); cur = conn.cursor()
    try:
        cur.execute(f"SELECT COUNT(*) FROM posts p {where}", params)
        total = cur.fetchone()[0]

        cur.execute(
            f"""
            SELECT p.id, p.category, p.title,
                   COALESCE(c.nickname, c.username, '익명') AS author,
                   p.likes, p.views, p.created_at,
                   (SELECT COUNT(*) FROM comments cm WHERE cm.post_id=p.id) AS comment_count
            FROM posts p
            LEFT JOIN customers c ON c.id=p.customer_id
            {where}
            ORDER BY {order_by}
            LIMIT %s OFFSET %s
            """,
            params + [limit, offset],
        )
        rows = cur.fetchall()

        bookmarked_ids: set = set()
        if me_id and rows:
            post_ids = [r[0] for r in rows]
            cur.execute(
                "SELECT post_id FROM bookmarks WHERE customer_id=%s AND post_id=ANY(%s)",
                (me_id, post_ids),
            )
            bookmarked_ids = {r[0] for r in cur.fetchall()}

        tags_map: dict = {}
        if rows:
            post_ids = [r[0] for r in rows]
            cur.execute(
                "SELECT post_id, tag FROM post_tags WHERE post_id=ANY(%s)",
                (post_ids,),
            )
            for pid, t in cur.fetchall():
                tags_map.setdefault(pid, []).append(t)

        posts = [
            {
                "id": r[0], "category": r[1], "title": r[2], "author": r[3],
                "likes": r[4], "views": r[5],
                "created_at": r[6].isoformat() if r[6] else None,
                "comment_count": r[7],
                "bookmarked": r[0] in bookmarked_ids,
                "tags": tags_map.get(r[0], []),
            }
            for r in rows
        ]
        return {"posts": posts, "total": total, "page": page, "limit": limit}
    except Exception:
        logger.error("list_posts error", exc_info=True)
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

    tags = [_strip(t) for t in (body.tags or []) if _strip(t)][:MAX_TAGS]
    image_keys = (body.image_keys or [])[:MAX_IMAGES]

    conn = _get_db(); cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO posts (customer_id,category,title,content) VALUES(%s,%s,%s,%s) RETURNING id",
            (me_id, category, title, content),
        )
        post_id = cur.fetchone()[0]
        for i, key in enumerate(image_keys):
            if key:
                cur.execute(
                    "INSERT INTO post_images (post_id,minio_key,sort_order) VALUES(%s,%s,%s)",
                    (post_id, key, i),
                )
        for tag in tags:
            cur.execute(
                "INSERT INTO post_tags (post_id,tag) VALUES(%s,%s) ON CONFLICT DO NOTHING",
                (post_id, tag),
            )
        conn.commit()
        return {"status": "ok", "id": post_id}
    except Exception:
        conn.rollback(); logger.error("create_post error", exc_info=True)
        raise HTTPException(500, "내부 오류가 발생했습니다.")
    finally:
        cur.close(); conn.close()


# ── 게시글 상세 ──────────────────────────────────────────────────────────────

@router.get("/{post_id}")
def get_post(post_id: int, swimtech_token: str = Cookie(default=None)):
    conn = _get_db(); cur = conn.cursor()
    try:
        cur.execute(
            "UPDATE posts SET views=views+1 WHERE id=%s AND is_hidden=FALSE",
            (post_id,),
        )
        conn.commit()

        cur.execute(
            """
            SELECT p.id, p.category, p.title, p.content,
                   COALESCE(c.nickname, c.username, '익명') AS author,
                   p.customer_id, p.likes, p.views, p.created_at, p.updated_at
            FROM posts p
            LEFT JOIN customers c ON c.id=p.customer_id
            WHERE p.id=%s AND p.is_hidden=FALSE
            """,
            (post_id,),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "게시글을 찾을 수 없습니다.")

        payload = decode_token(swimtech_token) if swimtech_token else {}
        me_id = payload.get("customer_id")

        liked = False; bookmarked = False
        if me_id:
            cur.execute(
                "SELECT 1 FROM post_likes WHERE post_id=%s AND customer_id=%s",
                (post_id, me_id),
            )
            liked = cur.fetchone() is not None
            cur.execute(
                "SELECT 1 FROM bookmarks WHERE post_id=%s AND customer_id=%s",
                (post_id, me_id),
            )
            bookmarked = cur.fetchone() is not None

        cur.execute(
            "SELECT id, minio_key, sort_order FROM post_images WHERE post_id=%s ORDER BY sort_order",
            (post_id,),
        )
        images = [
            {"id": r[0], "key": r[1], "url": f"/api/community/images/{r[1]}", "order": r[2]}
            for r in cur.fetchall()
        ]

        cur.execute("SELECT tag FROM post_tags WHERE post_id=%s ORDER BY tag", (post_id,))
        tags = [r[0] for r in cur.fetchall()]

        post = {
            "id": row[0], "category": row[1], "title": row[2], "content": row[3],
            "author": row[4], "customer_id": row[5], "likes": row[6], "views": row[7],
            "created_at": row[8].isoformat() if row[8] else None,
            "updated_at": row[9].isoformat() if row[9] else None,
            "liked": liked, "bookmarked": bookmarked, "is_mine": me_id == row[5],
            "images": images, "tags": tags,
        }

        cur.execute(
            """
            SELECT cm.id, cm.parent_id, cm.content,
                   COALESCE(c.nickname, c.username, '익명') AS author,
                   cm.customer_id, cm.likes, cm.created_at
            FROM comments cm
            LEFT JOIN customers c ON c.id=cm.customer_id
            WHERE cm.post_id=%s
            ORDER BY cm.created_at ASC
            """,
            (post_id,),
        )
        comment_rows = cur.fetchall()

        liked_ids: set = set()
        if me_id and comment_rows:
            c_ids = [r[0] for r in comment_rows]
            cur.execute(
                "SELECT comment_id FROM comment_likes WHERE customer_id=%s AND comment_id=ANY(%s)",
                [me_id, c_ids],
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
        logger.error("get_post error", exc_info=True)
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
    me_id = payload.get("customer_id"); username = payload.get("sub")
    conn = _get_db(); cur = conn.cursor()
    try:
        cur.execute("SELECT customer_id FROM posts WHERE id=%s", (post_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "게시글을 찾을 수 없습니다.")
        if row[0] != me_id and username != ADMIN_ID:
            raise HTTPException(403, "수정 권한이 없습니다.")

        updates: list[str] = []; params: list = []
        if body.title is not None:
            title = _strip(body.title)
            if not title or len(title) > 200:
                raise HTTPException(400, "제목은 1~200자여야 합니다.")
            updates.append("title=%s"); params.append(title)
        if body.content is not None:
            content = _strip(body.content)
            if not content or len(content) > 10000:
                raise HTTPException(400, "내용은 1~10000자여야 합니다.")
            updates.append("content=%s"); params.append(content)
        if body.category is not None:
            cat = _strip(body.category)
            if cat not in VALID_CATEGORIES:
                raise HTTPException(400, "올바르지 않은 카테고리입니다.")
            updates.append("category=%s"); params.append(cat)
        if updates:
            updates.append("updated_at=NOW()")
            cur.execute(
                f"UPDATE posts SET {','.join(updates)} WHERE id=%s",
                params + [post_id],
            )

        if body.image_keys is not None:
            cur.execute("DELETE FROM post_images WHERE post_id=%s", (post_id,))
            for i, key in enumerate(body.image_keys[:MAX_IMAGES]):
                if key:
                    cur.execute(
                        "INSERT INTO post_images (post_id,minio_key,sort_order) VALUES(%s,%s,%s)",
                        (post_id, key, i),
                    )

        if body.tags is not None:
            cur.execute("DELETE FROM post_tags WHERE post_id=%s", (post_id,))
            for tag in [_strip(t) for t in body.tags if _strip(t)][:MAX_TAGS]:
                cur.execute(
                    "INSERT INTO post_tags (post_id,tag) VALUES(%s,%s) ON CONFLICT DO NOTHING",
                    (post_id, tag),
                )

        conn.commit()
        return {"status": "ok"}
    except HTTPException:
        raise
    except Exception:
        conn.rollback(); logger.error("update_post error", exc_info=True)
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
    me_id = payload.get("customer_id"); username = payload.get("sub")
    conn = _get_db(); cur = conn.cursor()
    try:
        cur.execute("SELECT customer_id FROM posts WHERE id=%s", (post_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "게시글을 찾을 수 없습니다.")
        if row[0] != me_id and username != ADMIN_ID:
            raise HTTPException(403, "삭제 권한이 없습니다.")
        cur.execute("DELETE FROM posts WHERE id=%s", (post_id,))
        conn.commit()
        return {"status": "ok"}
    except HTTPException:
        raise
    except Exception:
        conn.rollback(); logger.error("delete_post error", exc_info=True)
        raise HTTPException(500, "내부 오류가 발생했습니다.")
    finally:
        cur.close(); conn.close()


# ── 게시글 좋아요 ─────────────────────────────────────────────────────────────

@router.post("/{post_id}/like")
def toggle_post_like(
    post_id: int,
    swimtech_token: str = Cookie(default=None),
):
    payload = _require_login(swimtech_token)
    me_id = payload.get("customer_id")
    if not me_id:
        raise HTTPException(403, "일반 계정으로 로그인해주세요.")
    conn = _get_db(); cur = conn.cursor()
    try:
        cur.execute(
            "SELECT id, customer_id FROM posts WHERE id=%s AND is_hidden=FALSE",
            (post_id,),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "게시글을 찾을 수 없습니다.")
        post_owner_id = row[1]

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
                "UPDATE posts SET likes=GREATEST(0,likes-1) WHERE id=%s RETURNING likes",
                (post_id,),
            )
            liked = False
        else:
            cur.execute(
                "INSERT INTO post_likes (post_id,customer_id) VALUES(%s,%s) ON CONFLICT DO NOTHING",
                (post_id, me_id),
            )
            cur.execute(
                "UPDATE posts SET likes=likes+1 WHERE id=%s RETURNING likes",
                (post_id,),
            )
            liked = True
            if post_owner_id and post_owner_id != me_id:
                _notify(cur, post_owner_id, "like", "회원님의 게시글에 좋아요가 달렸습니다.", post_id)

        likes = cur.fetchone()[0]
        conn.commit()
        return {"liked": liked, "likes": likes}
    except HTTPException:
        raise
    except Exception:
        conn.rollback(); logger.error("toggle_post_like error", exc_info=True)
        raise HTTPException(500, "내부 오류가 발생했습니다.")
    finally:
        cur.close(); conn.close()


# ── 게시글 북마크 ─────────────────────────────────────────────────────────────

@router.post("/{post_id}/bookmark")
def toggle_bookmark(
    post_id: int,
    swimtech_token: str = Cookie(default=None),
):
    payload = _require_login(swimtech_token)
    me_id = payload.get("customer_id")
    if not me_id:
        raise HTTPException(403, "일반 계정으로 로그인해주세요.")
    conn = _get_db(); cur = conn.cursor()
    try:
        cur.execute(
            "SELECT id FROM posts WHERE id=%s AND is_hidden=FALSE",
            (post_id,),
        )
        if not cur.fetchone():
            raise HTTPException(404, "게시글을 찾을 수 없습니다.")
        cur.execute(
            "SELECT 1 FROM bookmarks WHERE post_id=%s AND customer_id=%s",
            (post_id, me_id),
        )
        if cur.fetchone():
            cur.execute(
                "DELETE FROM bookmarks WHERE post_id=%s AND customer_id=%s",
                (post_id, me_id),
            )
            bookmarked = False
        else:
            cur.execute(
                "INSERT INTO bookmarks (post_id,customer_id) VALUES(%s,%s) ON CONFLICT DO NOTHING",
                (post_id, me_id),
            )
            bookmarked = True
        conn.commit()
        return {"bookmarked": bookmarked}
    except HTTPException:
        raise
    except Exception:
        conn.rollback(); logger.error("toggle_bookmark error", exc_info=True)
        raise HTTPException(500, "내부 오류가 발생했습니다.")
    finally:
        cur.close(); conn.close()


# ── 댓글 작성 ─────────────────────────────────────────────────────────────────

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

    conn = _get_db(); cur = conn.cursor()
    try:
        cur.execute(
            "SELECT id, customer_id FROM posts WHERE id=%s AND is_hidden=FALSE",
            (post_id,),
        )
        post_row = cur.fetchone()
        if not post_row:
            raise HTTPException(404, "게시글을 찾을 수 없습니다.")
        post_owner_id = post_row[1]

        if body.parent_id is not None:
            cur.execute(
                "SELECT id FROM comments WHERE id=%s AND post_id=%s",
                (body.parent_id, post_id),
            )
            if not cur.fetchone():
                raise HTTPException(400, "부모 댓글을 찾을 수 없습니다.")

        cur.execute(
            "SELECT COALESCE(nickname, username, '익명') FROM customers WHERE id=%s",
            (me_id,),
        )
        me_row = cur.fetchone()
        commenter_name = me_row[0] if me_row else "익명"

        cur.execute(
            "INSERT INTO comments (post_id,customer_id,parent_id,content) VALUES(%s,%s,%s,%s) RETURNING id",
            (post_id, me_id, body.parent_id, content),
        )
        comment_id = cur.fetchone()[0]

        if post_owner_id and post_owner_id != me_id:
            _notify(
                cur, post_owner_id, "comment",
                f"{commenter_name}님이 댓글을 달았습니다.", post_id,
            )

        mentioned_names = set(_MENTION_RE.findall(content))
        if mentioned_names:
            placeholders = ",".join(["%s"] * len(mentioned_names))
            cur.execute(
                f"""SELECT id, COALESCE(nickname, username) FROM customers
                    WHERE COALESCE(nickname, username) IN ({placeholders}) AND id != %s""",
                list(mentioned_names) + [me_id],
            )
            for uid, _ in cur.fetchall():
                _notify(
                    cur, uid, "mention",
                    f"{commenter_name}님이 댓글에서 회원님을 언급했습니다.", post_id,
                )

        conn.commit()
        return {"status": "ok", "id": comment_id}
    except HTTPException:
        raise
    except Exception:
        conn.rollback(); logger.error("create_comment error", exc_info=True)
        raise HTTPException(500, "내부 오류가 발생했습니다.")
    finally:
        cur.close(); conn.close()
