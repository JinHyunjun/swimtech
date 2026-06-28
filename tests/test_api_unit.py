"""API unit tests — no browser, no DB, no MinIO required.
Runs in CI via: pytest tests/test_api_unit.py
"""
from datetime import date

import pytest

# ---------------------------------------------------------------------------
# 1. community router — constants & regex
# ---------------------------------------------------------------------------
class TestCommunityConstants:
    def test_valid_reasons_count(self):
        from routers.community import VALID_REASONS
        assert len(VALID_REASONS) == 5

    def test_valid_reasons_content(self):
        from routers.community import VALID_REASONS
        assert "스팸" in VALID_REASONS
        assert "욕설" in VALID_REASONS

    def test_max_images(self):
        from routers.community import MAX_IMAGES
        assert MAX_IMAGES == 3

    def test_max_image_size(self):
        from routers.community import MAX_IMAGE_SIZE
        assert MAX_IMAGE_SIZE == 5 * 1024 * 1024

    def test_allowed_image_types(self):
        from routers.community import ALLOWED_IMG_TYPES
        assert "image/jpeg" in ALLOWED_IMG_TYPES
        assert "image/png" in ALLOWED_IMG_TYPES
        assert "image/webp" in ALLOWED_IMG_TYPES

    def test_max_tags(self):
        from routers.community import MAX_TAGS
        assert MAX_TAGS == 10

    def test_mention_regex_matches(self):
        from routers.community import _MENTION_RE
        result = _MENTION_RE.findall("안녕 @alice, @bob123 테스트")
        assert result == ["alice", "bob123"]

    def test_mention_regex_no_match(self):
        from routers.community import _MENTION_RE
        result = _MENTION_RE.findall("태그 없음")
        assert result == []

    def test_mention_regex_returns_list(self):
        from routers.community import _MENTION_RE
        result = _MENTION_RE.findall("일반 텍스트")
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# 2. Pydantic models
# ---------------------------------------------------------------------------
class TestCommunityModels:
    def test_post_create_defaults(self):
        from routers.community import PostCreate
        m = PostCreate(category="공지", title="제목", content="내용")
        assert m.tags == []
        assert m.image_keys == []

    def test_post_create_with_tags(self):
        from routers.community import PostCreate
        m = PostCreate(category="자유", title="t", content="c", tags=["수영", "freestyle"])
        assert "수영" in m.tags

    def test_post_update_all_optional(self):
        from routers.community import PostUpdate
        m = PostUpdate()
        assert m.title is None
        assert m.content is None
        assert m.category is None

    def test_report_create_post(self):
        from routers.community import ReportCreate
        m = ReportCreate(target_type="post", target_id=1, reason="스팸")
        assert m.target_type == "post"

    def test_report_create_comment(self):
        from routers.community import ReportCreate
        m = ReportCreate(target_type="comment", target_id=42, reason="욕설")
        assert m.target_id == 42


# ---------------------------------------------------------------------------
# 3. Router registration
# ---------------------------------------------------------------------------
class TestRouterSetup:
    def test_community_router_exists(self):
        from routers.community import router
        assert router is not None

    def test_notifications_router_exists(self):
        from routers.notifications import router
        assert router is not None

    def test_community_router_has_routes(self):
        from routers.community import router
        assert len(router.routes) > 0

    def test_community_routes_include_bookmark(self):
        from routers.community import router
        paths = [r.path for r in router.routes]
        assert any("bookmark" in p for p in paths)

    def test_community_routes_include_report(self):
        from routers.community import router
        paths = [r.path for r in router.routes]
        assert any("report" in p for p in paths)

    def test_community_routes_include_tags(self):
        from routers.community import router
        paths = [r.path for r in router.routes]
        assert any("tags" in p for p in paths)

    def test_community_routes_include_mentions(self):
        from routers.community import router
        paths = [r.path for r in router.routes]
        assert any("mentions" in p for p in paths)

    def test_community_routes_include_top_posts(self):
        from routers.community import router
        paths = [r.path for r in router.routes]
        assert any("top-posts" in p for p in paths)

    def test_notifications_routes_include_count(self):
        from routers.notifications import router
        paths = [r.path for r in router.routes]
        assert any("count" in p for p in paths)

    def test_notifications_routes_include_read_all(self):
        from routers.notifications import router
        paths = [r.path for r in router.routes]
        assert any("read-all" in p for p in paths)


# ---------------------------------------------------------------------------
# 4. Category validation
# ---------------------------------------------------------------------------
class TestCategoryValues:
    VALID = ["공지", "자유", "질문", "훈련후기"]

    def test_valid_categories_accepted(self):
        from routers.community import PostCreate
        for cat in self.VALID:
            m = PostCreate(category=cat, title="t", content="c")
            assert m.category == cat

    def test_invalid_category_raises(self):
        from routers.community import PostCreate
        import pydantic
        with pytest.raises((pydantic.ValidationError, ValueError)):
            PostCreate(category="잘못된카테고리", title="t", content="c")


# ---------------------------------------------------------------------------
# 5. Notification router HTTP methods
# ---------------------------------------------------------------------------
class TestNotificationRouterMethods:
    def test_has_get_method(self):
        from routers.notifications import router
        methods = {m for r in router.routes for m in getattr(r, "methods", [])}
        assert "GET" in methods

    def test_has_put_method(self):
        from routers.notifications import router
        methods = {m for r in router.routes for m in getattr(r, "methods", [])}
        assert "PUT" in methods


# ---------------------------------------------------------------------------
# 6. Verified coach AI class-operation templates
# ---------------------------------------------------------------------------
class TestCoachAiClassOperations:
    def test_group_template_has_fixed_dates_and_operational_sets(self):
        from routers.coach_ai import GenerateClassDocumentRequest, _render_document, _template_document

        request = GenerateClassDocumentRequest(
            document_type="lesson_schedule",
            title="2주 혼합반",
            objective="자유형 호흡",
            start_date=date(2026, 6, 29),
            weeks=2,
            sessions_per_week=2,
        )
        result = _template_document(request)
        rendered = _render_document(request.title, request.audience_label, result)

        assert len(result.sessions) == 4
        assert result.sessions[0].session_date == "2026-06-29"
        assert "출석·안전 확인" in rendered
        assert "레인" in rendered
        assert "입문·초급 조정" in rendered

    def test_cohort_template_uses_anonymous_member_refs(self):
        from routers.coach_ai import _template_insight

        result = _template_insight([{
            "member_ref": "S1",
            "sessions_30d": 0,
            "distance_30d": 0,
            "avg_distance_30d": 0,
            "days_since_last": None,
            "hard_sessions_14d": 0,
            "latest_readiness_score": None,
        }])

        assert result.groups[0].member_refs == ["S1"]
        assert all("이름" not in group.rationale for group in result.groups)
