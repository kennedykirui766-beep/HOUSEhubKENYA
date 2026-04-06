"""add system_setting table

Revision ID: db6b735185e8
Revises: 97fc58f870fc
Create Date: 2026-04-05 23:19:06.496766

"""
from alembic import op
import sqlalchemy as sa
import secrets
import string


# revision identifiers, used by Alembic.
revision = 'db6b735185e8'
down_revision = '97fc58f870fc'
branch_labels = None
depends_on = None


def generate_public_id(length=12):
    chars = string.ascii_letters + string.digits
    return ''.join(secrets.choice(chars) for _ in range(length))


def upgrade():
    # --- BOOKING TABLE ---
    with op.batch_alter_table('booking', schema=None) as batch_op:
        batch_op.add_column(sa.Column('created_at', sa.DateTime(), nullable=True))
        batch_op.alter_column(
            'tenant_id',
            existing_type=sa.INTEGER(),
            nullable=False
        )
        batch_op.alter_column(
            'house_id',
            existing_type=sa.INTEGER(),
            nullable=False
        )

    # --- USER TABLE ---
    with op.batch_alter_table('user', schema=None) as batch_op:
        # Step 1: add as nullable first
        batch_op.add_column(sa.Column('public_id', sa.String(length=32), nullable=True))

        batch_op.add_column(sa.Column('business_name', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('bio', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('address', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('email_notifications', sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column('message_alerts', sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column('sms_2fa_enabled', sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column('email_2fa_enabled', sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column('preferred_2fa_method', sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column('dashboard_order', sa.Text(), nullable=True))

    # --- BACKFILL public_id (IMPORTANT) ---
    conn = op.get_bind()
    user_table = sa.table(
        'user',
        sa.column('id', sa.Integer),
        sa.column('public_id', sa.String)
    )

    users = conn.execute(sa.select(user_table.c.id)).fetchall()

    for user in users:
        conn.execute(
            user_table.update()
            .where(user_table.c.id == user.id)
            .values(public_id=generate_public_id())
        )

    # --- ENFORCE NOT NULL + INDEX ---
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.alter_column('public_id', nullable=False)
        batch_op.create_index(batch_op.f('ix_user_public_id'), ['public_id'], unique=True)


def downgrade():
    # --- USER TABLE ---
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_user_public_id'))

        batch_op.drop_column('dashboard_order')
        batch_op.drop_column('preferred_2fa_method')
        batch_op.drop_column('email_2fa_enabled')
        batch_op.drop_column('sms_2fa_enabled')
        batch_op.drop_column('message_alerts')
        batch_op.drop_column('email_notifications')
        batch_op.drop_column('address')
        batch_op.drop_column('bio')
        batch_op.drop_column('business_name')
        batch_op.drop_column('public_id')

    # --- BOOKING TABLE ---
    with op.batch_alter_table('booking', schema=None) as batch_op:
        batch_op.alter_column(
            'house_id',
            existing_type=sa.INTEGER(),
            nullable=True
        )
        batch_op.alter_column(
            'tenant_id',
            existing_type=sa.INTEGER(),
            nullable=True
        )
        batch_op.drop_column('created_at')