"""Register the schema already deployed before Alembic adoption.

Revision ID: 20260723_01
Revises: None
Create Date: 2026-07-23

The production schema was historically built by db/init.sql and idempotent
route/startup DDL. This baseline intentionally changes no application tables;
it records that deployed state in alembic_version so every subsequent schema
change can be explicit, ordered, and reviewable.
"""

from typing import Sequence, Union


revision: str = "20260723_01"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    # A baseline stamp has no application-schema operation to reverse.
    pass
