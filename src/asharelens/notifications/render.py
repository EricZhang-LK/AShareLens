"""Deterministic Chinese renderers for persisted simulation results."""

from __future__ import annotations

from asharelens.core.execution import Side
from asharelens.notifications.models import MessageFormat, NotificationMessage
from asharelens.storage.simulation_repository import SimulationRunSnapshot


def render_daily_selection(
    *,
    account_name: str,
    run: SimulationRunSnapshot,
) -> NotificationMessage:
    """Render an explainable Markdown summary without recomputing signals."""

    selected = tuple(
        sorted(
            (candidate for candidate in run.candidates if candidate.selected),
            key=lambda candidate: (
                candidate.rank if candidate.rank is not None else 10**9,
                candidate.symbol,
            ),
        )
    )
    excluded_count = len(run.candidates) - len(selected)
    lines = [
        "# AShareLens 每日选股",
        "",
        f"- 组合：{account_name}",
        f"- 交易日：{run.session_date.isoformat()}",
        f"- 策略：{run.strategy_id} v{run.strategy_version}",
        (
            f"- 结果：入选 {len(selected)} / 候选 {len(run.candidates)} "
            f"/ 排除 {excluded_count}"
        ),
        f"- 组合净值：{run.nav.total_value:,.2f}",
        "",
        "## 入选股票",
        "",
    ]
    if selected:
        for candidate in selected:
            rank = candidate.rank if candidate.rank is not None else "-"
            reason = (
                candidate.reasons[0].message
                if candidate.reasons
                else "策略未提供文字理由。"
            )
            lines.append(
                f"{rank}. `{candidate.symbol}` | 得分 {candidate.score:.4f} | {reason}"
            )
    else:
        lines.append("本次没有股票通过策略条件。")

    lines.extend(["", "## D+1 待执行订单", ""])
    if run.orders:
        for order in run.orders:
            side = "买入" if order.side is Side.BUY else "卖出"
            lines.append(
                f"- `{order.symbol}`：{side} {order.quantity:,} 股"
            )
    else:
        lines.append("无待执行订单。")

    lines.extend(
        [
            "",
            "## 可复现信息",
            "",
            f"- 运行指纹：`{run.fingerprint}`",
            f"- 数据快照：`{run.data_snapshot_id}`",
            "",
            "> 本消息仅用于量化研究与软件功能展示，不构成投资建议。",
        ]
    )
    return NotificationMessage(
        title=f"AShareLens 每日选股 | {run.session_date.isoformat()}",
        body="\n".join(lines),
        format=MessageFormat.MARKDOWN,
    )
