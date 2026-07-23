"""Add timed swim test results and course-specific personal bests.

Revision ID: 20260723_06
Revises: 20260723_05
Create Date: 2026-07-23
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260723_06"
down_revision: Union[str, None] = "20260723_05"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "swim_test_results",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("training_log_id", sa.Integer(), sa.ForeignKey("training_logs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("test_date", sa.Date(), nullable=False),
        sa.Column("stroke_type", sa.String(length=20), nullable=False),
        sa.Column("distance_m", sa.Integer(), nullable=False),
        sa.Column("pool_length", sa.SmallInteger(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False, server_default="manual"),
        sa.Column("notes", sa.String(length=300), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.CheckConstraint("stroke_type IN ('자유형','배영','평영','접영','혼영')", name="ck_swim_test_results_stroke"),
        sa.CheckConstraint("distance_m BETWEEN 25 AND 5000", name="ck_swim_test_results_distance"),
        sa.CheckConstraint("pool_length IN (25, 50)", name="ck_swim_test_results_pool"),
        sa.CheckConstraint("distance_m % pool_length = 0", name="ck_swim_test_results_course_distance"),
        sa.CheckConstraint("duration_ms BETWEEN 1000 AND 86400000", name="ck_swim_test_results_duration"),
        sa.CheckConstraint("source IN ('manual','training_log')", name="ck_swim_test_results_source"),
    )
    op.create_index(
        "ix_swim_test_results_history",
        "swim_test_results",
        ["customer_id", "test_date"],
    )
    op.create_index(
        "ix_swim_test_results_pb",
        "swim_test_results",
        ["customer_id", "pool_length", "stroke_type", "distance_m", "duration_ms"],
    )


def downgrade() -> None:
    op.drop_index("ix_swim_test_results_pb", table_name="swim_test_results")
    op.drop_index("ix_swim_test_results_history", table_name="swim_test_results")
    op.drop_table("swim_test_results")
