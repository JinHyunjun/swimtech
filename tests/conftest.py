"""pytest-playwright 전역 설정."""
import pytest

# ── 고정 테스트 계정 (db/test_accounts.sql 로 사전 생성) ──────────────────
COACH_ID = "coach_test"
COACH_PW = "TestCoach123!"
STUDENT_ID = "student_test"
STUDENT_PW = "TestStudent123!"


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "slow: marks tests as slow (deselect with -m 'not slow')"
    )
