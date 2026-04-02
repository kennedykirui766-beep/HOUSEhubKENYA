"""expand public id length

Revision ID: f7a8c1d4e2b0
Revises: d3f4a6b9c1e2
Create Date: 2026-04-02 13:35:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f7a8c1d4e2b0'
down_revision = 'd3f4a6b9c1e2'
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column('user', 'public_id', existing_type=sa.String(length=10), type_=sa.String(length=32), existing_nullable=False)


def downgrade():
    op.alter_column('user', 'public_id', existing_type=sa.String(length=32), type_=sa.String(length=10), existing_nullable=False)
