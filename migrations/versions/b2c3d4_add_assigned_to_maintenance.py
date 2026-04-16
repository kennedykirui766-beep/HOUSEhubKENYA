"""add assigned_to to maintenance_request

Revision ID: b2c3d4_add_assigned_to
Revises: a1b2c3d4e5f6
Create Date: 2026-04-17 12:10:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b2c3d4_add_assigned_to'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('maintenance_request', schema=None) as batch_op:
        batch_op.add_column(sa.Column('assigned_to', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_maintenance_assigned_to_user', 'user', ['assigned_to'], ['id'])
        batch_op.add_column(sa.Column('priority', sa.String(length=20), nullable=True))


def downgrade():
    with op.batch_alter_table('maintenance_request', schema=None) as batch_op:
        try:
            batch_op.drop_constraint('fk_maintenance_assigned_to_user', type_='foreignkey')
        except Exception:
            pass
        batch_op.drop_column('priority')
        batch_op.drop_column('assigned_to')
