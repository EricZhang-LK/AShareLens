"""Persist the exact simulation execution configuration.

Revision ID: 20260730_0006
Revises: 20260729_0005
Create Date: 2026-07-30
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260730_0006"
down_revision: str | None = "20260729_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add immutable portfolio and fill assumptions to every simulation run."""

    with op.batch_alter_table("simulation_runs") as batch:
        batch.add_column(sa.Column("execution_config", sa.JSON(), nullable=True))
    runs = sa.table(
        "simulation_runs",
        sa.column("execution_config", sa.JSON()),
    )
    op.execute(runs.update().values(execution_config={}))
    with op.batch_alter_table("simulation_runs") as batch:
        batch.alter_column(
            "execution_config",
            existing_type=sa.JSON(),
            nullable=False,
        )


def downgrade() -> None:
    """Remove execution configuration from disposable databases."""

    with op.batch_alter_table("simulation_runs") as batch:
        batch.drop_column("execution_config")
