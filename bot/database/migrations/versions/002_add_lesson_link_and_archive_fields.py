"""Add lesson_id and archive fields to homework

Revision ID: 002
Revises: 001
Create Date: 2025-01-18 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '002'
down_revision: Union[str, None] = '001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add new columns to homeworks table
    op.add_column('homeworks', sa.Column('lesson_id', sa.Integer(), nullable=True))
    op.add_column('homeworks', sa.Column('is_archived', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('homeworks', sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True))

    # Add foreign key constraint
    op.create_foreign_key('fk_homework_lesson', 'homeworks', 'schedule_lessons', ['lesson_id'], ['id'], ondelete='SET NULL')

    # Add indexes
    op.create_index('ix_homeworks_lesson_id', 'homeworks', ['lesson_id'])
    op.create_index('ix_homeworks_is_archived', 'homeworks', ['is_archived'])


def downgrade() -> None:
    # Remove indexes
    op.drop_index('ix_homeworks_is_archived', 'homeworks')
    op.drop_index('ix_homeworks_lesson_id', 'homeworks')

    # Remove foreign key constraint
    op.drop_constraint('fk_homework_lesson', 'homeworks', type_='foreignkey')

    # Remove columns
    op.drop_column('homeworks', 'archived_at')
    op.drop_column('homeworks', 'is_archived')
    op.drop_column('homeworks', 'lesson_id')
