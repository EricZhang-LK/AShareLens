"""BaoStock 0.9.3 adapter with lazy SDK loading and stable errors."""

from __future__ import annotations

import hashlib
import importlib
import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from time import perf_counter
from typing import Any, Protocol, cast

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

DAILY_FIELDS = "date,code,open,high,low,close,volume,amount,tradestatus,isST"
ADJUSTMENT_FLAGS = {
    Adjustment.NONE: "3",
    Adjustment.FORWARD: "2",
    Adjustment.BACKWARD: "1",
}


class ResultSetLike(Protocol):
    """Subset of BaoStock ResultData consumed by the adapter."""

    fields: list[str]
    error_code: str
    error_msg: str

    def next(self) -> bool: ...

    def get_row_data(self) -> list[str]: ...


class BaoStockGateway(Protocol):
    """Injectable boundary around BaoStock's module-level socket client."""

    def login(self) -> ResultSetLike: ...

    def logout(self) -> ResultSetLike: ...

    def query_all_stock(self, day: str) -> ResultSetLike: ...

    def query_trade_dates(self, start_date: str, end_date: str) -> ResultSetLike: ...

    def query_history_k_data_plus(
        self,
        code: str,
        fields: str,
        *,
        start_date: str,
        end_date: str,
        frequency: str,
        adjustflag: str,
    ) -> ResultSetLike: ...


class BaoStockSdkGateway:
    """Lazy dynamic wrapper that keeps BaoStock an optional dependency."""

    def __init__(self) -> None:
        try:
            self._sdk: Any = importlib.import_module("baostock")
        except ModuleNotFoundError as error:
            raise ProviderError(
                provider_id="baostock",
                error_code="dependency_missing",
                message='BaoStock 未安装；请安装 "asharelens[baostock]"。',
                retryable=False,
            ) from error

    def login(self) -> ResultSetLike:
        return cast(ResultSetLike, self._sdk.login())

    def logout(self) -> ResultSetLike:
        return cast(ResultSetLike, self._sdk.logout())

    def query_all_stock(self, day: str) -> ResultSetLike:
        return cast(ResultSetLike, self._sdk.query_all_stock(day))

    def query_trade_dates(self, start_date: str, end_date: str) -> ResultSetLike:
        return cast(ResultSetLike, self._sdk.query_trade_dates(start_date, end_date))

    def query_history_k_data_plus(
        self,
        code: str,
        fields: str,
        *,
        start_date: str,
        end_date: str,
        frequency: str,
        adjustflag: str,
    ) -> ResultSetLike:
        return cast(
            ResultSetLike,
            self._sdk.query_history_k_data_plus(
                code,
                fields,
                start_date=start_date,
                end_date=end_date,
                frequency=frequency,
                adjustflag=adjustflag,
            ),
        )


class BaoStockProvider:
    """Default zero-registration daily data Provider."""

    metadata = ProviderMetadata(
        provider_id="baostock",
        name="BaoStock",
        version="1.0.0",
        description="免费、匿名登录的沪深 A 股基础数据源。",
        plugin_api_version="1.0",
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
        gateway: BaoStockGateway | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._gateway_override = gateway
        self._clock = clock or (lambda: datetime.now(UTC))

    def healthcheck(self) -> ProviderHealth:
        started = perf_counter()
        try:
            gateway = self._gateway()
            login_result = gateway.login()
            ok = login_result.error_code == "0"
            message = "连接正常" if ok else "匿名登录失败"
            if ok:
                gateway.logout()
        except ProviderError as error:
            ok = False
            message = str(error)
        latency_ms = round((perf_counter() - started) * 1000)
        return ProviderHealth(
            provider_id=self.metadata.provider_id,
            ok=ok,
            checked_at=self._clock(),
            message=message,
            latency_ms=latency_ms,
        )

    def fetch_instruments(self, as_of: date) -> DataBatch[Instrument]:
        request: dict[str, RequestScalar] = {"as_of": as_of.isoformat()}
        with self._authenticated_gateway() as gateway:
            result = gateway.query_all_stock(as_of.isoformat())
            rows = self._read_rows(result)

        records = tuple(
            Instrument(
                symbol=row["code"].lower(),
                name=row["code_name"],
                is_active=row["tradeStatus"] == "1",
            )
            for row in rows
            if _is_a_share_code(row.get("code", "").lower())
            and row.get("code_name", "").strip()
        )
        return self._batch(Dataset.INSTRUMENTS, request, rows, records)

    def fetch_calendar(
        self,
        start: date,
        end: date,
    ) -> DataBatch[TradingSession]:
        request: dict[str, RequestScalar] = {
            "start": start.isoformat(),
            "end": end.isoformat(),
        }
        with self._authenticated_gateway() as gateway:
            result = gateway.query_trade_dates(start.isoformat(), end.isoformat())
            rows = self._read_rows(result)

        records = tuple(
            TradingSession(
                trade_date=date.fromisoformat(row["calendar_date"]),
                is_open=row["is_trading_day"] == "1",
            )
            for row in rows
        )
        return self._batch(Dataset.TRADING_CALENDAR, request, rows, records)

    def fetch_daily_bars(
        self,
        symbols: tuple[str, ...],
        start: date,
        end: date,
        adjustment: Adjustment,
    ) -> DataBatch[DailyBar]:
        request: dict[str, RequestScalar] = {
            "symbols": ",".join(symbols),
            "start": start.isoformat(),
            "end": end.isoformat(),
            "adjustment": adjustment.value,
        }
        rows: list[dict[str, str]] = []
        with self._authenticated_gateway() as gateway:
            for symbol in symbols:
                result = gateway.query_history_k_data_plus(
                    symbol,
                    DAILY_FIELDS,
                    start_date=start.isoformat(),
                    end_date=end.isoformat(),
                    frequency="d",
                    adjustflag=ADJUSTMENT_FLAGS[adjustment],
                )
                rows.extend(self._read_rows(result))

        records: list[DailyBar] = []
        for row in rows:
            if row.get("tradestatus") != "1":
                continue
            numeric_fields = ("open", "high", "low", "close", "volume", "amount")
            if any(not row.get(field, "").strip() for field in numeric_fields):
                continue
            records.append(
                DailyBar(
                    symbol=row["code"].lower(),
                    trade_date=date.fromisoformat(row["date"]),
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=int(float(row["volume"])),
                    amount=float(row["amount"]),
                    is_trading=True,
                    is_st=row.get("isST") == "1",
                )
            )
        return self._batch(Dataset.DAILY_BARS, request, rows, tuple(records))

    def _gateway(self) -> BaoStockGateway:
        return self._gateway_override or BaoStockSdkGateway()

    @contextmanager
    def _authenticated_gateway(self) -> Iterator[BaoStockGateway]:
        gateway = self._gateway()
        login_result = gateway.login()
        if login_result.error_code != "0":
            raise ProviderError(
                provider_id=self.metadata.provider_id,
                error_code="authentication_failed",
                message="BaoStock 匿名登录失败。",
                retryable=True,
            )
        try:
            yield gateway
        finally:
            gateway.logout()

    def _read_rows(self, result: ResultSetLike) -> list[dict[str, str]]:
        if result.error_code != "0":
            raise ProviderError(
                provider_id=self.metadata.provider_id,
                error_code="upstream_query_failed",
                message=f"BaoStock 查询失败：{result.error_msg}",
                retryable=True,
            )

        rows: list[dict[str, str]] = []
        while result.error_code == "0" and result.next():
            values = result.get_row_data()
            rows.append(dict(zip(result.fields, values, strict=True)))
        if result.error_code != "0":
            raise ProviderError(
                provider_id=self.metadata.provider_id,
                error_code="upstream_query_failed",
                message=f"BaoStock 分页查询失败：{result.error_msg}",
                retryable=True,
            )
        return rows

    def _batch[RecordT](
        self,
        dataset: Dataset,
        request: dict[str, RequestScalar],
        raw_rows: list[dict[str, str]],
        records: tuple[RecordT, ...],
    ) -> DataBatch[RecordT]:
        content_hash = _canonical_hash(
            {
                "dataset": dataset,
                "request": request,
                "rows": raw_rows,
            }
        )
        return DataBatch[RecordT](
            dataset=dataset,
            provider_id=self.metadata.provider_id,
            provider_version=self.metadata.version,
            fetched_at=self._clock(),
            request=request,
            source_batch_id=f"baostock-{content_hash[:20]}",
            content_hash=content_hash,
            records=records,
        )


def _is_a_share_code(symbol: str) -> bool:
    if len(symbol) != 9 or symbol[2] != "." or not symbol[3:].isdigit():
        return False
    code = symbol[3:]
    if symbol.startswith("sh."):
        return code.startswith(("600", "601", "603", "605", "688", "689"))
    if symbol.startswith("sz."):
        return code.startswith(("000", "001", "002", "003", "300", "301"))
    if symbol.startswith("bj."):
        return code.startswith(("4", "8", "9"))
    return False


def _canonical_hash(value: object) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()
