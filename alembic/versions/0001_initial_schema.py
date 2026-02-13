"""initial schema

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-02-13 00:00:00
"""

from __future__ import annotations

from alembic import op

from app.models.db_models import Base

# revision identifiers, used by Alembic.
revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
