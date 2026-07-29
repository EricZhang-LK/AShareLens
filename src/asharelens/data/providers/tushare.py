"""Token-configured Tushare Pro adapter with secret-safe diagnostics."""

from __future__ import annotations

import importlib
import os
from collections.abc import Callable
from datetime import UTC, date, datetime
from functools import partial
from time import perf_counter
from typing import Any, Protocol

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
    to_tushare_symbol,
)

DAILY_FIELDS = "ts_code,trade_date,open,high,low,close,vol,amount"
STOCK_FIELDS = "ts_code,name,list_date,delist_date"
LIST_STATUSES = ("L", "D", "P", "G")


class TushareGateway(Protocol):
    """Subset of Tushare Pro used by the Provider."""

    version: str

    def fetch_stock_basic(
        self,
        list_status: str,
    ) -> list[dict[str, object]]: ...

    def fetch_calendar(
        self,
        *,
        start_date: str,
        end_date: str,
    ) -> list[dict[str, object]]: ...

    def fetch_daily_by_date(
        self,
        trade_date: str,
    ) -> list[dict[str, object]]: ...

    def fetch_daily_by_symbol(
        self,
        *,
        ts_code: str,
        start_date: str,
        end_date: str,
    ) -> list[dict[str, object]]: ...


class TushareSdkGateway:
    """Lazy SDK client that receives the Token only at construction."""

    def __init__(self, token: str) -> None:
        try:
            self._sdk: Any = importlib.import_module("tushare")
        except ModuleNotFoundError as error:
            raise ProviderError(
                provider_id="tushare",
                error_code="dependency_missing",
                message='Tushare 未安装；请安装 "asharelens[tushare]"。',
                retryable=False,
            ) from error
        try:
            self._pro: Any = self._sdk.pro_api(token)
        except Exception as error:
            raise ProviderError(
                provider_id="tushare",
                error_code="authentication_failed",
                message="Tushare 初始化失败，请检查 Token 和权限。",
                retryable=False,
            ) from error
        self.version = str(getattr(self._sdk, "__version__", "unknown"))

    def fetch_stock_basic(
        self,
        list_status: str,
    ) -> list[dict[str, object]]:
        return _records(
            self._pro.stock_basic(
                exchange="",
                list_status=list_status,
                fields=STOCK_FIELDS,
            )
        )

    def fetch_calendar(
        self,
        *,
        start_date: str,
        end_date: str,
    ) -> list[dict[str, object]]:
        return _records(
            self._pro.trade_cal(
                exchange="",
                start_date=start_date,
                end_date=end_date,
                fields="cal_date,is_open",
            )
        )

    def fetch_daily_by_date(
        self,
        trade_date: str,
    ) -> list[dict[str, object]]:
        return _records(
            self._pro.daily(
                trade_date=trade_date,
                fields=DAILY_FIELDS,
            )
        )

    def fetch_daily_by_symbol(
        self,
        *,
        ts_code: str,
        start_date: str,
        end_date: str,
    ) -> list[dict[str, object]]:
        return _records(
            self._pro.daily(
                ts_code=ts_code,
                start_date=start_date,
                end_date=end_date,
                fields=DAILY_FIELDS,
            )
        )


class TushareProvider:
    """Optional registered data source with point-in-time listings."""

    metadata = ProviderMetadata(
        provider_id="tushare",
        name="Tushare Pro",
        version="1.0.0",
        description="用户配置 Token 的 A 股专业数据源。",
        datasets=(
            Dataset.INSTRUMENTS,
            Dataset.TRADING_CALENDAR,
            Dataset.DAILY_BARS,
        ),
        requires_registration=True,
    )

    def __init__(
        self,
        *,
        token: str | None = None,
        gateway: TushareGateway | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._token = token
        self._gateway_override = gateway
        self._clock = clock or (lambda: datetime.now(UTC))

    def healthcheck(self) -> ProviderHealth:
        started = perf_counter()
        today = self._clock().date().strftime("%Y%m%d")
        try:
            gateway = self._gateway()
            self._call(
                lambda: gateway.fetch_calendar(start_date=today, end_date=today)
            )
            ok = True
            message = "连接正常"
        except ProviderError as error:
            ok = False
            message = (
                str(error)
                if error.error_code in {"configuration_missing", "dependency_missing"}
                else "Tushare 上游不可用"
            )
        return ProviderHealth(
            provider_id=self.metadata.provider_id,
            ok=ok,
            checked_at=self._clock(),
            message=message,
            latency_ms=round((perf_counter() - started) * 1000),
        )

    def fetch_instruments(self, as_of: date) -> DataBatch[Instrument]:
        gateway = self._gateway()
        rows: list[dict[str, object]] = []
        for list_status in LIST_STATUSES:
            rows.extend(
                self._call(partial(gateway.fetch_stock_basic, list_status))
            )

        by_symbol: dict[str, Instrument] = {}
        for row in rows:
            try:
                symbol = normalize_a_share_symbol(str(row["ts_code"]))
                name = str(row["name"]).strip()
                listed_on = _optional_compact_date(row.get("list_date"))
                delisted_on = _optional_compact_date(row.get("delist_date"))
            except (KeyError, TypeError, ValueError) as error:
                raise _schema_error() from error
            if not name or (listed_on is not None and listed_on > as_of):
                continue
            if delisted_on is not None and as_of >= delisted_on:
                continue
            by_symbol[symbol] = Instrument(
                symbol=symbol,
                name=name,
                listed_on=listed_on,
                delisted_on=delisted_on,
                is_active=True,
            )
        records = tuple(by_symbol[symbol] for symbol in sorted(by_symbol))
        request: dict[str, RequestScalar] = {
            "as_of": as_of.isoformat(),
            "list_statuses": ",".join(LIST_STATUSES),
            "upstream_version": gateway.version,
        }
        return self._batch(Dataset.INSTRUMENTS, request, rows, records)

    def fetch_calendar(
        self,
        start: date,
        end: date,
    ) -> DataBatch[TradingSession]:
        _validate_range(start, end)
        gateway = self._gateway()
        rows = self._call(
            lambda: gateway.fetch_calendar(
                start_date=start.strftime("%Y%m%d"),
                end_date=end.strftime("%Y%m%d"),
            )
        )
        try:
            records = tuple(
                TradingSession(
                    trade_date=_compact_date(row["cal_date"]),
                    is_open=str(row["is_open"]) == "1",
                )
                for row in sorted(rows, key=lambda value: str(value["cal_date"]))
            )
        except (KeyError, TypeError, ValueError) as error:
            raise _schema_error() from error
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
        if adjustment is not Adjustment.NONE:
            raise ProviderError(
                provider_id=self.metadata.provider_id,
                error_code="adjustment_unsupported",
                message="Tushare daily 适配器只提供未复权行情。",
                retryable=False,
            )
        try:
            normalized_symbols = tuple(
                normalize_a_share_symbol(symbol) for symbol in symbols
            )
        except ValueError as error:
            raise ProviderError(
                provider_id=self.metadata.provider_id,
                error_code="invalid_symbol",
                message="Tushare 请求包含无效 A 股代码。",
                retryable=False,
            ) from error
        expected = set(normalized_symbols)
        gateway = self._gateway()
        rows: list[dict[str, object]] = []
        if start == end:
            rows.extend(
                self._call(
                    lambda: gateway.fetch_daily_by_date(start.strftime("%Y%m%d"))
                )
            )
        else:
            for symbol in normalized_symbols:
                ts_code = to_tushare_symbol(symbol)
                rows.extend(
                    self._call(
                        partial(
                            gateway.fetch_daily_by_symbol,
                            ts_code=ts_code,
                            start_date=start.strftime("%Y%m%d"),
                            end_date=end.strftime("%Y%m%d"),
                        )
                    )
                )

        records: list[DailyBar] = []
        for row in rows:
            try:
                symbol = normalize_a_share_symbol(str(row["ts_code"]))
                if symbol not in expected:
                    continue
                records.append(
                    DailyBar(
                        symbol=symbol,
                        trade_date=_compact_date(row["trade_date"]),
                        open=_as_float(row["open"]),
                        high=_as_float(row["high"]),
                        low=_as_float(row["low"]),
                        close=_as_float(row["close"]),
                        volume=round(_as_float(row["vol"]) * 100),
                        amount=_as_float(row["amount"]) * 1000,
                        is_trading=True,
                        is_st=False,
                    )
                )
            except (KeyError, TypeError, ValueError) as error:
                raise _schema_error() from error
        records.sort(key=lambda bar: (bar.symbol, bar.trade_date))
        request: dict[str, RequestScalar] = {
            "symbols": ",".join(normalized_symbols),
            "start": start.isoformat(),
            "end": end.isoformat(),
            "adjustment": adjustment.value,
            "query_mode": "trade_date" if start == end else "symbol_range",
            "upstream_version": gateway.version,
            "volume_unit": "shares",
            "amount_unit": "CNY",
        }
        return self._batch(Dataset.DAILY_BARS, request, rows, tuple(records))

    def _gateway(self) -> TushareGateway:
        if self._gateway_override is not None:
            return self._gateway_override
        token = self._token or os.getenv("TUSHARE_TOKEN")
        if not token:
            raise ProviderError(
                provider_id=self.metadata.provider_id,
                error_code="configuration_missing",
                message="未配置 TUSHARE_TOKEN。",
                retryable=False,
            )
        return TushareSdkGateway(token)

    def _call[ResultT](self, action: Callable[[], ResultT]) -> ResultT:
        try:
            return action()
        except ProviderError:
            raise
        except Exception as error:
            raise ProviderError(
                provider_id=self.metadata.provider_id,
                error_code="upstream_query_failed",
                message="Tushare 查询失败。",
                retryable=True,
            ) from error

    def _batch[RecordT](
        self,
        dataset: Dataset,
        request: dict[str, RequestScalar],
        rows: list[dict[str, object]],
        records: tuple[RecordT, ...],
    ) -> DataBatch[RecordT]:
        content_hash = canonical_hash(
            {
                "dataset": dataset,
                "request": request,
                "rows": _json_safe_rows(rows),
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
        raise TypeError("Tushare response is not a DataFrame-like object")
    rows = converter(orient="records")
    if not isinstance(rows, list):
        raise TypeError("Tushare response records are invalid")
    return [dict(row) for row in rows]


def _compact_date(value: object) -> date:
    text = str(value)
    if len(text) == 8 and text.isdigit():
        return datetime.strptime(text, "%Y%m%d").date()
    return date.fromisoformat(text[:10])


def _optional_compact_date(value: object) -> date | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return None
    return _compact_date(text)


def _as_float(value: object) -> float:
    if isinstance(value, (str, int, float)):
        return float(value)
    item = getattr(value, "item", None)
    if callable(item):
        scalar = item()
        if isinstance(scalar, (str, int, float)):
            return float(scalar)
    raise TypeError("value is not numeric")


def _validate_range(start: date, end: date) -> None:
    if start > end:
        raise ValueError("start must not be later than end")


def _schema_error() -> ProviderError:
    return ProviderError(
        provider_id="tushare",
        error_code="schema_mismatch",
        message="Tushare 返回字段与适配器契约不一致。",
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
