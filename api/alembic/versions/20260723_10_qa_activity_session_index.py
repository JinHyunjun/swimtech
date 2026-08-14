"""Index activity sessions used to separate anonymous QA traffic.

Revision ID: 20260723_10
Revises: 20260723_09
Create Date: 2026-08-14
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260723_10"
down_revision: Union[str, None] = "20260723_09"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_activity_qa_session_anchor",
        "user_activity_logs",
        ["ip_address", "user_agent", "created_at", "customer_id"],
        postgresql_where=sa.text(
            "customer_id IS NOT NULL AND ip_address IS NOT NULL AND user_agent IS NOT NULL"
        ),
    )


def downgrade() -> None:
    op.drop_index("ix_activity_qa_session_anchor", table_name="user_activity_logs")
