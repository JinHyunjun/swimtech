"""Add account session revision and password-change audit time.

Revision ID: 20260723_07
Revises: 20260723_06
Create Date: 2026-07-23
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260723_07"
down_revision: Union[str, None] = "20260723_06"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "customers",
        sa.Column("auth_version", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "customers",
        sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_customers_auth_version_nonnegative",
        "customers",
        "auth_version >= 0",
    )


def downgrade() -> None:
    op.drop_constraint("ck_customers_auth_version_nonnegative", "customers", type_="check")
    op.drop_column("customers", "password_changed_at")
    op.drop_column("customers", "auth_version")
