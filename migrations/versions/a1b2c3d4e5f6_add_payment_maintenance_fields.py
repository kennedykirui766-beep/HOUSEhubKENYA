"""add payment and maintenance fields

Revision ID: a1b2c3d4e5f6
Revises: 9fa5cab23522
Create Date: 2026-04-17 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = '9fa5cab23522'
branch_labels = None
depends_on = None


def upgrade():
    # Add new columns to payment
    with op.batch_alter_table('payment', schema=None) as batch_op:
        batch_op.add_column(sa.Column('house_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('payment_month', sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column('payment_link', sa.String(length=500), nullable=True))
        batch_op.add_column(sa.Column('transaction_id', sa.String(length=200), nullable=True))
        batch_op.add_column(sa.Column('receipt_url', sa.String(length=500), nullable=True))
        batch_op.add_column(sa.Column('receipt_pdf_url', sa.String(length=500), nullable=True))
        batch_op.add_column(sa.Column('created_at', sa.DateTime(), nullable=True))
        # create FK to house if table exists
        try:
            batch_op.create_foreign_key('fk_payment_house', 'house', ['house_id'], ['id'])
        except Exception:
            # If creating FK fails (older DB layout), skip to avoid blocking upgrade
            pass

    # Add columns to maintenance_request
    with op.batch_alter_table('maintenance_request', schema=None) as batch_op:
        batch_op.add_column(sa.Column('attachments', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('sla_due', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('tenant_comments', sa.Text(), nullable=True))

    # Create maintenance_comment table
    op.create_table(
        'maintenance_comment',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('request_id', sa.Integer(), sa.ForeignKey('maintenance_request.id'), nullable=False),
        sa.Column('author_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=True),
        sa.Column('role', sa.String(length=50), nullable=True),
        sa.Column('comment', sa.Text(), nullable=False),
        sa.Column('attachments', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )


def downgrade():
    # Drop maintenance_comment
    op.drop_table('maintenance_comment')

    # Remove maintenance_request columns
    with op.batch_alter_table('maintenance_request', schema=None) as batch_op:
        batch_op.drop_column('tenant_comments')
        batch_op.drop_column('sla_due')
        batch_op.drop_column('attachments')

    # Remove payment columns
    with op.batch_alter_table('payment', schema=None) as batch_op:
        try:
            batch_op.drop_constraint('fk_payment_house', type_='foreignkey')
        except Exception:
            pass
        batch_op.drop_column('created_at')
        batch_op.drop_column('receipt_pdf_url')
        batch_op.drop_column('receipt_url')
        batch_op.drop_column('transaction_id')
        batch_op.drop_column('payment_link')
        batch_op.drop_column('payment_month')
        batch_op.drop_column('house_id')
