"""Shared chronological engine for backtests and daily paper portfolios."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date

from pydantic import BaseModel

from asharelens.core.execution import (
    Fill,
    OpeningExecutionModel,
    Order,
    OrderRejected,
    Side,
)
from asharelens.core.fingerprint import build_run_fingerprint
from asharelens.core.models import DailyBar, SelectionCandidate, StrategyContext
from asharelens.core.portfolio import build_equal_weight_targets
from asharelens.core.strategy import StrategyPlugin

ENGINE_VERSION = "0.1.0"

@dataclass(frozen=True, slots=True)
class Position:
    """End-of-session position state."""

    quantity: int
    average_cost: float


@dataclass(frozen=True, slots=True)
class PortfolioState:
    """Serializable state carried from one trading session to the next."""

    cash: float
    positions: dict[str, Position]
    pending_orders: tuple[Order, ...]


@dataclass(frozen=True, slots=True)
class NavPoint:
    """One close-to-close portfolio valuation."""

    trade_date: date
    cash: float
    market_value: float
    total_value: float


@dataclass(frozen=True, slots=True)
class SessionOutcome:
    """Observable effects of one invocation of the daily cycle."""

    state: PortfolioState
    candidates: tuple[SelectionCandidate, ...]
    orders: tuple[Order, ...]
    fills: tuple[Fill, ...]
    nav: NavPoint


@dataclass(frozen=True, slots=True)
class BacktestResult:
    """Immutable ledgers returned by a historical run."""

    candidates: tuple[SelectionCandidate, ...]
    orders: tuple[Order, ...]
    fills: tuple[Fill, ...]
    nav: tuple[NavPoint, ...]
    fingerprint: str


class DailyCycleEngine[ParamsT: BaseModel]:
    """Run the same point-in-time session transition in history or each day."""

    def __init__(
        self,
        *,
        strategy: StrategyPlugin[ParamsT],
        params: ParamsT,
        execution_model: OpeningExecutionModel,
        initial_cash: float,
        top_n: int,
        max_weight: float,
    ) -> None:
        if initial_cash <= 0:
            raise ValueError("initial_cash must be positive")
        if top_n <= 0:
            raise ValueError("top_n must be positive")
        if not 0 < max_weight <= 1:
            raise ValueError("max_weight must be in (0, 1]")

        self.strategy = strategy
        self.params = params
        self.execution_model = execution_model
        self.initial_cash = round(initial_cash, 2)
        self.top_n = top_n
        self.max_weight = max_weight

    def initial_state(self) -> PortfolioState:
        """Create an empty portfolio suitable for the first session."""

        return PortfolioState(cash=self.initial_cash, positions={}, pending_orders=())

    def process_session(
        self,
        state: PortfolioState,
        session_date: date,
        history: Mapping[str, tuple[DailyBar, ...]],
    ) -> SessionOutcome:
        """Advance one session: fills first, close signal second."""

        session_bars = {
            symbol: observations[-1]
            for symbol, observations in history.items()
            if observations and observations[-1].trade_date == session_date
        }
        cash, positions, fills = self._execute_pending(
            state.cash,
            state.positions,
            state.pending_orders,
            session_bars,
        )
        latest_prices = {
            symbol: observations[-1].close
            for symbol, observations in history.items()
            if observations
        }
        nav = self._value_portfolio(session_date, cash, positions, latest_prices)

        context = StrategyContext(signal_date=session_date, bars=dict(history))
        candidates = self.strategy.generate(context, self.params)
        targets = build_equal_weight_targets(
            candidates,
            top_n=self.top_n,
            max_weight=self.max_weight,
        )
        orders = self._build_orders(
            session_date,
            nav.total_value,
            positions,
            targets,
            latest_prices,
        )
        next_state = PortfolioState(
            cash=cash,
            positions=positions,
            pending_orders=orders,
        )
        return SessionOutcome(
            state=next_state,
            candidates=candidates,
            orders=orders,
            fills=fills,
            nav=nav,
        )

    def run(
        self,
        bars: Mapping[str, tuple[DailyBar, ...]],
    ) -> BacktestResult:
        """Run all available sessions in chronological order."""

        session_dates = sorted(
            {bar.trade_date for observations in bars.values() for bar in observations}
        )
        if not session_dates:
            raise ValueError("market data must not be empty")

        state = self.initial_state()
        candidate_ledger: list[SelectionCandidate] = []
        order_ledger: list[Order] = []
        fill_ledger: list[Fill] = []
        nav_ledger: list[NavPoint] = []

        for session_date in session_dates:
            history = {
                symbol: tuple(bar for bar in observations if bar.trade_date <= session_date)
                for symbol, observations in bars.items()
            }
            outcome = self.process_session(state, session_date, history)
            state = outcome.state
            candidate_ledger.extend(outcome.candidates)
            order_ledger.extend(outcome.orders)
            fill_ledger.extend(outcome.fills)
            nav_ledger.append(outcome.nav)

        strategy_identity = hashlib.sha256(
            (
                f"{self.strategy.metadata.strategy_id}:"
                f"{self.strategy.metadata.version}"
            ).encode()
        ).hexdigest()
        fingerprint = build_run_fingerprint(
            strategy_identity,
            self.params.model_dump(mode="json"),
            build_data_snapshot_id(bars),
            ENGINE_VERSION,
        )
        return BacktestResult(
            candidates=tuple(candidate_ledger),
            orders=tuple(order_ledger),
            fills=tuple(fill_ledger),
            nav=tuple(nav_ledger),
            fingerprint=fingerprint,
        )

    def _execute_pending(
        self,
        cash: float,
        positions: Mapping[str, Position],
        pending_orders: tuple[Order, ...],
        session_bars: Mapping[str, DailyBar],
    ) -> tuple[float, dict[str, Position], tuple[Fill, ...]]:
        next_cash = cash
        next_positions = dict(positions)
        fills: list[Fill] = []
        ordered = sorted(
            pending_orders,
            key=lambda order: (0 if order.side is Side.SELL else 1, order.symbol),
        )

        for order in ordered:
            bar = session_bars.get(order.symbol)
            if order.side is Side.SELL:
                position = next_positions.get(order.symbol)
                if position is None:
                    continue
                quantity = min(order.quantity, position.quantity)
                executable = Order(order.symbol, order.side, quantity, order.signal_date)
                try:
                    fill = self.execution_model.execute(executable, bar)
                except OrderRejected:
                    continue
                next_cash = round(next_cash + fill.cash_delta, 2)
                remaining = position.quantity - fill.quantity
                if remaining == 0:
                    del next_positions[order.symbol]
                else:
                    next_positions[order.symbol] = Position(
                        quantity=remaining,
                        average_cost=position.average_cost,
                    )
                fills.append(fill)
                continue

            buy_fill = self._affordable_buy(order, bar, next_cash)
            if buy_fill is None:
                continue
            previous = next_positions.get(order.symbol)
            previous_quantity = previous.quantity if previous else 0
            previous_cost = (
                previous.average_cost * previous.quantity if previous is not None else 0
            )
            total_cost = previous_cost - buy_fill.cash_delta
            new_quantity = previous_quantity + buy_fill.quantity
            next_positions[order.symbol] = Position(
                quantity=new_quantity,
                average_cost=round(total_cost / new_quantity, 6),
            )
            next_cash = round(next_cash + buy_fill.cash_delta, 2)
            fills.append(buy_fill)

        return next_cash, next_positions, tuple(fills)

    def _affordable_buy(
        self,
        order: Order,
        bar: DailyBar | None,
        cash: float,
    ) -> Fill | None:
        quantity = order.quantity // self.execution_model.board_lot * self.execution_model.board_lot
        while quantity > 0:
            executable = Order(order.symbol, order.side, quantity, order.signal_date)
            try:
                fill = self.execution_model.execute(executable, bar)
            except OrderRejected:
                return None
            if -fill.cash_delta <= cash:
                return fill
            quantity -= self.execution_model.board_lot
        return None

    def _build_orders(
        self,
        signal_date: date,
        nav: float,
        positions: Mapping[str, Position],
        targets: Mapping[str, float],
        prices: Mapping[str, float],
    ) -> tuple[Order, ...]:
        orders: list[Order] = []
        symbols = sorted(set(positions) | set(targets))
        for symbol in symbols:
            price = prices.get(symbol)
            if price is None:
                continue
            target_value = nav * targets.get(symbol, 0)
            desired_quantity = (
                int(target_value / price)
                // self.execution_model.board_lot
                * self.execution_model.board_lot
            )
            current_quantity = positions.get(symbol, Position(0, 0)).quantity
            difference = desired_quantity - current_quantity
            if difference > 0:
                orders.append(Order(symbol, Side.BUY, difference, signal_date))
            elif difference < 0:
                orders.append(Order(symbol, Side.SELL, -difference, signal_date))

        return tuple(
            sorted(
                orders,
                key=lambda order: (0 if order.side is Side.SELL else 1, order.symbol),
            )
        )

    @staticmethod
    def _value_portfolio(
        trade_date: date,
        cash: float,
        positions: Mapping[str, Position],
        prices: Mapping[str, float],
    ) -> NavPoint:
        market_value = round(
            sum(
                position.quantity * prices[symbol]
                for symbol, position in positions.items()
                if symbol in prices
            ),
            2,
        )
        return NavPoint(
            trade_date=trade_date,
            cash=round(cash, 2),
            market_value=market_value,
            total_value=round(cash + market_value, 2),
        )


def build_data_snapshot_id(
    bars: Mapping[str, tuple[DailyBar, ...]],
) -> str:
    """Hash the exact point-in-time normalized market-data snapshot."""

    payload = {
        symbol: [bar.model_dump(mode="json") for bar in observations]
        for symbol, observations in sorted(bars.items())
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()
