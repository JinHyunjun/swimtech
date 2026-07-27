"""Curated, deterministic swimming knowledge retrieval for the AI coach.

The model remains responsible for natural-language generation.  This module
only selects a small set of reviewed facts and source metadata so answers do
not depend on model memory alone.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


KNOWLEDGE_VERSION = "2026-07-27"


@dataclass(frozen=True)
class KnowledgeSource:
    key: str
    title: str
    organization: str
    url: str
    verified_on: str = KNOWLEDGE_VERSION


@dataclass(frozen=True)
class KnowledgeItem:
    key: str
    category: str
    title: str
    keywords: tuple[str, ...]
    facts: tuple[str, ...]
    source_keys: tuple[str, ...] = ()
    internal_links: tuple[tuple[str, str], ...] = ()
    current_verification_required: bool = False


SOURCES = {
    "world_aquatics_rules": KnowledgeSource(
        key="world_aquatics_rules",
        title="World Aquatics Competition Regulations",
        organization="World Aquatics",
        url="https://www.worldaquatics.com/rules/competition-regulations",
    ),
    "swim_england_strokes": KnowledgeSource(
        key="swim_england_strokes",
        title="Tips for learning the four swimming strokes",
        organization="Swim England",
        url="https://www.swimming.org/learntoswim/learning-the-four-swimming-strokes/",
    ),
    "swim_england_training": KnowledgeSource(
        key="swim_england_training",
        title="Learn to Swim Stages 8–10",
        organization="Swim England",
        url="https://www.swimming.org/learntoswim/swim-england-learn-to-swim-awards-8-10/",
    ),
    "swim_england_equipment": KnowledgeSource(
        key="swim_england_equipment",
        title="Adult swimming aids to help you learn",
        organization="Swim England",
        url="https://www.swimming.org/learntoswim/4-adult-swimming-aids-to-help-you-learn/",
    ),
    "red_cross_safety": KnowledgeSource(
        key="red_cross_safety",
        title="Swimming Safety",
        organization="American Red Cross",
        url=(
            "https://www.redcross.org/get-help/how-to-prepare-for-emergencies/"
            "types-of-emergencies/water-safety/swim-safety.html"
        ),
    ),
    "red_cross_general_safety": KnowledgeSource(
        key="red_cross_general_safety",
        title="General Water Safety",
        organization="American Red Cross",
        url=(
            "https://www.redcross.org/content/dam/redcross/uncategorized/2/"
            "2309_general_water_safety_final.pdf"
        ),
    ),
    "cdc_healthy_swimming": KnowledgeSource(
        key="cdc_healthy_swimming",
        title="Guidelines for Healthy and Safe Swimming",
        organization="U.S. Centers for Disease Control and Prevention",
        url="https://www.cdc.gov/healthy-swimming/safety/index.html",
    ),
    "cdc_pool_safety": KnowledgeSource(
        key="cdc_pool_safety",
        title="Guidelines for Keeping Your Pool Safe and Healthy",
        organization="U.S. Centers for Disease Control and Prevention",
        url=(
            "https://www.cdc.gov/healthy-swimming/safety/"
            "what-you-can-do-to-stay-healthy-in-swimming-pools.html"
        ),
    ),
}


ITEMS = (
    KnowledgeItem(
        key="freestyle_basics",
        category="영법",
        title="자유형 기본 자세·호흡",
        keywords=(
            "자유형", "크롤", "프론트 크롤", "캐치", "하이엘보", "팔꺾기",
            "자유형 호흡", "양측호흡", "롤링", "스트로크",
        ),
        facts=(
            "몸을 길게 뻗고 수면 가까이 수평을 유지하며, 교대 킥은 발목 힘을 빼고 이어간다.",
            "한 팔이 앞에 뻗어 있을 때 몸통 회전과 함께 머리를 옆으로 돌려 들이마시고, 물속에서는 계속 내쉰다.",
            "호흡 때문에 고개를 들어 올리면 하체가 가라앉기 쉬우므로 한쪽 귀가 물에 남는 정도의 회전을 우선 점검한다.",
            "교정은 짧은 구간에서 자세가 유지되는 횟수부터 늘리고, 통증이 생기면 동작을 중단한다.",
        ),
        source_keys=("swim_england_strokes",),
        internal_links=(("자유형 드릴 가이드", "/drill"),),
    ),
    KnowledgeItem(
        key="backstroke_basics",
        category="영법",
        title="배영 기본 자세·회전",
        keywords=(
            "배영", "백스트로크", "배영 롤링", "배영 킥", "배영 팔", "새끼손가락",
        ),
        facts=(
            "귀가 물에 잠길 정도로 머리를 안정시키고 시선은 위쪽을 향해 몸을 길게 유지한다.",
            "교대 킥은 무릎이 수면 밖으로 크게 나오지 않게 하고 발끝이 작은 물보라를 만드는 범위에서 이어간다.",
            "팔은 회복 후 새끼손가락 쪽부터 입수하고, 몸통 회전과 연결해 허벅지 방향으로 물을 민다.",
            "좌우 흔들림이 크면 팔 속도보다 머리 고정과 몸통 회전 범위를 먼저 점검한다.",
        ),
        source_keys=("swim_england_strokes",),
        internal_links=(("배영 드릴 가이드", "/drill"),),
    ),
    KnowledgeItem(
        key="breaststroke_basics",
        category="영법",
        title="평영 타이밍·킥",
        keywords=(
            "평영", "브레스트스트로크", "평영 킥", "웨지킥", "개구리킥",
            "평영 타이밍", "풀 브레스 킥 글라이드",
        ),
        facts=(
            "팔 당기기와 호흡 뒤에 킥을 연결하고, 팔과 다리가 길게 모인 유선형 구간을 만든다.",
            "발을 엉덩이 쪽으로 가져온 뒤 발목을 바깥쪽으로 세우고, 뒤쪽으로 차며 두 발을 모은다.",
            "기본 리듬은 '당기기-호흡-차기-미끄러지기'이며 팔과 다리를 동시에 크게 접지 않는다.",
            "무릎 안쪽 통증이 있으면 킥 각도나 강도를 억지로 반복하지 말고 전문가에게 확인한다.",
        ),
        source_keys=("swim_england_strokes",),
        internal_links=(("평영 드릴 가이드", "/drill"),),
    ),
    KnowledgeItem(
        key="butterfly_basics",
        category="영법",
        title="접영 웨이브·돌핀킥",
        keywords=(
            "접영", "버터플라이", "돌핀킥", "접영 웨이브", "접영 호흡",
            "접영 팔", "두번 킥", "2비트 킥",
        ),
        facts=(
            "몸의 물결은 머리를 과도하게 흔드는 동작이 아니라 가슴과 몸통에서 발끝까지 이어지는 리듬으로 만든다.",
            "두 팔은 함께 입수·당기기·회복하며, 일반적인 기본 리듬은 한 팔 사이클에 두 번의 돌핀킥이다.",
            "호흡은 당기기 후반에 턱을 앞으로 보내 짧게 하고, 팔 회복 중 얼굴을 다시 물속으로 돌린다.",
            "초보자는 완성 동작을 오래 반복하기보다 바디 돌핀, 한 팔 접영, 짧은 구간을 나눠 연습한다.",
        ),
        source_keys=("swim_england_strokes",),
        internal_links=(("접영 드릴 가이드", "/drill"),),
    ),
    KnowledgeItem(
        key="training_cycle",
        category="훈련",
        title="사이클·인터벌 구성",
        keywords=(
            "사이클", "인터벌", "휴식", "턴어라운드", "출발 간격", "몇 초",
            "세트", "반복", "디센딩", "빌드업", "네거티브", "훈련표",
        ),
        facts=(
            "사이클은 한 반복의 수영 시간과 휴식을 합친 다음 출발 시각이다. 예: 50m를 45초에 수영하고 15초 쉬면 1분 사이클이다.",
            "기술 세트는 자세를 유지할 여유가 있어야 하고, 지구력 세트는 반복 간 페이스가 크게 무너지지 않는 범위에서 구성한다.",
            "사이클을 정할 때는 영법, 거리, 수영장 길이, 현재 기록, 세트 목적을 함께 봐야 한다.",
            "반복 후반에 동작이 무너지면 사이클을 늘리거나 반복 수를 줄여 품질을 먼저 회복한다.",
        ),
        source_keys=("swim_england_training",),
        internal_links=(("훈련 플랜", "/plan"), ("수영 용어집", "/glossary")),
    ),
    KnowledgeItem(
        key="pool_length",
        category="훈련",
        title="25m·50m 풀 차이",
        keywords=(
            "25m", "25미터", "50m", "50미터", "숏코스", "롱코스",
            "수영장 길이", "풀 길이", "코스 변환",
        ),
        facts=(
            "같은 총거리라도 25m 풀은 턴과 벽 차기가 더 많고, 50m 풀은 한 길이에서 영법과 페이스를 더 오래 유지해야 한다.",
            "기록과 사이클은 풀 길이를 분리해 비교해야 하며, 단순히 같은 초 단위로 복사하지 않는다.",
            "50m 풀로 옮길 때는 첫 시도에서 사이클에 여유를 두고, 실제 반복 기록으로 다시 조정한다.",
            "훈련표 변환 시 총거리뿐 아니라 반복 거리, 턴 목적, 휴식 목적이 유지되는지 함께 확인한다.",
        ),
        internal_links=(("25m·50m 플랜 선택", "/plan"),),
    ),
    KnowledgeItem(
        key="equipment",
        category="장비",
        title="수영 훈련 장비 활용",
        keywords=(
            "장비", "킥판", "풀부이", "핀", "숏핀", "롱핀", "패들",
            "스노클", "수영 용품", "오리발",
        ),
        facts=(
            "킥판은 킥에 집중할 때, 풀부이는 하체 부력을 보조해 팔 동작과 호흡에 집중할 때 사용한다.",
            "핀은 킥 리듬과 몸의 수평 자세를 익히는 데 도움이 되지만, 핀 없이 같은 자세를 재현하는 연습도 함께 필요하다.",
            "패들은 어깨 부하를 늘릴 수 있으므로 크기와 사용 거리를 보수적으로 시작하고 통증이 있으면 중단한다.",
            "장비는 목표 동작을 더 잘 느끼게 하는 보조 수단이며, 장비 자체가 훈련 목적이 되지 않게 한다.",
        ),
        source_keys=("swim_england_equipment",),
        internal_links=(("장비 가이드", "/equipment"),),
    ),
    KnowledgeItem(
        key="water_safety",
        category="안전",
        title="수영·수상 안전 기본",
        keywords=(
            "안전", "익수", "물에 빠", "구조", "라이프가드", "오픈워터",
            "바다 수영", "강 수영", "호수 수영", "버디",
        ),
        facts=(
            "지정된 수영 구역과 안전요원이 있는 장소를 우선하고, 혼자 수영하지 않는다.",
            "자연수역은 수온, 기상, 조류, 시야, 출입 지점을 입수 전에 확인하고 자신의 능력을 과대평가하지 않는다.",
            "위급 상황에서는 훈련을 계속하지 말고 안전요원과 지역 긴급구조 체계에 즉시 도움을 요청한다.",
            "어린이와 초보자는 물가에서 지속적이고 가까운 감독이 필요하다.",
        ),
        source_keys=("red_cross_safety", "cdc_healthy_swimming"),
    ),
    KnowledgeItem(
        key="breath_hold_safety",
        category="안전",
        title="잠영·호흡 참기 안전",
        keywords=(
            "잠영", "숨 참기", "호흡 참기", "저산소", "하이폭식", "과호흡",
            "언더워터", "돌핀 잠영",
        ),
        facts=(
            "경쟁적으로 오래 숨을 참거나 반복해서 장시간 잠영하는 훈련은 피한다.",
            "과호흡 후 잠영은 의식 소실 위험을 알아차리기 어렵게 만들 수 있으므로 하지 않는다.",
            "잠영 훈련은 감독 가능한 환경과 명확한 안전 규칙 안에서 짧고 통제된 방식으로 수행한다.",
        ),
        source_keys=("red_cross_general_safety",),
    ),
    KnowledgeItem(
        key="pool_health",
        category="안전",
        title="수영장 위생·건강",
        keywords=(
            "수영장 물", "염소", "위생", "설사", "눈 따가", "귀", "샤워",
            "수영장 건강", "감염", "수영자 귀",
        ),
        facts=(
            "설사 증상이 있으면 수영장에 들어가지 않고, 입수 전에는 몸의 오염물을 씻어낸다.",
            "수영장 물을 삼키지 않고, 수영 후에는 귀의 물기를 부드럽게 말린다.",
            "눈·피부 자극이나 호흡 불편이 지속되면 물에서 나와 시설 관리자 또는 의료 전문가에게 확인한다.",
        ),
        source_keys=("cdc_pool_safety",),
    ),
    KnowledgeItem(
        key="competition_rules",
        category="규정",
        title="경영 경기 규정 확인",
        keywords=(
            "규정", "실격", "대회", "경기", "스타트", "출발", "턴 규칙",
            "터치 규정", "잠영 거리", "영법 순서", "world aquatics", "FINA",
        ),
        facts=(
            "영법별 출발, 턴, 터치, 수중 동작과 혼영 순서는 경기 규정의 적용을 받는다.",
            "대회 요강과 주최 단체의 적용 규정을 함께 확인해야 하며, 연령·종목·대회에 따라 별도 조건이 있을 수 있다.",
            "정확한 실격 판단은 최신 World Aquatics 규정과 해당 대회 요강을 기준으로 심판 또는 주최 측에 확인한다.",
        ),
        source_keys=("world_aquatics_rules",),
        current_verification_required=True,
    ),
    KnowledgeItem(
        key="pain_recovery_boundary",
        category="회복",
        title="통증·회복 질문의 안전 경계",
        keywords=(
            "통증", "아파", "부상", "어깨", "무릎", "허리", "쥐", "경련",
            "회복", "재활", "진단", "치료",
        ),
        facts=(
            "AI 답변은 일반적인 훈련 정보이며 질환이나 부상을 진단하지 않는다.",
            "날카로운 통증, 힘 빠짐, 어지럼, 흉통, 호흡 곤란이 있으면 훈련을 중단하고 적절한 의료 도움을 받는다.",
            "회복 훈련은 통증을 참고 수행하는 세션이 아니며, 증상이 지속되면 전문가의 평가를 우선한다.",
        ),
        source_keys=("cdc_healthy_swimming",),
        internal_links=(("부상 예방 가이드", "/injury"),),
    ),
)


def _normalize(value: str) -> str:
    return " ".join((value or "").lower().replace("_", " ").split())


def retrieve_knowledge(query: str, limit: int = 3) -> list[KnowledgeItem]:
    """Return the most relevant reviewed items using deterministic keyword scoring."""
    normalized = _normalize(query)
    if not normalized:
        return []

    scored: list[tuple[float, int, KnowledgeItem]] = []
    for index, item in enumerate(ITEMS):
        score = 0.0
        for keyword in item.keywords:
            term = _normalize(keyword)
            if term and term in normalized:
                score += 2.0 + min(len(term), 8) / 8
        if _normalize(item.title) in normalized:
            score += 4
        if score > 0:
            scored.append((score, -index, item))

    scored.sort(key=lambda row: (row[0], row[1]), reverse=True)
    return [row[2] for row in scored[: max(1, min(limit, 5))]]


def build_knowledge_context(items: Iterable[KnowledgeItem]) -> str:
    selected = list(items)
    if not selected:
        return ""

    blocks = [
        "\n\n[검수된 수영 지식베이스]",
        "아래 내용은 답변의 근거로만 사용하세요. 제공되지 않은 출처나 최신 확인 결과를 지어내지 마세요.",
    ]
    for item in selected:
        blocks.append(f"\n- 주제: {item.title} ({item.category})")
        blocks.extend(f"  · {fact}" for fact in item.facts)
        if item.current_verification_required:
            blocks.append(
                "  · 최신 확인 필요: 규정은 변경될 수 있으므로 기준 버전을 밝히고 공식 원문 확인을 안내하세요."
            )
        for source_key in item.source_keys:
            source = SOURCES[source_key]
            blocks.append(
                f"  · 출처: {source.organization} — {source.title} "
                f"({source.url}, 검수일 {source.verified_on})"
            )
    return "\n".join(blocks)


def grounding_payload(items: Iterable[KnowledgeItem]) -> dict:
    selected = list(items)
    source_keys: list[str] = []
    links: list[dict] = []
    seen_links: set[str] = set()

    for item in selected:
        for source_key in item.source_keys:
            if source_key not in source_keys:
                source_keys.append(source_key)
        for label, url in item.internal_links:
            if url not in seen_links:
                links.append({"title": label, "url": url, "kind": "guide"})
                seen_links.add(url)

    sources = []
    for source_key in source_keys:
        source = SOURCES[source_key]
        sources.append({
            "title": source.title,
            "organization": source.organization,
            "url": source.url,
            "verified_on": source.verified_on,
            "kind": "official",
        })

    return {
        "knowledge_version": KNOWLEDGE_VERSION,
        "topics": [
            {
                "key": item.key,
                "title": item.title,
                "category": item.category,
                "current_verification_required": item.current_verification_required,
            }
            for item in selected
        ],
        "sources": sources,
        "related_links": links,
    }
