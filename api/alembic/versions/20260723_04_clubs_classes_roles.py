"""Add club, class, and scoped membership roles.

Revision ID: 20260723_04
Revises: 20260723_03
Create Date: 2026-07-23
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260723_04"
down_revision: Union[str, None] = "20260723_03"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "swim_clubs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "owner_coach_id",
            sa.Integer(),
            sa.ForeignKey("coaches.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("default_pool_length", sa.SmallInteger(), nullable=False, server_default="25"),
        sa.Column("invite_code", sa.String(length=20), nullable=False, unique=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.CheckConstraint("default_pool_length IN (25, 50)", name="ck_swim_clubs_pool_length"),
        sa.CheckConstraint("status IN ('active', 'archived')", name="ck_swim_clubs_status"),
    )
    op.create_index("ix_swim_clubs_owner", "swim_clubs", ["owner_coach_id", "status"])

    op.create_table(
        "swim_club_members",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "club_id",
            sa.Integer(),
            sa.ForeignKey("swim_clubs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "customer_id",
            sa.Integer(),
            sa.ForeignKey("customers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(length=20), nullable=False, server_default="member"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.CheckConstraint("role IN ('owner', 'coach', 'assistant', 'member')", name="ck_swim_club_members_role"),
        sa.CheckConstraint("status IN ('active', 'inactive')", name="ck_swim_club_members_status"),
        sa.UniqueConstraint("club_id", "customer_id", name="uq_swim_club_member"),
    )
    op.create_index("ix_swim_club_members_customer", "swim_club_members", ["customer_id", "status"])

    op.create_table(
        "swim_classes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "club_id",
            sa.Integer(),
            sa.ForeignKey("swim_clubs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "lead_coach_customer_id",
            sa.Integer(),
            sa.ForeignKey("customers.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("level", sa.String(length=30), nullable=False, server_default="혼합"),
        sa.Column("goal", sa.String(length=80), nullable=True),
        sa.Column("pool_length", sa.SmallInteger(), nullable=False, server_default="25"),
        sa.Column("max_members", sa.SmallInteger(), nullable=False, server_default="30"),
        sa.Column("invite_code", sa.String(length=20), nullable=False, unique=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.CheckConstraint("pool_length IN (25, 50)", name="ck_swim_classes_pool_length"),
        sa.CheckConstraint("max_members BETWEEN 1 AND 500", name="ck_swim_classes_max_members"),
        sa.CheckConstraint("status IN ('active', 'archived')", name="ck_swim_classes_status"),
    )
    op.create_index("ix_swim_classes_club", "swim_classes", ["club_id", "status"])

    op.create_table(
        "swim_class_members",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "class_id",
            sa.Integer(),
            sa.ForeignKey("swim_classes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "customer_id",
            sa.Integer(),
            sa.ForeignKey("customers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(length=20), nullable=False, server_default="student"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.CheckConstraint("role IN ('coach', 'assistant', 'student')", name="ck_swim_class_members_role"),
        sa.CheckConstraint("status IN ('active', 'inactive')", name="ck_swim_class_members_status"),
        sa.UniqueConstraint("class_id", "customer_id", name="uq_swim_class_member"),
    )
    op.create_index("ix_swim_class_members_customer", "swim_class_members", ["customer_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_swim_class_members_customer", table_name="swim_class_members")
    op.drop_table("swim_class_members")
    op.drop_index("ix_swim_classes_club", table_name="swim_classes")
    op.drop_table("swim_classes")
    op.drop_index("ix_swim_club_members_customer", table_name="swim_club_members")
    op.drop_table("swim_club_members")
    op.drop_index("ix_swim_clubs_owner", table_name="swim_clubs")
    op.drop_table("swim_clubs")
