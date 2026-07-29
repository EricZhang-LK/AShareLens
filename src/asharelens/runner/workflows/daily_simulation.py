"""Daily paper simulation backed by the same Core transition as backtests."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import date, datetime

from pydantic import BaseModel
from sqlalchemy.orm import Session

from asharelens.core.engine import (
    ENGINE_VERSION,
    DailyCycleEngine,
    build_data_snapshot_id,
)
from asharelens.core.models import DailyBar, FundamentalSnapshot
from asharelens.storage.simulation_repository import (
    SimulationAccountSnapshot,
    SimulationRepository,
    SimulationRunInputs,
    SimulationRunSnapshot,
)


class SimulationReplayConflict(ValueError):
    """A completed account date cannot be silently rewritten with new inputs."""


class SimulationSessionOrderError(ValueError):
    """Daily account transitions must advance in chronological order."""


class DailySimulationService[ParamsT: BaseModel]:
    """Advance a persisted paper account through one shared Core session."""

    def __init__(
        self,
        session: Session,
        *,
        engine: DailyCycleEngine[ParamsT],
    ) -> None:
        self._repository = SimulationRepository(session)
        self._engine = engine

    def create_account(
        self,
        *,
        name: str,
        now: datetime,
    ) -> SimulationAccountSnapshot:
        """Create a paper account from the Engine's configured initial cash."""

        return self._repository.create_account(
            name=name,
            initial_state=self._engine.initial_state(),
            now=now,
        )

    def process_session(
        self,
        *,
        account_id: str,
        session_date: date,
        history: Mapping[str, tuple[DailyBar, ...]],
        partition_ids: tuple[str, ...],
        now: datetime,
        fundamentals: Mapping[str, tuple[FundamentalSnapshot, ...]] | None = None,
    ) -> SimulationRunSnapshot:
        """Run and atomically persist one date, idempotently."""

        normalized_partitions = tuple(sorted(set(partition_ids)))
        if not normalized_partitions:
            raise ValueError("partition_ids must identify the exact input data")
        data_snapshot_id = build_data_snapshot_id(history, fundamentals)
        parameters = self._engine.params.model_dump(mode="json")
        execution_config = self._engine.execution_config()
        strategy_id = self._engine.strategy.metadata.strategy_id
        strategy_version = self._engine.strategy.metadata.version

        account = self._repository.get_account(account_id, for_update=True)
        existing = self._repository.get_run(
            account_id,
            session_date,
            for_update=True,
        )
        if existing is not None:
            if (
                existing.strategy_id != strategy_id
                or existing.strategy_version != strategy_version
                or existing.parameters != parameters
                or existing.execution_config != execution_config
                or existing.data_snapshot_id != data_snapshot_id
                or existing.partition_ids != normalized_partitions
            ):
                raise SimulationReplayConflict(
                    "completed simulation date has different immutable inputs"
                )
            return existing

        if (
            account.last_session_date is not None
            and session_date <= account.last_session_date
        ):
            raise SimulationSessionOrderError(
                "simulation sessions must advance chronologically"
            )

        outcome = self._engine.process_session(
            account.state,
            session_date,
            history,
            fundamentals,
        )
        fingerprint = _simulation_fingerprint(
            account_id=account.id,
            session_date=session_date,
            strategy_id=strategy_id,
            strategy_version=strategy_version,
            parameters=parameters,
            execution_config=execution_config,
            data_snapshot_id=data_snapshot_id,
            partition_ids=normalized_partitions,
            input_state_hash=account.state_hash,
        )
        return self._repository.advance(
            account_id=account.id,
            session_date=session_date,
            input_state=account.state,
            outcome=outcome,
            inputs=SimulationRunInputs(
                fingerprint=fingerprint,
                strategy_id=strategy_id,
                strategy_version=strategy_version,
                engine_version=ENGINE_VERSION,
                parameters=parameters,
                execution_config=execution_config,
                data_snapshot_id=data_snapshot_id,
                partition_ids=normalized_partitions,
            ),
            now=now,
        )


def _simulation_fingerprint(
    *,
    account_id: str,
    session_date: date,
    strategy_id: str,
    strategy_version: str,
    parameters: dict[str, object],
    execution_config: dict[str, object],
    data_snapshot_id: str,
    partition_ids: tuple[str, ...],
    input_state_hash: str,
) -> str:
    payload = {
        "account_id": account_id,
        "data_snapshot_id": data_snapshot_id,
        "engine_version": ENGINE_VERSION,
        "input_state_hash": input_state_hash,
        "parameters": parameters,
        "execution_config": execution_config,
        "partition_ids": partition_ids,
        "session_date": session_date.isoformat(),
        "strategy_id": strategy_id,
        "strategy_version": strategy_version,
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()
