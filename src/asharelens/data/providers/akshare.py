"""AkShare adapter for free沪深京补充数据."""

from __future__ import annotations

import importlib
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from functools import partial
from time import perf_counter
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from asharelens.core.models import DailyBar
from asharelens.data.models import (
    Adjustment,
    DataBatch,
    Dataset,
    Instrument,
    RequestScalar,
    TradingSession,
)
from asharelens.data.provider import (
    ProviderError,
    ProviderHealth,
    ProviderMetadata,
)
from asharelens.data.providers.common import (
    build_source_batch_id,
    canonical_hash,
    normalize_a_share_symbol,
)

ADJUSTMENTS = {
    Adjustment.NONE: "",
    Adjustment.FORWARD: "qfq",
    Adjustment.BACKWARD: "hfq",
}


class AkShareGateway(Protocol):
    """SDK boundary returning plain row dictionaries."""

    version: str

    def fetch_instruments(self) -> list[dict[str, object]]: ...

    def fetch_open_dates(self) -> list[dict[str, object]]: ...

    def fetch_daily(
        self,
        *,
        symbol: str,
        start_date: str,
        end_date: str,
        adjust: str,
    ) -> list[dict[str, object]]: ...


class AkShareSdkGateway:
    """Lazy wrapper around the optional AkShare module."""

    def __init__(self) -> None:
        try:
            self._sdk: Any = importlib.import_module("akshare")
        except ModuleNotFoundError as error:
            raise ProviderError(
                provider_id="akshare",
                error_code="dependency_missing",
                message='AkShare 未安装；请安装 "asharelens[akshare]"。',
                retryable=False,
            ) from error
        self.version = str(getattr(self._sdk, "__version__", "unknown"))

    def fetch_instruments(self) -> list[dict[str, object]]:
        return _records(self._sdk.stock_info_a_code_name())

    def fetch_open_dates(self) -> list[dict[str, object]]:
        return _records(self._sdk.tool_trade_date_hist_sina())

    def fetch_daily(
        self,
        *,
        symbol: str,
        start_date: str,
        end_date: str,
        adjust: str,
    ) -> list[dict[str, object]]:
        return _records(
            self._sdk.stock_zh_a_hist(
                symbol=symbol,
                period="daily",
                start_date=start_date,
                end_date=end_date,
                adjust=adjust,
            )
        )


class AkShareProvider:
    """Zero-registration supplement, especially for Beijing-listed shares."""

    metadata = ProviderMetadata(
        provider_id="akshare",
        name="AkShare",
        version="1.0.0",
        description="免注册的沪深京 A 股补充数据源。",
        datasets=(
            Dataset.INSTRUMENTS,
            Dataset.TRADING_CALENDAR,
            Dataset.DAILY_BARS,
        ),
        requires_registration=False,
    )

    def __init__(
        self,
        *,
        gateway: AkShareGateway | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._gateway_override = gateway
        self._clock = clock or (lambda: datetime.now(UTC))

    def healthcheck(self) -> ProviderHealth:
        started = perf_counter()
        try:
            rows = self._call(self._gateway().fetch_open_dates)
            ok = bool(rows)
            message = "连接正常" if ok else "AkShare 未返回交易日历"
        except ProviderError as error:
            ok = False
            message = (
                str(error)
                if error.error_code == "dependency_missing"
                else "AkShare 上游不可用"
            )
        return ProviderHealth(
            provider_id=self.metadata.provider_id,
            ok=ok,
            checked_at=self._clock(),
            message=message,
            latency_ms=round((perf_counter() - started) * 1000),
        )

    def fetch_instruments(self, as_of: date) -> DataBatch[Instrument]:
        current_date = self._clock().astimezone(ZoneInfo("Asia/Shanghai")).date()
        if as_of != current_date:
            raise ProviderError(
                provider_id=self.metadata.provider_id,
                error_code="point_in_time_unsupported",
                message="AkShare 股票列表仅代表当前快照，不能用于历史时点股票池。",
                retryable=False,
            )
        gateway = self._gateway()
        rows = self._call(gateway.fetch_instruments)
        records: list[Instrument] = []
        for row in rows:
            try:
                symbol = normalize_a_share_symbol(str(row["code"]))
            except (KeyError, ValueError):
                continue
            name = str(row.get("name", "")).strip()
            if name:
                records.append(Instrument(symbol=symbol, name=name, is_active=True))
        request: dict[str, RequestScalar] = {
            "as_of": as_of.isoformat(),
            "snapshot_semantics": "current_only",
            "upstream_version": gateway.version,
        }
        return self._batch(Dataset.INSTRUMENTS, request, rows, tuple(records))

    def fetch_calendar(
        self,
        start: date,
        end: date,
    ) -> DataBatch[TradingSession]:
        _validate_range(start, end)
        gateway = self._gateway()
        rows = self._call(gateway.fetch_open_dates)
        try:
            open_dates = {
                _as_date(row["trade_date"])
                for row in rows
                if start <= _as_date(row["trade_date"]) <= end
            }
        except (KeyError, TypeError, ValueError) as error:
            raise _schema_error() from error
        records = tuple(
            TradingSession(trade_date=day, is_open=day in open_dates)
            for day in _inclusive_dates(start, end)
        )
        request: dict[str, RequestScalar] = {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "upstream_version": gateway.version,
        }
        return self._batch(Dataset.TRADING_CALENDAR, request, rows, records)

    def fetch_daily_bars(
        self,
        symbols: tuple[str, ...],
        start: date,
        end: date,
        adjustment: Adjustment,
    ) -> DataBatch[DailyBar]:
        _validate_range(start, end)
        gateway = self._gateway()
        normalized_symbols: list[str] = []
        try:
            normalized_symbols = [
                normalize_a_share_symbol(symbol) for symbol in symbols
            ]
        except ValueError as error:
            raise ProviderError(
                provider_id=self.metadata.provider_id,
                error_code="invalid_symbol",
                message="AkShare 请求包含无效 A 股代码。",
                retryable=False,
            ) from error

        raw_rows: list[dict[str, object]] = []
        records: list[DailyBar] = []
        for symbol in normalized_symbols:
            rows = self._call(
                partial(
                    gateway.fetch_daily,
                    symbol=symbol[3:],
                    start_date=start.strftime("%Y%m%d"),
                    end_date=end.strftime("%Y%m%d"),
                    adjust=ADJUSTMENTS[adjustment],
                )
            )
            raw_rows.extend(rows)
            for row in rows:
                try:
                    row_symbol = normalize_a_share_symbol(
                        str(row.get("股票代码", symbol[3:]))
                    )
                    if row_symbol != symbol:
                        continue
                    records.append(
                        DailyBar(
                            symbol=row_symbol,
                            trade_date=_as_date(row["日期"]),
                            open=_as_float(row["开盘"]),
                            high=_as_float(row["最高"]),
                            low=_as_float(row["最低"]),
                            close=_as_float(row["收盘"]),
                            volume=int(_as_float(row["成交量"]) * 100),
                            amount=_as_float(row["成交额"]),
                            is_trading=True,
                            is_st=False,
                        )
                    )
                except (KeyError, TypeError, ValueError) as error:
                    raise _schema_error() from error

        request: dict[str, RequestScalar] = {
            "symbols": ",".join(normalized_symbols),
            "start": start.isoformat(),
            "end": end.isoformat(),
            "adjustment": adjustment.value,
            "upstream_version": gateway.version,
            "volume_unit": "shares",
            "amount_unit": "CNY",
        }
        return self._batch(Dataset.DAILY_BARS, request, raw_rows, tuple(records))

    def _gateway(self) -> AkShareGateway:
        return self._gateway_override or AkShareSdkGateway()

    def _call[ResultT](self, action: Callable[[], ResultT]) -> ResultT:
        try:
            return action()
        except ProviderError:
            raise
        except Exception as error:
            raise ProviderError(
                provider_id=self.metadata.provider_id,
                error_code="upstream_query_failed",
                message="AkShare 查询失败。",
                retryable=True,
            ) from error

    def _batch[RecordT](
        self,
        dataset: Dataset,
        request: dict[str, RequestScalar],
        raw_rows: list[dict[str, object]],
        records: tuple[RecordT, ...],
    ) -> DataBatch[RecordT]:
        content_hash = canonical_hash(
            {
                "dataset": dataset,
                "request": request,
                "rows": _json_safe_rows(raw_rows),
            }
        )
        return DataBatch[RecordT](
            dataset=dataset,
            provider_id=self.metadata.provider_id,
            provider_version=self.metadata.version,
            fetched_at=self._clock(),
            request=request,
            source_batch_id=build_source_batch_id(
                self.metadata.provider_id,
                dataset,
                content_hash,
            ),
            content_hash=content_hash,
            records=records,
        )


def _records(frame: object) -> list[dict[str, object]]:
    converter = getattr(frame, "to_dict", None)
    if converter is None:
        raise TypeError("AkShare response is not a DataFrame-like object")
    rows = converter(orient="records")
    if not isinstance(rows, list):
        raise TypeError("AkShare response records are invalid")
    return [dict(row) for row in rows]


def _inclusive_dates(start: date, end: date) -> tuple[date, ...]:
    return tuple(
        start + timedelta(days=offset)
        for offset in range((end - start).days + 1)
    )


def _as_date(value: object) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _validate_range(start: date, end: date) -> None:
    if start > end:
        raise ValueError("start must not be later than end")


def _schema_error() -> ProviderError:
    return ProviderError(
        provider_id="akshare",
        error_code="schema_mismatch",
        message="AkShare 返回字段与适配器契约不一致。",
        retryable=False,
    )


def _json_safe_rows(
    rows: list[dict[str, object]],
) -> list[dict[str, object]]:
    return [
        {str(key): _json_safe_value(value) for key, value in row.items()}
        for row in rows
    ]


def _json_safe_value(value: object) -> object:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    item = getattr(value, "item", None)
    if callable(item):
        return item()
    return str(value)


def _as_float(value: object) -> float:
    if isinstance(value, (str, int, float)):
        return float(value)
    item = getattr(value, "item", None)
    if callable(item):
        scalar = item()
        if isinstance(scalar, (str, int, float)):
            return float(scalar)
    raise TypeError("value is not numeric")
