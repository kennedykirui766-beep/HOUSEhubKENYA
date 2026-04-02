"""add dashboard order to user

Revision ID: 9b2c7d1a4f55
Revises: efa47bce62c0
Create Date: 2026-04-02 12:40:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '9b2c7d1a4f55'
down_revision = 'f8ca064707b6'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('user', sa.Column('dashboard_order', sa.Text(), nullable=True))


def downgrade():
    op.drop_column('user', 'dashboard_order')
