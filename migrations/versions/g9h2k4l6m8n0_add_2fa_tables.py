"""Add TwoFactorCode and TwoFactorVerification models

Revision ID: g9h2k4l6m8n0
Revises: f7a8c1d4e2b0
Create Date: 2026-04-02 22:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'g9h2k4l6m8n0'
down_revision = 'f7a8c1d4e2b0'
branch_labels = None
depends_on = None


def upgrade():
    # Add preferred_2fa_method column to user table
    op.add_column('user', sa.Column('preferred_2fa_method', sa.String(20), nullable=True))
    
    # Create TwoFactorCode table
    op.create_table(
        'two_factor_code',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('code', sa.String(6), nullable=False),
        sa.Column('method', sa.String(20), nullable=False),
        sa.Column('is_used', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_two_factor_code_user_id', 'two_factor_code', ['user_id'])
    op.create_index('ix_two_factor_code_created_at', 'two_factor_code', ['created_at'])
    op.create_index('ix_two_factor_code_expires_at', 'two_factor_code', ['expires_at'])
    
    # Create TwoFactorVerification table
    op.create_table(
        'two_factor_verification',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('email_enabled', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('sms_enabled', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('totp_enabled', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('verified_phone', sa.String(20), nullable=True),
        sa.Column('phone_verified', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('backup_codes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id')
    )
    op.create_index('ix_two_factor_verification_user_id', 'two_factor_verification', ['user_id'])


def downgrade():
    # Drop indices
    op.drop_index('ix_two_factor_verification_user_id', 'two_factor_verification')
    op.drop_table('two_factor_verification')
    
    op.drop_index('ix_two_factor_code_expires_at', 'two_factor_code')
    op.drop_index('ix_two_factor_code_created_at', 'two_factor_code')
    op.drop_index('ix_two_factor_code_user_id', 'two_factor_code')
    op.drop_table('two_factor_code')
    
    # Remove preferred_2fa_method column
    op.drop_column('user', 'preferred_2fa_method')
