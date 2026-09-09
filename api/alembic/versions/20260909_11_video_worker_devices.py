"""Remember revocable analysis PCs, never video files or administrator passwords."""
from alembic import op
import sqlalchemy as sa

revision: str = "20260909_11"
down_revision: str = "20260723_10"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('video_worker_devices',
        sa.Column('id', sa.String(32), primary_key=True),
        sa.Column('customer_id', sa.Integer(), sa.ForeignKey('customers.id', ondelete='CASCADE'), nullable=False),
        sa.Column('auth_version', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(80), nullable=False),
        sa.Column('secret_hash', sa.String(64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('last_used_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('revoked_at', sa.DateTime(timezone=True)))
    op.create_index('ix_video_worker_devices_owner', 'video_worker_devices', ['customer_id'])


def downgrade():
    op.drop_table('video_worker_devices')
