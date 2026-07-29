"""Whole-partition routing across ordered data Providers."""

from __future__ import annotations

from datetime import date
from enum import StrEnum

from asharelens.core.models import FrozenModel
from asharelens.data.models import Adjustment
from asharelens.data.partition import DataPartition, partition_daily_bars
from asharelens.data.provider import DataProviderPlugin, ProviderError
from asharelens.data.quality import DailyBarQualityGate, QualityReport


class RoutingOutcome(StrEnum):
    """Result of one Provider attempt."""

    ACCEPTED = "accepted"
    PROVIDER_ERROR = "provider_error"
    QUALITY_REJECTED = "quality_rejected"


class ProviderAttempt(FrozenModel):
    """Sanitized evidence retained for routing diagnostics."""

    provider_id: str
    outcome: RoutingOutcome
    error_code: str | None = None
    message: str


class RoutedPartition(FrozenModel):
    """One accepted partition and the attempts that led to it."""

    partition: DataPartition
    quality_report: QualityReport
    attempts: tuple[ProviderAttempt, ...]


class AllProvidersFailed(RuntimeError):
    """Raised when no Provider supplies a publishable complete partition."""

    def __init__(self, attempts: tuple[ProviderAttempt, ...]) -> None:
        self.attempts = attempts
        provider_ids = ", ".join(attempt.provider_id for attempt in attempts)
        super().__init__(f"no provider supplied a publishable partition: {provider_ids}")


class ProviderRouter:
    """Try Providers in order without combining records between them."""

    def __init__(
        self,
        *,
        providers: tuple[DataProviderPlugin, ...],
        quality_gate: DailyBarQualityGate,
    ) -> None:
        if not providers:
            raise ValueError("at least one provider is required")
        self.providers = providers
        self.quality_gate = quality_gate

    def fetch_daily_partition(
        self,
        trade_date: date,
        symbols: tuple[str, ...],
        adjustment: Adjustment = Adjustment.NONE,
    ) -> RoutedPartition:
        """Return the first complete, publishable single-source partition."""

        attempts: list[ProviderAttempt] = []
        for provider in self.providers:
            provider_id = provider.metadata.provider_id
            try:
                batch = provider.fetch_daily_bars(
                    symbols,
                    trade_date,
                    trade_date,
                    adjustment,
                )
            except ProviderError as error:
                attempts.append(
                    ProviderAttempt(
                        provider_id=provider_id,
                        outcome=RoutingOutcome.PROVIDER_ERROR,
                        error_code=error.error_code,
                        message=str(error),
                    )
                )
                continue

            partitions = partition_daily_bars(batch)
            partition = next(
                (
                    candidate
                    for candidate in partitions
                    if candidate.key.partition_date == trade_date
                ),
                None,
            )
            if partition is None:
                attempts.append(
                    ProviderAttempt(
                        provider_id=provider_id,
                        outcome=RoutingOutcome.QUALITY_REJECTED,
                        error_code="missing_partition",
                        message=f"provider returned no partition for {trade_date}",
                    )
                )
                continue

            report = self.quality_gate.evaluate(
                partition,
                expected_symbols=symbols,
            )
            if not report.publishable:
                failure_codes = ",".join(
                    issue.code for issue in report.issues if issue.severity == "failure"
                )
                attempts.append(
                    ProviderAttempt(
                        provider_id=provider_id,
                        outcome=RoutingOutcome.QUALITY_REJECTED,
                        error_code="quality_gate_failed",
                        message=failure_codes,
                    )
                )
                continue

            attempts.append(
                ProviderAttempt(
                    provider_id=provider_id,
                    outcome=RoutingOutcome.ACCEPTED,
                    message="partition accepted",
                )
            )
            return RoutedPartition(
                partition=partition,
                quality_report=report,
                attempts=tuple(attempts),
            )

        raise AllProvidersFailed(tuple(attempts))
