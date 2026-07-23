"""Store structured set-level execution data for training logs.

Revision ID: 20260723_03
Revises: 20260723_02
Create Date: 2026-07-23
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260723_03"
down_revision: Union[str, None] = "20260723_02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "training_log_sets",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "training_log_id",
            sa.Integer(),
            sa.ForeignKey("training_logs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "customer_id",
            sa.Integer(),
            sa.ForeignKey("customers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("set_order", sa.SmallInteger(), nullable=False),
        sa.Column("phase", sa.String(length=20), nullable=False, server_default="main"),
        sa.Column("stroke_type", sa.String(length=20), nullable=True),
        sa.Column("description", sa.String(length=200), nullable=False),
        sa.Column("target_reps", sa.SmallInteger(), nullable=False, server_default="1"),
        sa.Column("target_distance_m", sa.Integer(), nullable=False),
        sa.Column("target_cycle_seconds", sa.Integer(), nullable=True),
        sa.Column("completed_reps", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("completed_distance_m", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("actual_cycle_seconds", sa.Integer(), nullable=True),
        sa.Column("rpe", sa.SmallInteger(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("notes", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.CheckConstraint("set_order >= 0", name="ck_training_log_sets_order"),
        sa.CheckConstraint(
            "phase IN ('warmup', 'drill', 'main', 'cooldown', 'other')",
            name="ck_training_log_sets_phase",
        ),
        sa.CheckConstraint("target_reps BETWEEN 1 AND 200", name="ck_training_log_sets_target_reps"),
        sa.CheckConstraint(
            "target_distance_m BETWEEN 1 AND 50000",
            name="ck_training_log_sets_target_distance",
        ),
        sa.CheckConstraint(
            "target_cycle_seconds IS NULL OR target_cycle_seconds BETWEEN 1 AND 7200",
            name="ck_training_log_sets_target_cycle",
        ),
        sa.CheckConstraint(
            "completed_reps BETWEEN 0 AND 300",
            name="ck_training_log_sets_completed_reps",
        ),
        sa.CheckConstraint(
            "completed_distance_m BETWEEN 0 AND 200000",
            name="ck_training_log_sets_completed_distance",
        ),
        sa.CheckConstraint(
            "actual_cycle_seconds IS NULL OR actual_cycle_seconds BETWEEN 1 AND 7200",
            name="ck_training_log_sets_actual_cycle",
        ),
        sa.CheckConstraint("rpe IS NULL OR rpe BETWEEN 1 AND 10", name="ck_training_log_sets_rpe"),
        sa.CheckConstraint(
            "status IN ('pending', 'completed', 'skipped', 'modified')",
            name="ck_training_log_sets_status",
        ),
        sa.UniqueConstraint("training_log_id", "set_order", name="uq_training_log_sets_order"),
    )
    op.create_index(
        "ix_training_log_sets_customer",
        "training_log_sets",
        ["customer_id", "training_log_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_training_log_sets_customer", table_name="training_log_sets")
    op.drop_table("training_log_sets")
