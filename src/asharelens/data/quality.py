"""Deterministic data-quality gates applied before partition publication."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from asharelens.core.models import FrozenModel
from asharelens.data.partition import DataPartition


class QualitySeverity(StrEnum):
    """Whether an issue blocks publication or marks it degraded."""

    WARNING = "warning"
    FAILURE = "failure"


class QualityIssue(FrozenModel):
    """One stable machine-readable quality finding."""

    severity: QualitySeverity
    code: str
    message: str
    symbol: str | None = None


class QualityReport(FrozenModel):
    """Ordered findings and coverage for one partition."""

    coverage: float = Field(ge=0, le=1)
    issues: tuple[QualityIssue, ...]

    @property
    def publishable(self) -> bool:
        return all(issue.severity is not QualitySeverity.FAILURE for issue in self.issues)

    @property
    def degraded(self) -> bool:
        return any(issue.severity is QualitySeverity.WARNING for issue in self.issues)


class DailyBarQualityGate(BaseModel):
    """Evaluate structural coverage and trading-state anomalies."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    min_coverage: float = Field(default=0.98, ge=0, le=1)

    def evaluate(
        self,
        partition: DataPartition,
        *,
        expected_symbols: Iterable[str],
    ) -> QualityReport:
        expected = set(expected_symbols)
        present = {record.symbol for record in partition.records}
        coverage = len(present & expected) / len(expected) if expected else 1.0
        issues: list[QualityIssue] = []

        counts = Counter((record.symbol, record.trade_date) for record in partition.records)
        for (symbol, trade_date), count in counts.items():
            if count > 1:
                issues.append(
                    QualityIssue(
                        severity=QualitySeverity.FAILURE,
                        code="duplicate_record",
                        message=f"{symbol} 在 {trade_date} 出现 {count} 条记录。",
                        symbol=symbol,
                    )
                )

        if coverage < self.min_coverage:
            issues.append(
                QualityIssue(
                    severity=QualitySeverity.FAILURE,
                    code="coverage_below_threshold",
                    message=(
                        f"分区覆盖率 {coverage:.4f} 低于门限 "
                        f"{self.min_coverage:.4f}。"
                    ),
                )
            )

        for record in partition.records:
            if record.trade_date != partition.key.partition_date:
                issues.append(
                    QualityIssue(
                        severity=QualitySeverity.FAILURE,
                        code="unexpected_trade_date",
                        message=(
                            f"{record.symbol} 的记录日期 {record.trade_date} "
                            f"不属于分区 {partition.key.partition_date}。"
                        ),
                        symbol=record.symbol,
                    )
                )
            if record.is_trading and record.volume == 0:
                issues.append(
                    QualityIssue(
                        severity=QualitySeverity.WARNING,
                        code="zero_volume",
                        message=f"{record.symbol} 标记为交易但成交量为零。",
                        symbol=record.symbol,
                    )
                )

        severity_order = {
            QualitySeverity.FAILURE: 0,
            QualitySeverity.WARNING: 1,
        }
        ordered = tuple(
            sorted(
                issues,
                key=lambda issue: (
                    severity_order[issue.severity],
                    issue.code,
                    issue.symbol or "",
                ),
            )
        )
        return QualityReport(coverage=coverage, issues=ordered)
