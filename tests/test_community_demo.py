"""Demo conversations must never masquerade as real community activity."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]


def test_demo_is_explicit_isolated_and_read_only():
    page=(ROOT/'frontend/community_demo.html').read_text(encoding='utf-8')
    script=(ROOT/'frontend/static/community-demo.js').read_text(encoding='utf-8')
    assert '실제 이용 후기나 회원 간 활동 이력이 아닙니다' in page
    assert '예시 날짜' in page and '2026-10-24' in page
    assert 'noindex,nofollow' in page
    assert '/community_demo' in (ROOT/'frontend/community.html').read_text(encoding='utf-8')
    assert 'fetch(' not in script and 'XMLHttpRequest' not in script
    assert 'localStorage' not in script
    assert 'textContent' in script and 'innerHTML' not in script
    assert script.count('[QA 데모]')==4
    assert script.count('category:')==6
    assert '예시 날짜 ${date}' in script
