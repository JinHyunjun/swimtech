"""Classify dedicated QA accounts separately from production users.

Revision ID: 20260723_08
Revises: 20260723_07
Create Date: 2026-08-09
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260723_08"
down_revision: Union[str, None] = "20260723_07"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "customers",
        sa.Column("is_qa_account", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index(
        "ix_customers_qa_account_true",
        "customers",
        ["is_qa_account"],
        postgresql_where=sa.text("is_qa_account IS TRUE"),
    )


def downgrade() -> None:
    op.drop_index("ix_customers_qa_account_true", table_name="customers")
    op.drop_column("customers", "is_qa_account")
