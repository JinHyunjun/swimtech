#!/usr/bin/env python3
"""Validate credentials required by the unattended production QA gate."""

from __future__ import annotations

import os
import sys


REQUIRED_CREDENTIALS = (
    "QA_USERNAME",
    "QA_PASSWORD",
    "QA_EMAIL",
    "QA_STUDENT_USERNAME",
    "QA_STUDENT_PASSWORD",
    "QA_STUDENT_EMAIL",
    "ADMIN_ID",
    "ADMIN_PW",
)


def missing_credentials() -> list[str]:
    return [name for name in REQUIRED_CREDENTIALS if not os.getenv(name, "").strip()]


def main() -> int:
    missing = missing_credentials()
    if missing:
        names = ", ".join(missing)
        print(f"::error title=QA credentials missing::Configure GitHub Actions secrets: {names}")
        return 2

    print("QA credentials are configured for user, student, and administrator roles.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
