"""Add revocable result shares and public club promotion campaigns.

Revision ID: 20260723_09
Revises: 20260723_08
Create Date: 2026-08-12
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260723_09"
down_revision: Union[str, None] = "20260723_08"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "swim_club_members",
        sa.Column(
            "promotion_distance_opt_in",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_table(
        "promotion_result_shares",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "customer_id",
            sa.Integer(),
            sa.ForeignKey("customers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token", sa.String(length=64), nullable=False, unique=True),
        sa.Column("share_type", sa.String(length=20), nullable=False, server_default="monthly"),
        sa.Column("period_year", sa.SmallInteger(), nullable=False),
        sa.Column("period_month", sa.SmallInteger(), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("display_name", sa.String(length=80), nullable=True),
        sa.Column("show_nickname", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("view_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_viewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW() + INTERVAL '180 days'"),
        ),
        sa.CheckConstraint("share_type IN ('monthly')", name="ck_promotion_result_share_type"),
        sa.CheckConstraint("period_month BETWEEN 1 AND 12", name="ck_promotion_result_share_month"),
        sa.CheckConstraint("status IN ('active', 'revoked')", name="ck_promotion_result_share_status"),
    )
    op.create_index(
        "ix_promotion_result_shares_owner",
        "promotion_result_shares",
        ["customer_id", "status", "created_at"],
    )

    op.create_table(
        "club_promotion_campaigns",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "club_id",
            sa.Integer(),
            sa.ForeignKey("swim_clubs.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "class_id",
            sa.Integer(),
            sa.ForeignKey("swim_classes.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("public_token", sa.String(length=64), nullable=False, unique=True),
        sa.Column("headline", sa.String(length=120), nullable=False),
        sa.Column("target_distance", sa.Integer(), nullable=False, server_default="100000"),
        sa.Column("start_date", sa.Date(), nullable=False, server_default=sa.text("CURRENT_DATE")),
        sa.Column("end_date", sa.Date(), nullable=False, server_default=sa.text("(CURRENT_DATE + 30)")),
        sa.Column("is_public", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("show_member_count", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("view_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_viewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.CheckConstraint("target_distance BETWEEN 1000 AND 100000000", name="ck_club_campaign_target"),
        sa.CheckConstraint("end_date >= start_date", name="ck_club_campaign_dates"),
    )
    op.create_index("ix_club_campaigns_public", "club_promotion_campaigns", ["is_public", "updated_at"])


def downgrade() -> None:
    op.drop_index("ix_club_campaigns_public", table_name="club_promotion_campaigns")
    op.drop_table("club_promotion_campaigns")
    op.drop_index("ix_promotion_result_shares_owner", table_name="promotion_result_shares")
    op.drop_table("promotion_result_shares")
    op.drop_column("swim_club_members", "promotion_distance_opt_in")
