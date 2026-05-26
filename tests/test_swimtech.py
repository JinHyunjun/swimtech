"""
SwimTech — 통합 테스트
커뮤니티 페이지/API 테스트 포함

실행: pytest tests/test_swimtech.py -v
환경변수: TEST_BASE_URL (기본값: https://localhost)
         VERIFY_SSL    (기본값: false)
"""
import os
import pytest
import httpx

BASE_URL   = os.getenv("TEST_BASE_URL", "https://localhost")
VERIFY_SSL = os.getenv("VERIFY_SSL", "false").lower() != "false"

# ── 픽스처 ────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def client():
    """세션 공유 httpx 클라이언트 (쿠키 유지)"""
    with httpx.Client(base_url=BASE_URL, verify=VERIFY_SSL, timeout=10, follow_redirects=True) as c:
        yield c


@pytest.fixture(scope="session")
def auth_client():
    """로그인된 클라이언트 (admin 계정 사용)"""
    admin_id = os.getenv("ADMIN_ID", "admin")
    admin_pw = os.getenv("ADMIN_PW", "swimtech1234")
    with httpx.Client(base_url=BASE_URL, verify=VERIFY_SSL, timeout=10, follow_redirects=True) as c:
        res = c.post("/auth/login", json={"username": admin_id, "password": admin_pw})
        # admin은 customers 테이블에 없어 customer_id가 없을 수 있으므로 체크만
        yield c


# ── 헬스 체크 ─────────────────────────────────────────────────────────────────

def test_health(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json()["status"] == "healthy"


# ── 커뮤니티 페이지 로드 ──────────────────────────────────────────────────────

def test_community_load(client):
    """커뮤니티 페이지가 200 OK로 로드되어야 한다."""
    res = client.get("/community")
    assert res.status_code == 200, f"Expected 200, got {res.status_code}"
    # SwimTech 공통 헤더/요소 확인
    assert "SwimTech" in res.text
    assert "커뮤니티" in res.text


def test_community_load_has_categories(client):
    """카테고리 탭(자유/질문/훈련후기/공지)이 HTML에 포함되어야 한다."""
    res = client.get("/community")
    assert res.status_code == 200
    for cat in ["자유", "질문", "훈련후기", "공지"]:
        assert cat in res.text, f"카테고리 '{cat}'가 페이지에 없음"


def test_community_write_btn(client):
    """글쓰기 버튼 요소(write-btn)가 HTML에 존재해야 한다."""
    res = client.get("/community")
    assert res.status_code == 200
    assert "write-btn" in res.text, "글쓰기 버튼 id='write-btn'이 없음"
    # 비로그인 시 display:none 으로 숨겨져야 함
    assert "display: none" in res.text or "display:none" in res.text, \
        "비로그인 시 글쓰기 버튼이 숨겨져 있어야 함"


# ── 커뮤니티 API ──────────────────────────────────────────────────────────────

def test_community_api_list(client):
    """게시글 목록 API가 올바른 구조를 반환해야 한다."""
    res = client.get("/api/community")
    assert res.status_code == 200
    data = res.json()
    assert "posts" in data
    assert "total" in data
    assert "page" in data
    assert "limit" in data
    assert isinstance(data["posts"], list)
    assert data["page"] == 1


def test_community_api_list_category(client):
    """카테고리 필터가 동작해야 한다."""
    for cat in ["자유", "질문", "훈련후기", "공지"]:
        res = client.get("/api/community", params={"category": cat})
        assert res.status_code == 200, f"category={cat} 실패"
        data = res.json()
        assert "posts" in data
        # 필터된 게시글은 모두 해당 카테고리여야 함
        for post in data["posts"]:
            assert post["category"] == cat


def test_community_api_list_search(client):
    """검색 파라미터가 동작해야 한다."""
    res = client.get("/api/community", params={"search": "테스트검색어_없음"})
    assert res.status_code == 200
    data = res.json()
    assert data["posts"] == []
    assert data["total"] == 0


def test_community_api_write_requires_login(client):
    """비로그인 상태에서 게시글 작성은 401을 반환해야 한다."""
    res = client.post("/api/community", json={
        "category": "자유",
        "title": "테스트 제목",
        "content": "테스트 내용입니다.",
    })
    assert res.status_code == 401, f"Expected 401, got {res.status_code}"


def test_community_api_post_not_found(client):
    """존재하지 않는 게시글 상세 조회는 404를 반환해야 한다."""
    res = client.get("/api/community/99999999")
    assert res.status_code == 404


def test_community_api_like_requires_login(client):
    """비로그인 좋아요는 401을 반환해야 한다."""
    res = client.post("/api/community/1/like")
    assert res.status_code == 401


def test_community_api_comment_requires_login(client):
    """비로그인 댓글 작성은 401을 반환해야 한다."""
    res = client.post("/api/community/1/comments", json={"content": "댓글"})
    assert res.status_code == 401


def test_community_api_delete_requires_login(client):
    """비로그인 게시글 삭제는 401을 반환해야 한다."""
    res = client.delete("/api/community/1")
    assert res.status_code == 401


def test_community_api_pagination(client):
    """페이지 파라미터가 동작해야 한다."""
    res = client.get("/api/community", params={"page": 2})
    assert res.status_code == 200
    data = res.json()
    assert data["page"] == 2
    assert "posts" in data


def test_community_api_invalid_page(client):
    """page < 1은 422 Unprocessable Entity를 반환해야 한다."""
    res = client.get("/api/community", params={"page": 0})
    assert res.status_code == 422
