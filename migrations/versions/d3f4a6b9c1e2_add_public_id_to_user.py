"""add public id to user

Revision ID: d3f4a6b9c1e2
Revises: 9b2c7d1a4f55
Create Date: 2026-04-02 13:10:00.000000

"""
from alembic import op
import sqlalchemy as sa
import secrets
import string


# revision identifiers, used by Alembic.
revision = 'd3f4a6b9c1e2'
down_revision = '9b2c7d1a4f55'
branch_labels = None
depends_on = None


def _generate_unique_public_id(existing_values, length=10):
    charset = string.ascii_letters + string.digits
    while True:
        value = ''.join(secrets.choice(charset) for _ in range(length))
        if value not in existing_values:
            existing_values.add(value)
            return value


def upgrade():
    op.add_column('user', sa.Column('public_id', sa.String(length=10), nullable=True))

    bind = op.get_bind()
    user_table = sa.table(
        'user',
        sa.column('id', sa.Integer()),
        sa.column('public_id', sa.String(length=10)),
    )

    existing_values = {
        row[0]
        for row in bind.execute(
            sa.select(user_table.c.public_id).where(user_table.c.public_id.isnot(None))
        ).fetchall()
        if row[0]
    }

    users_to_fill = bind.execute(
        sa.select(user_table.c.id).where(user_table.c.public_id.is_(None))
    ).fetchall()

    for row in users_to_fill:
        public_id = _generate_unique_public_id(existing_values)
        bind.execute(
            user_table.update().where(user_table.c.id == row[0]).values(public_id=public_id)
        )

    op.create_unique_constraint('uq_user_public_id', 'user', ['public_id'])
    op.create_index('ix_user_public_id', 'user', ['public_id'], unique=False)
    op.alter_column('user', 'public_id', existing_type=sa.String(length=10), nullable=False)


def downgrade():
    op.drop_index('ix_user_public_id', table_name='user')
    op.drop_constraint('uq_user_public_id', 'user', type_='unique')
    op.drop_column('user', 'public_id')
