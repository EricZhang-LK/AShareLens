from datetime import date

from asharelens.core.engine import NavPoint, PortfolioState
from asharelens.core.execution import Order, Side
from asharelens.core.models import SelectionCandidate, SelectionReason
from asharelens.notifications.models import MessageFormat
from asharelens.notifications.render import render_daily_selection
from asharelens.storage.simulation_repository import SimulationRunSnapshot


def _run() -> SimulationRunSnapshot:
    empty = PortfolioState(cash=100_000, positions={}, pending_orders=())
    return SimulationRunSnapshot(
        id="run-1",
        account_id="account-1",
        session_date=date(2026, 7, 29),
        fingerprint="a" * 64,
        strategy_id="moving_average",
        strategy_version="1.0.0",
        engine_version="0.1.0",
        parameters={"fast_period": 20},
        data_snapshot_id="b" * 64,
        partition_ids=("partition-1",),
        input_state=empty,
        input_state_hash="c" * 64,
        output_state=empty,
        output_state_hash="d" * 64,
        candidates=(
            SelectionCandidate(
                symbol="sh.600000",
                signal_date=date(2026, 7, 29),
                selected=True,
                score=0.9,
                rank=1,
                reasons=(
                    SelectionReason(
                        code="ma_trend_confirmed",
                        message="短期均线持续高于长期均线。",
                    ),
                ),
            ),
            SelectionCandidate(
                symbol="sz.000001",
                signal_date=date(2026, 7, 29),
                selected=False,
                score=0.2,
                rank=2,
                reasons=(
                    SelectionReason(
                        code="ma_trend_not_confirmed",
                        message="趋势尚未确认。",
                    ),
                ),
            ),
        ),
        orders=(
            Order(
                symbol="sh.600000",
                side=Side.BUY,
                quantity=1000,
                signal_date=date(2026, 7, 29),
            ),
        ),
        fills=(),
        nav=NavPoint(
            trade_date=date(2026, 7, 29),
            cash=100_000,
            market_value=0,
            total_value=100_000,
        ),
    )


def test_daily_selection_renderer_is_deterministic_and_complete() -> None:
    first = render_daily_selection(account_name="演示组合", run=_run())
    second = render_daily_selection(account_name="演示组合", run=_run())

    assert first == second
    assert first.format is MessageFormat.MARKDOWN
    assert first.title == "AShareLens 每日选股 | 2026-07-29"
    assert "入选 1 / 候选 2 / 排除 1" in first.body
    assert "sh.600000" in first.body
    assert "短期均线持续高于长期均线" in first.body
    assert "D+1 待执行订单" in first.body
    assert "买入 1,000 股" in first.body
    assert "a" * 64 in first.body
    assert "不构成投资建议" in first.body
    assert "sz.000001" not in first.body
