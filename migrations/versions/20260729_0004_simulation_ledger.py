"""Create paper simulation accounts and immutable ledgers.

Revision ID: 20260729_0004
Revises: 20260729_0003
Create Date: 2026-07-29
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20260729_0004"
down_revision: str | None = "20260729_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MYSQL_OPTIONS = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
}


def upgrade() -> None:
    """Create paper accounts, reproducible runs and normalized ledgers."""

    op.create_table(
        "simulation_accounts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("initial_cash", mysql.DECIMAL(precision=24, scale=4), nullable=False),
        sa.Column("current_state", sa.JSON(), nullable=False),
        sa.Column("state_hash", sa.String(length=64), nullable=False),
        sa.Column("last_session_date", sa.Date(), nullable=True),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("updated_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_simulation_account_name"),
        **MYSQL_OPTIONS,
    )
    op.create_table(
        "simulation_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("account_id", sa.String(length=36), nullable=False),
        sa.Column("session_date", sa.Date(), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("strategy_id", sa.String(length=128), nullable=False),
        sa.Column("strategy_version", sa.String(length=32), nullable=False),
        sa.Column("engine_version", sa.String(length=32), nullable=False),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("data_snapshot_id", sa.String(length=64), nullable=False),
        sa.Column("partition_ids", sa.JSON(), nullable=False),
        sa.Column("input_state", sa.JSON(), nullable=False),
        sa.Column("input_state_hash", sa.String(length=64), nullable=False),
        sa.Column("output_state", sa.JSON(), nullable=False),
        sa.Column("output_state_hash", sa.String(length=64), nullable=False),
        sa.Column("nav_cash", mysql.DECIMAL(precision=24, scale=4), nullable=False),
        sa.Column(
            "nav_market_value",
            mysql.DECIMAL(precision=24, scale=4),
            nullable=False,
        ),
        sa.Column(
            "nav_total_value",
            mysql.DECIMAL(precision=24, scale=4),
            nullable=False,
        ),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["simulation_accounts.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "account_id",
            "session_date",
            name="uq_simulation_run_account_date",
        ),
        **MYSQL_OPTIONS,
    )
    op.create_index(
        "ix_simulation_runs_account_id",
        "simulation_runs",
        ["account_id"],
        unique=False,
    )
    op.create_index(
        "ix_simulation_run_fingerprint",
        "simulation_runs",
        ["fingerprint"],
        unique=False,
    )
    op.create_table(
        "simulation_candidates",
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(length=16), nullable=False),
        sa.Column("signal_date", sa.Date(), nullable=False),
        sa.Column("selected", sa.Boolean(), nullable=False),
        sa.Column("score", mysql.DECIMAL(precision=20, scale=18), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=True),
        sa.Column("reasons", sa.JSON(), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("data_warnings", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["simulation_runs.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "run_id",
            "sequence",
            name="pk_simulation_candidate",
        ),
        sa.UniqueConstraint(
            "run_id",
            "symbol",
            name="uq_simulation_candidate_symbol",
        ),
        **MYSQL_OPTIONS,
    )
    op.create_table(
        "simulation_orders",
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(length=16), nullable=False),
        sa.Column("side", sa.String(length=8), nullable=False),
        sa.Column("quantity", sa.BigInteger(), nullable=False),
        sa.Column("signal_date", sa.Date(), nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["simulation_runs.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("run_id", "sequence", name="pk_simulation_order"),
        **MYSQL_OPTIONS,
    )
    op.create_table(
        "simulation_fills",
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(length=16), nullable=False),
        sa.Column("side", sa.String(length=8), nullable=False),
        sa.Column("quantity", sa.BigInteger(), nullable=False),
        sa.Column("price", mysql.DECIMAL(precision=18, scale=6), nullable=False),
        sa.Column("signal_date", sa.Date(), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("commission", mysql.DECIMAL(precision=18, scale=4), nullable=False),
        sa.Column(
            "transfer_fee",
            mysql.DECIMAL(precision=18, scale=4),
            nullable=False,
        ),
        sa.Column("stamp_duty", mysql.DECIMAL(precision=18, scale=4), nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["simulation_runs.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("run_id", "sequence", name="pk_simulation_fill"),
        **MYSQL_OPTIONS,
    )


def downgrade() -> None:
    """Remove paper-simulation persistence from a disposable database."""

    op.drop_table("simulation_fills")
    op.drop_table("simulation_orders")
    op.drop_table("simulation_candidates")
    op.drop_index("ix_simulation_run_fingerprint", table_name="simulation_runs")
    op.drop_index("ix_simulation_runs_account_id", table_name="simulation_runs")
    op.drop_table("simulation_runs")
    op.drop_table("simulation_accounts")
