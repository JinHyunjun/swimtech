"""pytest-playwright 전역 설정.

계정 정보는 저장소에 두지 않고 환경변수 또는 GitHub Actions Secrets로만 전달한다.
"""
import os
import pytest

TEST_ID = os.getenv("QA_USERNAME", "")
TEST_PW = os.getenv("QA_PASSWORD", "")
COACH_ID = os.getenv("QA_USERNAME", "")
COACH_PW = os.getenv("QA_PASSWORD", "")
STUDENT_ID = os.getenv("QA_STUDENT_USERNAME", "")
STUDENT_PW = os.getenv("QA_STUDENT_PASSWORD", "")


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "slow: marks tests as slow (deselect with -m 'not slow')"
    )
