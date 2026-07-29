"""Synthetic daily bars that require no network or market-data license."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta

from asharelens.core.models import DailyBar


def _weekday_sessions(start: date, count: int) -> tuple[date, ...]:
    sessions: list[date] = []
    current = start
    while len(sessions) < count:
        if current.weekday() < 5:
            sessions.append(current)
        current += timedelta(days=1)
    return tuple(sessions)


def _rising_close(index: int) -> float:
    return 10 + index * 0.08


def _falling_close(index: int) -> float:
    return 18 - index * 0.06


def _oscillating_close(index: int) -> float:
    return 13 + ((index % 20) - 10) * 0.04 + index * 0.005


def _build_symbol_bars(
    symbol: str,
    sessions: tuple[date, ...],
    close_path: Callable[[int], float],
    volume_offset: int,
) -> tuple[DailyBar, ...]:
    observations: list[DailyBar] = []
    for index, trade_date in enumerate(sessions):
        close = round(close_path(index), 2)
        open_price = round(close * (1.001 if index % 2 == 0 else 0.999), 2)
        high = round(max(open_price, close) + 0.05, 2)
        low = round(min(open_price, close) - 0.05, 2)
        volume = 100_000 + volume_offset + index * 250
        observations.append(
            DailyBar(
                symbol=symbol,
                trade_date=trade_date,
                open=open_price,
                high=high,
                low=low,
                close=close,
                volume=volume,
                amount=round(volume * close, 2),
            )
        )
    return tuple(observations)


def generate_demo_bars(
    start: date,
    sessions: int,
) -> dict[str, tuple[DailyBar, ...]]:
    """Generate rising, falling, and oscillating symbols deterministically."""

    if sessions <= 0:
        raise ValueError("sessions must be positive")

    trading_dates = _weekday_sessions(start, sessions)
    return {
        "demo.000001": _build_symbol_bars(
            "demo.000001", trading_dates, _rising_close, volume_offset=10_000
        ),
        "demo.000002": _build_symbol_bars(
            "demo.000002", trading_dates, _falling_close, volume_offset=20_000
        ),
        "demo.000003": _build_symbol_bars(
            "demo.000003", trading_dates, _oscillating_close, volume_offset=30_000
        ),
    }
