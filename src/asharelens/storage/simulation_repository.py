"""Persistence adapter for paper-account state and immutable daily ledgers."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from asharelens.core.engine import NavPoint, PortfolioState, Position, SessionOutcome
from asharelens.core.execution import Fill, Order, Side
from asharelens.core.models import SelectionCandidate
from asharelens.storage.models import (
    SimulationAccountRow,
    SimulationCandidateRow,
    SimulationFillRow,
    SimulationOrderRow,
    SimulationRunRow,
)


class SimulationAccountNotFound(LookupError):
    """Raised when a paper-account ID does not exist."""


class SimulationAccountNameConflict(ValueError):
    """Raised when an account name already belongs to another initial state."""


@dataclass(frozen=True, slots=True)
class SimulationAccountSnapshot:
    """Immutable paper-account state."""

    id: str
    name: str
    initial_cash: float
    state: PortfolioState
    state_hash: str
    last_session_date: date | None


@dataclass(frozen=True, slots=True)
class SimulationRunSnapshot:
    """One reproducible daily transition and its explainable ledgers."""

    id: str
    account_id: str
    session_date: date
    fingerprint: str
    strategy_id: str
    strategy_version: str
    engine_version: str
    parameters: dict[str, Any]
    data_snapshot_id: str
    partition_ids: tuple[str, ...]
    input_state: PortfolioState
    input_state_hash: str
    output_state: PortfolioState
    output_state_hash: str
    candidates: tuple[SelectionCandidate, ...]
    orders: tuple[Order, ...]
    fills: tuple[Fill, ...]
    nav: NavPoint


@dataclass(frozen=True, slots=True)
class SimulationRunInputs:
    """Reproduction metadata supplied by the workflow."""

    fingerprint: str
    strategy_id: str
    strategy_version: str
    engine_version: str
    parameters: dict[str, Any]
    data_snapshot_id: str
    partition_ids: tuple[str, ...]


class SimulationRepository:
    """Persist paper simulations without committing the caller's transaction."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create_account(
        self,
        *,
        name: str,
        initial_state: PortfolioState,
        now: datetime,
    ) -> SimulationAccountSnapshot:
        """Create an account idempotently by unique human-readable name."""

        if not name:
            raise ValueError("name must not be empty")
        payload = serialize_portfolio_state(initial_state)
        digest = hash_portfolio_state(initial_state)
        existing = self._session.scalar(
            select(SimulationAccountRow).where(SimulationAccountRow.name == name)
        )
        if existing is not None:
            if existing.state_hash != digest or existing.last_session_date is not None:
                raise SimulationAccountNameConflict(name)
            return _account_snapshot(existing)

        current = _naive_utc(now)
        row = SimulationAccountRow(
            id=str(uuid4()),
            name=name,
            initial_cash=Decimal(str(initial_state.cash)),
            current_state=payload,
            state_hash=digest,
            last_session_date=None,
            created_at=current,
            updated_at=current,
        )
        self._session.add(row)
        self._session.flush()
        return _account_snapshot(row)

    def get_account(
        self,
        account_id: str,
        *,
        for_update: bool = False,
    ) -> SimulationAccountSnapshot:
        """Load an account, optionally locking it for one state transition."""

        statement = select(SimulationAccountRow).where(
            SimulationAccountRow.id == account_id
        )
        if for_update:
            statement = statement.with_for_update().execution_options(
                populate_existing=True
            )
        row = self._session.scalar(statement)
        if row is None:
            raise SimulationAccountNotFound(account_id)
        return _account_snapshot(row)

    def get_run(
        self,
        account_id: str,
        session_date: date,
        *,
        for_update: bool = False,
    ) -> SimulationRunSnapshot | None:
        """Load the immutable result for one account and session."""

        statement = select(SimulationRunRow).where(
            SimulationRunRow.account_id == account_id,
            SimulationRunRow.session_date == session_date,
        )
        if for_update:
            statement = statement.with_for_update().execution_options(
                populate_existing=True
            )
        row = self._session.scalar(statement)
        if row is None:
            return None
        return self._run_snapshot(row)

    def advance(
        self,
        *,
        account_id: str,
        session_date: date,
        input_state: PortfolioState,
        outcome: SessionOutcome,
        inputs: SimulationRunInputs,
        now: datetime,
    ) -> SimulationRunSnapshot:
        """Atomically append ledgers and move the paper-account state."""

        account_row = self._session.get(SimulationAccountRow, account_id)
        if account_row is None:
            raise SimulationAccountNotFound(account_id)
        input_hash = hash_portfolio_state(input_state)
        if account_row.state_hash != input_hash:
            raise ValueError("paper-account state changed before persistence")

        output_payload = serialize_portfolio_state(outcome.state)
        output_hash = hash_portfolio_state(outcome.state)
        run_id = str(uuid4())
        current = _naive_utc(now)
        run = SimulationRunRow(
            id=run_id,
            account_id=account_id,
            session_date=session_date,
            fingerprint=inputs.fingerprint,
            strategy_id=inputs.strategy_id,
            strategy_version=inputs.strategy_version,
            engine_version=inputs.engine_version,
            parameters=dict(inputs.parameters),
            data_snapshot_id=inputs.data_snapshot_id,
            partition_ids=list(inputs.partition_ids),
            input_state=serialize_portfolio_state(input_state),
            input_state_hash=input_hash,
            output_state=output_payload,
            output_state_hash=output_hash,
            nav_cash=Decimal(str(outcome.nav.cash)),
            nav_market_value=Decimal(str(outcome.nav.market_value)),
            nav_total_value=Decimal(str(outcome.nav.total_value)),
            created_at=current,
        )
        self._session.add(run)
        self._session.add_all(
            [
                SimulationCandidateRow(
                    run_id=run_id,
                    sequence=sequence,
                    symbol=candidate.symbol,
                    signal_date=candidate.signal_date,
                    selected=candidate.selected,
                    score=Decimal(str(candidate.score)),
                    rank=candidate.rank,
                    reasons=[
                        reason.model_dump(mode="json") for reason in candidate.reasons
                    ],
                    metrics=dict(candidate.metrics),
                    data_warnings=list(candidate.data_warnings),
                )
                for sequence, candidate in enumerate(outcome.candidates)
            ]
        )
        self._session.add_all(
            [
                SimulationOrderRow(
                    run_id=run_id,
                    sequence=sequence,
                    symbol=order.symbol,
                    side=order.side.value,
                    quantity=order.quantity,
                    signal_date=order.signal_date,
                )
                for sequence, order in enumerate(outcome.orders)
            ]
        )
        self._session.add_all(
            [
                SimulationFillRow(
                    run_id=run_id,
                    sequence=sequence,
                    symbol=fill.symbol,
                    side=fill.side.value,
                    quantity=fill.quantity,
                    price=Decimal(str(fill.price)),
                    signal_date=fill.signal_date,
                    trade_date=fill.trade_date,
                    commission=Decimal(str(fill.commission)),
                    transfer_fee=Decimal(str(fill.transfer_fee)),
                    stamp_duty=Decimal(str(fill.stamp_duty)),
                )
                for sequence, fill in enumerate(outcome.fills)
            ]
        )
        account_row.current_state = output_payload
        account_row.state_hash = output_hash
        account_row.last_session_date = session_date
        account_row.updated_at = current
        self._session.flush()
        return self._run_snapshot(run)

    def _run_snapshot(self, row: SimulationRunRow) -> SimulationRunSnapshot:
        candidate_rows = self._session.scalars(
            select(SimulationCandidateRow)
            .where(SimulationCandidateRow.run_id == row.id)
            .order_by(SimulationCandidateRow.sequence)
        ).all()
        order_rows = self._session.scalars(
            select(SimulationOrderRow)
            .where(SimulationOrderRow.run_id == row.id)
            .order_by(SimulationOrderRow.sequence)
        ).all()
        fill_rows = self._session.scalars(
            select(SimulationFillRow)
            .where(SimulationFillRow.run_id == row.id)
            .order_by(SimulationFillRow.sequence)
        ).all()
        return SimulationRunSnapshot(
            id=row.id,
            account_id=row.account_id,
            session_date=row.session_date,
            fingerprint=row.fingerprint,
            strategy_id=row.strategy_id,
            strategy_version=row.strategy_version,
            engine_version=row.engine_version,
            parameters=dict(row.parameters),
            data_snapshot_id=row.data_snapshot_id,
            partition_ids=tuple(row.partition_ids),
            input_state=deserialize_portfolio_state(row.input_state),
            input_state_hash=row.input_state_hash,
            output_state=deserialize_portfolio_state(row.output_state),
            output_state_hash=row.output_state_hash,
            candidates=tuple(
                SelectionCandidate(
                    symbol=candidate.symbol,
                    signal_date=candidate.signal_date,
                    selected=candidate.selected,
                    score=float(candidate.score),
                    rank=candidate.rank,
                    reasons=tuple(candidate.reasons),
                    metrics=dict(candidate.metrics),
                    data_warnings=tuple(candidate.data_warnings),
                )
                for candidate in candidate_rows
            ),
            orders=tuple(
                Order(
                    symbol=order.symbol,
                    side=Side(order.side),
                    quantity=order.quantity,
                    signal_date=order.signal_date,
                )
                for order in order_rows
            ),
            fills=tuple(
                Fill(
                    symbol=fill.symbol,
                    side=Side(fill.side),
                    quantity=fill.quantity,
                    price=float(fill.price),
                    signal_date=fill.signal_date,
                    trade_date=fill.trade_date,
                    commission=float(fill.commission),
                    transfer_fee=float(fill.transfer_fee),
                    stamp_duty=float(fill.stamp_duty),
                )
                for fill in fill_rows
            ),
            nav=NavPoint(
                trade_date=row.session_date,
                cash=float(row.nav_cash),
                market_value=float(row.nav_market_value),
                total_value=float(row.nav_total_value),
            ),
        )


def serialize_portfolio_state(state: PortfolioState) -> dict[str, Any]:
    """Serialize money as decimal strings for stable JSON hashes."""

    return {
        "cash": _decimal_text(state.cash),
        "pending_orders": [
            {
                "quantity": order.quantity,
                "side": order.side.value,
                "signal_date": order.signal_date.isoformat(),
                "symbol": order.symbol,
            }
            for order in state.pending_orders
        ],
        "positions": {
            symbol: {
                "average_cost": _decimal_text(position.average_cost),
                "quantity": position.quantity,
            }
            for symbol, position in sorted(state.positions.items())
        },
    }


def deserialize_portfolio_state(payload: dict[str, Any]) -> PortfolioState:
    """Restore a Core state from its canonical JSON representation."""

    positions_payload = payload["positions"]
    orders_payload = payload["pending_orders"]
    if not isinstance(positions_payload, dict) or not isinstance(orders_payload, list):
        raise ValueError("invalid persisted portfolio state")
    return PortfolioState(
        cash=float(payload["cash"]),
        positions={
            symbol: Position(
                quantity=int(value["quantity"]),
                average_cost=float(value["average_cost"]),
            )
            for symbol, value in positions_payload.items()
        },
        pending_orders=tuple(
            Order(
                symbol=value["symbol"],
                side=Side(value["side"]),
                quantity=int(value["quantity"]),
                signal_date=date.fromisoformat(value["signal_date"]),
            )
            for value in orders_payload
        ),
    )


def hash_portfolio_state(state: PortfolioState) -> str:
    """Hash a canonical paper-account state."""

    payload = serialize_portfolio_state(state)
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _account_snapshot(row: SimulationAccountRow) -> SimulationAccountSnapshot:
    return SimulationAccountSnapshot(
        id=row.id,
        name=row.name,
        initial_cash=float(row.initial_cash),
        state=deserialize_portfolio_state(row.current_state),
        state_hash=row.state_hash,
        last_session_date=row.last_session_date,
    )


def _naive_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def _decimal_text(value: float) -> str:
    normalized = Decimal(str(value)).normalize()
    return format(normalized, "f")
