"""recover missing revision marker

Revision ID: f8ca064707b6
Revises: efa47bce62c0
Create Date: 2026-04-02 14:00:00.000000

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = 'f8ca064707b6'
down_revision = 'efa47bce62c0'
branch_labels = None
depends_on = None


def upgrade():
    # This revision file restores a missing migration marker.
    # No schema change is executed.
    pass


def downgrade():
    pass
