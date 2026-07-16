"""add checkin_no_spam, ask_auto_rollover, auto_rollover; nullable start_time

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-07-16 15:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, Sequence[str], None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add anti-spam / rollover settings and allow untimed tasks."""
    op.add_column(
        "users",
        sa.Column(
            "checkin_no_spam",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "ask_auto_rollover",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "tasks",
        sa.Column(
            "auto_rollover",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.alter_column(
        "tasks",
        "start_time",
        existing_type=sa.Time(),
        nullable=True,
    )


def downgrade() -> None:
    """Revert anti-spam / rollover settings and restore required start_time."""
    # Untimed tasks cannot be restored to NOT NULL without a placeholder time.
    op.execute("UPDATE tasks SET start_time = '00:00:00' WHERE start_time IS NULL")
    op.alter_column(
        "tasks",
        "start_time",
        existing_type=sa.Time(),
        nullable=False,
    )
    op.drop_column("tasks", "auto_rollover")
    op.drop_column("users", "ask_auto_rollover")
    op.drop_column("users", "checkin_no_spam")
