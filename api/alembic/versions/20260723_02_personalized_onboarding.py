"""Add persisted preferences for personalized onboarding.

Revision ID: 20260723_02
Revises: 20260723_01
Create Date: 2026-07-23
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260723_02"
down_revision: Union[str, None] = "20260723_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "customers",
        sa.Column("preferred_pool_length", sa.SmallInteger(), nullable=False, server_default="25"),
    )
    op.add_column(
        "customers",
        sa.Column("onboarding_completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_customers_preferred_pool_length",
        "customers",
        "preferred_pool_length IN (25, 50)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_customers_preferred_pool_length", "customers", type_="check")
    op.drop_column("customers", "onboarding_completed_at")
    op.drop_column("customers", "preferred_pool_length")
