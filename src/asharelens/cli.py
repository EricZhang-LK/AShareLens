"""Command-line entry points for SDK users and offline demonstrations."""

from __future__ import annotations

import json
from datetime import date
from typing import Annotated

import typer

from asharelens.core.engine import DailyCycleEngine
from asharelens.core.execution import OpeningExecutionModel
from asharelens.demo.data import generate_demo_bars
from asharelens.strategies.moving_average import (
    MovingAverageParams,
    MovingAverageStrategy,
)

app = typer.Typer(
    name="asharelens",
    help="AShareLens 本地 A 股量化选股平台。",
    no_args_is_help=True,
)


@app.callback()
def main() -> None:
    """AShareLens 命令组。"""


@app.command()
def demo(
    as_json: Annotated[
        bool,
        typer.Option("--json", help="输出稳定的机器可读 JSON。"),
    ] = False,
) -> None:
    """运行不需要网络和账号的选股、回测与模拟成交闭环。"""

    sessions = 80
    initial_cash = 100_000.0
    bars = generate_demo_bars(date(2026, 1, 5), sessions=sessions)
    engine = DailyCycleEngine(
        strategy=MovingAverageStrategy(),
        params=MovingAverageParams(fast_period=10, slow_period=30, confirm_days=3),
        execution_model=OpeningExecutionModel(),
        initial_cash=initial_cash,
        top_n=1,
        max_weight=1,
    )
    result = engine.run(bars)
    final_nav = result.nav[-1].total_value
    payload = {
        "data_source": "deterministic_synthetic",
        "fills": len(result.fills),
        "final_nav": final_nav,
        "fingerprint": result.fingerprint,
        "initial_cash": initial_cash,
        "orders": len(result.orders),
        "sessions": sessions,
        "signals": sum(candidate.selected for candidate in result.candidates),
        "strategy": "moving_average",
        "total_return_pct": round((final_nav / initial_cash - 1) * 100, 4),
    }

    if as_json:
        typer.echo(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return

    typer.echo("AShareLens 离线演示")
    typer.echo("数据：确定性合成数据（不联网、不包含真实行情）")
    typer.echo(f"策略：均线趋势；交易日：{sessions}")
    typer.echo(f"选中信号：{payload['signals']}；模拟成交：{payload['fills']}")
    typer.echo(
        f"初始资金：{initial_cash:.2f}；期末净值：{final_nav:.2f}；"
        f"收益率：{payload['total_return_pct']:.4f}%"
    )
    typer.echo(f"运行指纹：{result.fingerprint}")
    typer.echo("本结果只用于软件功能演示，不构成投资建议。")


if __name__ == "__main__":
    app()
