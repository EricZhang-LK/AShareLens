"""Traceable range synchronization with whole-batch provider fallback."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from sqlalchemy.orm import Session

from asharelens.core.models import DailyBar
from asharelens.data.models import Adjustment, DataBatch, Dataset
from asharelens.data.partition import DataPartition, partition_daily_bars
from asharelens.data.provider import DataProviderPlugin, ProviderError
from asharelens.data.quality import DailyBarQualityGate, QualityReport
from asharelens.storage.data_repository import DataRepository


class MarketSyncStatus(StrEnum):
    """Observable result of one provider-routing decision."""

    UPDATED = "updated"
    NO_DATA = "no_data"


class MarketSyncOutcome(StrEnum):
    """Sanitized result retained for each provider attempt."""

    ACCEPTED = "accepted"
    NO_DATA = "no_data"
    PROVIDER_ERROR = "provider_error"
    QUALITY_REJECTED = "quality_rejected"
    CONTRACT_ERROR = "contract_error"


@dataclass(frozen=True, slots=True)
class MarketSyncAttempt:
    """One secret-free provider attempt."""

    provider_id: str
    outcome: MarketSyncOutcome
    error_code: str | None
    retryable: bool
    message: str


@dataclass(frozen=True, slots=True)
class MarketSyncResult:
    """Accepted immutable batch plus per-partition quality evidence."""

    status: MarketSyncStatus
    batch: DataBatch[DailyBar] | None
    partitions: tuple[DataPartition, ...]
    quality_reports: tuple[QualityReport, ...]
    attempts: tuple[MarketSyncAttempt, ...]


class MarketSyncFailure(RuntimeError):
    """No provider supplied a trustworthy range."""

    def __init__(self, attempts: tuple[MarketSyncAttempt, ...]) -> None:
        self.attempts = attempts
        self.retryable = any(attempt.retryable for attempt in attempts)
        providers = ", ".join(attempt.provider_id for attempt in attempts)
        super().__init__(f"market data synchronization failed: {providers}")


class MarketDataSynchronizer:
    """Fetch outside transactions, then publish an accepted batch atomically."""

    def __init__(
        self,
        *,
        providers: tuple[DataProviderPlugin, ...],
        quality_gate: DailyBarQualityGate,
    ) -> None:
        if not providers:
            raise ValueError("at least one provider is required")
        self._providers = providers
        self._quality_gate = quality_gate

    def fetch_range(
        self,
        *,
        start: date,
        end: date,
        symbols: tuple[str, ...],
        adjustment: Adjustment = Adjustment.NONE,
    ) -> MarketSyncResult:
        """Return the first complete single-provider range."""

        if start > end:
            raise ValueError("start must not be later than end")
        if not symbols:
            raise ValueError("symbols must not be empty")
        attempts: list[MarketSyncAttempt] = []
        for provider in self._providers:
            provider_id = provider.metadata.provider_id
            try:
                batch = provider.fetch_daily_bars(
                    symbols,
                    start,
                    end,
                    adjustment,
                )
            except ProviderError as error:
                attempts.append(
                    MarketSyncAttempt(
                        provider_id=provider_id,
                        outcome=MarketSyncOutcome.PROVIDER_ERROR,
                        error_code=error.error_code,
                        retryable=error.retryable,
                        message=str(error),
                    )
                )
                continue
            except Exception:
                attempts.append(
                    MarketSyncAttempt(
                        provider_id=provider_id,
                        outcome=MarketSyncOutcome.PROVIDER_ERROR,
                        error_code="unexpected_provider_failure",
                        retryable=True,
                        message="provider failed unexpectedly",
                    )
                )
                continue

            contract_error = _contract_error(
                batch,
                provider_id=provider_id,
                start=start,
                end=end,
                symbols=symbols,
            )
            if contract_error is not None:
                attempts.append(
                    MarketSyncAttempt(
                        provider_id=provider_id,
                        outcome=MarketSyncOutcome.CONTRACT_ERROR,
                        error_code="provider_contract_violation",
                        retryable=False,
                        message=contract_error,
                    )
                )
                continue

            partitions = partition_daily_bars(batch)
            if not partitions:
                attempts.append(
                    MarketSyncAttempt(
                        provider_id=provider_id,
                        outcome=MarketSyncOutcome.NO_DATA,
                        error_code=None,
                        retryable=False,
                        message="provider returned no trading-day records",
                    )
                )
                continue

            reports = tuple(
                self._quality_gate.evaluate(
                    partition,
                    expected_symbols=symbols,
                )
                for partition in partitions
            )
            if not all(report.publishable for report in reports):
                codes = sorted(
                    {
                        issue.code
                        for report in reports
                        for issue in report.issues
                        if issue.severity == "failure"
                    }
                )
                attempts.append(
                    MarketSyncAttempt(
                        provider_id=provider_id,
                        outcome=MarketSyncOutcome.QUALITY_REJECTED,
                        error_code="quality_gate_failed",
                        retryable=False,
                        message=",".join(codes),
                    )
                )
                continue

            attempts.append(
                MarketSyncAttempt(
                    provider_id=provider_id,
                    outcome=MarketSyncOutcome.ACCEPTED,
                    error_code=None,
                    retryable=False,
                    message=f"accepted {len(partitions)} daily partitions",
                )
            )
            return MarketSyncResult(
                status=MarketSyncStatus.UPDATED,
                batch=batch,
                partitions=partitions,
                quality_reports=reports,
                attempts=tuple(attempts),
            )

        if attempts and all(
            attempt.outcome is MarketSyncOutcome.NO_DATA for attempt in attempts
        ):
            return MarketSyncResult(
                status=MarketSyncStatus.NO_DATA,
                batch=None,
                partitions=(),
                quality_reports=(),
                attempts=tuple(attempts),
            )
        raise MarketSyncFailure(tuple(attempts))

    def publish(self, session: Session, result: MarketSyncResult) -> tuple[str, ...]:
        """Publish one previously fetched accepted result in caller transaction."""

        if result.status is MarketSyncStatus.NO_DATA:
            return ()
        if result.batch is None:
            raise ValueError("updated synchronization result requires a batch")
        if len(result.partitions) != len(result.quality_reports):
            raise ValueError("partition and quality report counts differ")

        repository = DataRepository(session)
        repository.record_batch(result.batch)
        return tuple(
            repository.publish_daily_partition(partition, report)
            for partition, report in zip(
                result.partitions,
                result.quality_reports,
                strict=True,
            )
        )


def _contract_error(
    batch: DataBatch[DailyBar],
    *,
    provider_id: str,
    start: date,
    end: date,
    symbols: tuple[str, ...],
) -> str | None:
    if batch.dataset is not Dataset.DAILY_BARS:
        return "provider returned the wrong dataset"
    if batch.provider_id != provider_id:
        return "batch provider ID does not match the selected provider"
    expected = set(symbols)
    for bar in batch.records:
        if bar.symbol not in expected:
            return "provider returned an unrequested symbol"
        if not start <= bar.trade_date <= end:
            return "provider returned a record outside the requested range"
    return None
