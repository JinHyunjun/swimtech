"""AI coach knowledge grounding and privacy-minimized personalization tests."""
from pathlib import Path
from datetime import date


ROOT = Path(__file__).resolve().parent.parent


def test_freestyle_question_selects_reviewed_stroke_knowledge():
    from services.swimming_knowledge import grounding_payload, retrieve_knowledge

    items = retrieve_knowledge("자유형 호흡할 때 다리가 가라앉아요")
    assert items
    assert items[0].key == "freestyle_basics"

    grounding = grounding_payload(items)
    assert any(source["organization"] == "Swim England" for source in grounding["sources"])
    assert any(link["url"] == "/drill" for link in grounding["related_links"])


def test_pool_cycle_question_combines_course_and_interval_knowledge():
    from services.swimming_knowledge import retrieve_knowledge

    keys = {
        item.key
        for item in retrieve_knowledge(
            "25m 풀에서 자유형 50m 사이클과 휴식은 어떻게 정하나요?"
        )
    }
    assert {"pool_length", "training_cycle"} <= keys


def test_competition_rules_are_marked_for_current_verification():
    from services.swimming_knowledge import grounding_payload, retrieve_knowledge

    items = retrieve_knowledge("평영 경기 실격과 터치 규정을 알려줘")
    rules = next(item for item in items if item.key == "competition_rules")
    assert rules.current_verification_required is True

    grounding = grounding_payload(items)
    assert any(
        source["organization"] == "World Aquatics"
        and source["url"].startswith("https://www.worldaquatics.com/")
        for source in grounding["sources"]
    )


def test_unrelated_question_does_not_attach_swimming_sources():
    from services.swimming_knowledge import retrieve_knowledge

    assert retrieve_knowledge("파이썬 정렬 알고리즘을 알려줘") == []


def test_personalization_intent_is_explicit():
    from services.chat_personalization import should_personalize

    assert should_personalize("내 최근 훈련을 바탕으로 다음 세션을 추천해줘")
    assert should_personalize("이번 달 목표 달성률을 분석해줘")
    assert should_personalize("제 기록이라면 사이클을 어떻게 잡나요?")
    assert not should_personalize("접영 돌핀킥의 기본 원리를 알려줘")
    assert not should_personalize("입문자용 수영 장비를 추천해줘")
    assert not should_personalize("이번 주 평영 경기 규정을 알려줘")


class _FakeCursor:
    def __init__(self):
        self.query = ""
        self.params = None
        self.closed = False

    def execute(self, query, params=None):
        self.query = " ".join(query.split())
        self.params = params

    def fetchone(self):
        if "FROM customers" in self.query:
            return (7, "중급", "영법교정", 4, 50)
        if "COUNT(*) FILTER" in self.query and "FROM training_logs" in self.query:
            return (2, 2600, 5, 7200, 190)
        if "to_regclass('public.training_goals')" in self.query:
            return (False, False, False, False, False, False)
        return None

    def fetchall(self):
        if "FROM training_logs" in self.query:
            return [
                (date(2026, 7, 26), "자유형", 1600, 42, 50, "보통", "좋음"),
                (date(2026, 7, 23), "배영", 1000, 30, 25, "쉬움", "보통"),
            ]
        return []

    def close(self):
        self.closed = True


class _FakeConnection:
    def __init__(self):
        self.cursor_instance = _FakeCursor()
        self.closed = False

    def cursor(self):
        return self.cursor_instance

    def close(self):
        self.closed = True


def test_personalization_uses_training_data_without_identity_or_free_text():
    from services.chat_personalization import load_personalization

    connection = _FakeConnection()
    snapshot = load_personalization(
        "private-user",
        "내 최근 훈련을 바탕으로 맞춤 세션을 추천해줘",
        lambda: connection,
    )

    assert snapshot.available is True
    assert snapshot.applied is True
    assert "훈련 설정" in snapshot.categories
    assert "최근 훈련" in snapshot.categories
    assert "50m 풀" in snapshot.text
    assert "private-user" not in snapshot.text
    assert "username" not in snapshot.text.lower()
    assert connection.cursor_instance.closed is True
    assert connection.closed is True


def test_general_question_does_not_load_detailed_personal_records():
    from services.chat_personalization import load_personalization

    connection = _FakeConnection()
    snapshot = load_personalization(
        "private-user",
        "배영 기본 자세를 알려줘",
        lambda: connection,
    )

    assert snapshot.available is True
    assert snapshot.applied is False
    assert snapshot.text == ""
    assert snapshot.categories == ()
    assert connection.cursor_instance.closed is True
    assert connection.closed is True


def test_chat_model_family_is_unchanged_and_context_preview_is_registered():
    from routers import chat

    assert chat.MODEL_FALLBACKS[0] == "gemini-3.1-flash-lite"
    assert all(not model.startswith("gpt-") for model in chat.MODEL_FALLBACKS)
    paths = {route.path for route in chat.router.routes}
    assert "/context-preview" in paths
    assert "/send" in paths

    workflow = (ROOT / ".github" / "workflows" / "qa.yml").read_text(encoding="utf-8")
    api_qa = (ROOT / "scripts" / "qa_runner.py").read_text(encoding="utf-8")
    ui_qa = (ROOT / "scripts" / "qa_ui_crawler.py").read_text(encoding="utf-8")
    chat_page = (ROOT / "frontend" / "chat.html").read_text(encoding="utf-8")
    checklist = (ROOT / "FEATURE_CHECKLIST.md").read_text(encoding="utf-8")

    assert "tests/test_chat_grounding.py" in workflow
    assert "/api/chat/context-preview" in api_qa
    assert "AI 코치 지식 근거·본인 기록 개인화 매핑" in api_qa
    assert '"#chat-grounding-info"' in ui_qa
    assert "renderSafeMarkdown" in chat_page
    assert "script,style,iframe,object,embed" in chat_page
    assert "P14 — 완료" in checklist
