"""add_reminder_time_and_check_interval_to_user

Revision ID: a1b2c3d4e5f6
Revises: 9f4d2b6c1e38
Create Date: 2026-07-08 17:28:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '9f4d2b6c1e38'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema — add reminder_time and check_interval to users table."""
    op.add_column(
        'users',
        sa.Column('reminder_time', sa.Time(), nullable=True),
    )
    op.add_column(
        'users',
        sa.Column(
            'check_interval',
            sa.Integer(),
            nullable=False,
            server_default=sa.text('15'),
        ),
    )


def downgrade() -> None:
    """Downgrade schema — remove reminder_time and check_interval from users table."""
    op.drop_column('users', 'check_interval')
    op.drop_column('users', 'reminder_time')