"""Add class schedules, attendance, notices, and notice reads.

Revision ID: 20260723_05
Revises: 20260723_04
Create Date: 2026-07-23
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260723_05"
down_revision: Union[str, None] = "20260723_04"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "swim_class_sessions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("class_id", sa.Integer(), sa.ForeignKey("swim_classes.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "created_by_customer_id",
            sa.Integer(),
            sa.ForeignKey("customers.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("title", sa.String(length=100), nullable=False),
        sa.Column("session_date", sa.Date(), nullable=False),
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("end_time", sa.Time(), nullable=True),
        sa.Column("location", sa.String(length=120), nullable=True),
        sa.Column("lane_count", sa.SmallInteger(), nullable=False, server_default="1"),
        sa.Column("training_focus", sa.String(length=200), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="scheduled"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.CheckConstraint("lane_count BETWEEN 1 AND 50", name="ck_swim_class_sessions_lane_count"),
        sa.CheckConstraint("status IN ('scheduled', 'completed', 'cancelled')", name="ck_swim_class_sessions_status"),
        sa.UniqueConstraint("class_id", "session_date", "start_time", name="uq_swim_class_session_slot"),
    )
    op.create_index(
        "ix_swim_class_sessions_schedule",
        "swim_class_sessions",
        ["class_id", "session_date", "status"],
    )

    op.create_table(
        "swim_class_attendance",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "session_id",
            sa.Integer(),
            sa.ForeignKey("swim_class_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("note", sa.String(length=300), nullable=True),
        sa.Column(
            "checked_by_customer_id",
            sa.Integer(),
            sa.ForeignKey("customers.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.CheckConstraint("status IN ('present', 'late', 'absent', 'excused')", name="ck_swim_class_attendance_status"),
        sa.UniqueConstraint("session_id", "customer_id", name="uq_swim_class_attendance_member"),
    )
    op.create_index(
        "ix_swim_class_attendance_customer",
        "swim_class_attendance",
        ["customer_id", "checked_at"],
    )

    op.create_table(
        "swim_class_notices",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("club_id", sa.Integer(), sa.ForeignKey("swim_clubs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("class_id", sa.Integer(), sa.ForeignKey("swim_classes.id", ondelete="CASCADE"), nullable=True),
        sa.Column(
            "author_customer_id",
            sa.Integer(),
            sa.ForeignKey("customers.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("title", sa.String(length=100), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("is_pinned", sa.Boolean(), nullable=False, server_default=sa.text("FALSE")),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.CheckConstraint("status IN ('active', 'archived')", name="ck_swim_class_notices_status"),
    )
    op.create_index(
        "ix_swim_class_notices_scope",
        "swim_class_notices",
        ["club_id", "class_id", "status", "published_at"],
    )

    op.create_table(
        "swim_class_notice_reads",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "notice_id",
            sa.Integer(),
            sa.ForeignKey("swim_class_notices.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.UniqueConstraint("notice_id", "customer_id", name="uq_swim_class_notice_read"),
    )
    op.create_index(
        "ix_swim_class_notice_reads_customer",
        "swim_class_notice_reads",
        ["customer_id", "read_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_swim_class_notice_reads_customer", table_name="swim_class_notice_reads")
    op.drop_table("swim_class_notice_reads")
    op.drop_index("ix_swim_class_notices_scope", table_name="swim_class_notices")
    op.drop_table("swim_class_notices")
    op.drop_index("ix_swim_class_attendance_customer", table_name="swim_class_attendance")
    op.drop_table("swim_class_attendance")
    op.drop_index("ix_swim_class_sessions_schedule", table_name="swim_class_sessions")
    op.drop_table("swim_class_sessions")
