"""pytest-playwright 전역 설정."""
import pytest

# ── 메인 테스트 계정 (실제 DB의 kom1452 계정) ────────────────────────────
TEST_ID = "kom1452"
TEST_PW = "swimtech1234"

# ── 고정 테스트 계정 (db/test_accounts.sql 로 사전 생성) ──────────────────
COACH_ID = "coach_test"
COACH_PW = "TestCoach123!"
STUDENT_ID = "student_test"
STUDENT_PW = "TestStudent123!"


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "slow: marks tests as slow (deselect with -m 'not slow')"
    )
