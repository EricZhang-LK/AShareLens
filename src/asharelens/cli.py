"""Command-line entry points for SDK users and offline demonstrations."""

from __future__ import annotations

import json
import os
import socket
from datetime import UTC, date, datetime
from typing import Annotated

import typer
from alembic.migration import MigrationContext
from sqlalchemy import func, select
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError, SQLAlchemyError

from asharelens.core.engine import DailyCycleEngine
from asharelens.core.execution import OpeningExecutionModel
from asharelens.data.provider import DataProviderPlugin
from asharelens.data.providers.baostock import BaoStockProvider
from asharelens.demo.data import generate_demo_bars
from asharelens.runner.executor import ExecutorRegistry
from asharelens.runner.models import JobStatus
from asharelens.runner.runtime import run_until_stopped
from asharelens.runner.scheduler import PersistentScheduler
from asharelens.runner.worker import Reaper, Worker, WorkerRun
from asharelens.storage.database import (
    create_database_engine,
    create_session_factory,
)
from asharelens.storage.models import RunnerJobRow
from asharelens.strategies.moving_average import (
    MovingAverageParams,
    MovingAverageStrategy,
)

app = typer.Typer(
    name="asharelens",
    help="AShareLens 本地 A 股量化选股平台。",
    no_args_is_help=True,
)
provider_app = typer.Typer(help="查看和诊断市场数据源。")
app.add_typer(provider_app, name="provider")
database_app = typer.Typer(help="检查持久化数据库和迁移版本。")
app.add_typer(database_app, name="database")
runner_app = typer.Typer(help="运行持久任务、日程和失联任务回收。")
app.add_typer(runner_app, name="runner")


@app.callback()
def main() -> None:
    """AShareLens 命令组。"""


def _provider_registry() -> dict[str, DataProviderPlugin]:
    return {"baostock": BaoStockProvider()}


@provider_app.command("list")
def provider_list() -> None:
    """列出内置 Provider，不连接外部服务。"""

    for provider_id, provider in sorted(_provider_registry().items()):
        registration = "需要注册" if provider.metadata.requires_registration else "免注册"
        default_label = "默认" if provider_id == "baostock" else "备用"
        typer.echo(
            f"{provider_id} | {default_label} | {registration} | "
            '可选安装：pip install "asharelens[baostock]"'
        )


@provider_app.command("check")
def provider_check(provider_id: str) -> None:
    """执行一次脱敏的 Provider 健康检查。"""

    provider = _provider_registry().get(provider_id)
    if provider is None:
        typer.echo(f"未知数据源：{provider_id}")
        raise typer.Exit(code=2)

    health = provider.healthcheck()
    status = "正常" if health.ok else "失败"
    latency = f"{health.latency_ms}ms" if health.latency_ms is not None else "未记录"
    typer.echo(f"{provider_id} | {status} | {latency} | {health.message}")
    if not health.ok:
        raise typer.Exit(code=1)


@database_app.command("check")
def database_check(
    url: Annotated[
        str | None,
        typer.Option("--url", help="覆盖 ASHARELENS_DATABASE_URL。"),
    ] = None,
) -> None:
    """检查连接并输出脱敏 URL 和当前 Alembic revision。"""

    database_url = (
        url
        or os.getenv("ASHARELENS_DATABASE_URL")
        or "sqlite+pysqlite:///./asharelens.db"
    )
    try:
        parsed = make_url(database_url)
    except (ArgumentError, ValueError):
        typer.echo("数据库 URL 无效。")
        raise typer.Exit(code=1) from None
    sanitized = parsed.render_as_string(hide_password=True)

    try:
        engine = create_database_engine(database_url)
        with engine.connect() as connection:
            revision = MigrationContext.configure(connection).get_current_revision()
        engine.dispose()
    except (SQLAlchemyError, OSError):
        typer.echo(f"{sanitized} | 连接失败")
        raise typer.Exit(code=1) from None

    revision_label = revision or "未迁移"
    typer.echo(f"{sanitized} | {parsed.get_backend_name()} | 正常 | {revision_label}")


@runner_app.command("doctor")
def runner_doctor(
    url: Annotated[
        str | None,
        typer.Option("--url", help="覆盖 ASHARELENS_DATABASE_URL。"),
    ] = None,
) -> None:
    """检查 Runner 数据库、迁移版本和待处理任务数。"""

    database_url = _database_url(url)
    parsed = _parse_database_url(database_url)
    sanitized = parsed.render_as_string(hide_password=True)
    engine = create_database_engine(database_url)
    try:
        with engine.connect() as connection:
            revision = MigrationContext.configure(connection).get_current_revision()
            pending = connection.scalar(
                select(func.count())
                .select_from(RunnerJobRow)
                .where(
                    RunnerJobRow.status.in_(
                        (JobStatus.QUEUED.value, JobStatus.RETRY_WAIT.value)
                    )
                )
            )
    except (SQLAlchemyError, OSError):
        typer.echo(f"{sanitized} | Runner 连接失败")
        raise typer.Exit(code=1) from None
    finally:
        engine.dispose()
    typer.echo(
        f"Runner 正常 | {parsed.get_backend_name()} | "
        f"迁移 {revision or '未迁移'} | 待处理 {pending or 0}"
    )


@runner_app.command("work")
def runner_work(
    once: Annotated[
        bool,
        typer.Option("--once", help="最多处理一个任务后退出。"),
    ] = False,
    url: Annotated[
        str | None,
        typer.Option("--url", help="覆盖 ASHARELENS_DATABASE_URL。"),
    ] = None,
    queue: Annotated[
        str,
        typer.Option("--queue", help="只领取指定队列。"),
    ] = "default",
    poll_seconds: Annotated[
        float,
        typer.Option("--poll-seconds", min=0.05, help="空闲轮询间隔。"),
    ] = 1.0,
) -> None:
    """领取并执行持久任务；默认持续运行。"""

    engine = create_database_engine(_database_url(url))
    factory = create_session_factory(engine)
    worker = Worker(
        session_factory=factory,
        registry=ExecutorRegistry(),
        worker_id=f"{socket.gethostname()}-{os.getpid()}",
        queue=queue,
    )
    try:
        if once:
            _echo_worker_run(worker.run_once())
            return

        def work_once() -> None:
            run = worker.run_once()
            if run.job_id is not None:
                _echo_worker_run(run)

        run_until_stopped(work_once, poll_seconds=poll_seconds)
    finally:
        engine.dispose()


@runner_app.command("start")
def runner_start(
    once: Annotated[
        bool,
        typer.Option("--once", help="协调一个完整轮次后退出。"),
    ] = False,
    url: Annotated[
        str | None,
        typer.Option("--url", help="覆盖 ASHARELENS_DATABASE_URL。"),
    ] = None,
    queue: Annotated[
        str,
        typer.Option("--queue", help="只领取指定队列。"),
    ] = "default",
    poll_seconds: Annotated[
        float,
        typer.Option("--poll-seconds", min=0.05, help="协调循环间隔。"),
    ] = 1.0,
) -> None:
    """在一个进程中协调 Scheduler、Reaper 和 Worker。"""

    engine = create_database_engine(_database_url(url))
    factory = create_session_factory(engine)
    worker = Worker(
        session_factory=factory,
        registry=ExecutorRegistry(),
        worker_id=f"{socket.gethostname()}-{os.getpid()}",
        queue=queue,
    )
    reaper = Reaper(session_factory=factory)

    def run_cycle() -> None:
        with factory.begin() as session:
            tick = PersistentScheduler(session).run_due(now=_utc_now_naive())
        reaped = reaper.run_once()
        run = worker.run_once()
        typer.echo(
            f"Runner 轮次 | 投递 {len(tick.enqueued)} | 回收 {reaped} | "
            f"Worker {run.outcome.value}"
        )

    try:
        if once:
            run_cycle()
            return
        run_until_stopped(run_cycle, poll_seconds=poll_seconds)
    finally:
        engine.dispose()


@runner_app.command("schedule")
def runner_schedule(
    once: Annotated[
        bool,
        typer.Option("--once", help="扫描一次到期日程后退出。"),
    ] = False,
    url: Annotated[
        str | None,
        typer.Option("--url", help="覆盖 ASHARELENS_DATABASE_URL。"),
    ] = None,
    poll_seconds: Annotated[
        float,
        typer.Option("--poll-seconds", min=0.05, help="日程扫描间隔。"),
    ] = 5.0,
) -> None:
    """将到期日程幂等地投递到持久队列。"""

    engine = create_database_engine(_database_url(url))
    factory = create_session_factory(engine)

    def schedule_once() -> None:
        with factory.begin() as session:
            tick = PersistentScheduler(session).run_due(now=_utc_now_naive())
        typer.echo(f"日程扫描完成 | 投递 {len(tick.enqueued)}")

    try:
        if once:
            schedule_once()
            return
        run_until_stopped(schedule_once, poll_seconds=poll_seconds)
    finally:
        engine.dispose()


@runner_app.command("reap")
def runner_reap(
    once: Annotated[
        bool,
        typer.Option("--once", help="回收一次过期租约后退出。"),
    ] = False,
    url: Annotated[
        str | None,
        typer.Option("--url", help="覆盖 ASHARELENS_DATABASE_URL。"),
    ] = None,
    poll_seconds: Annotated[
        float,
        typer.Option("--poll-seconds", min=0.05, help="租约回收间隔。"),
    ] = 30.0,
) -> None:
    """恢复失联 Worker 遗留的过期任务。"""

    engine = create_database_engine(_database_url(url))
    reaper = Reaper(session_factory=create_session_factory(engine))

    def reap_once() -> None:
        typer.echo(f"租约扫描完成 | 回收 {reaper.run_once()}")

    try:
        if once:
            reap_once()
            return
        run_until_stopped(reap_once, poll_seconds=poll_seconds)
    finally:
        engine.dispose()


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


def _database_url(override: str | None) -> str:
    return (
        override
        or os.getenv("ASHARELENS_DATABASE_URL")
        or "sqlite+pysqlite:///./asharelens.db"
    )


def _parse_database_url(database_url: str) -> URL:
    try:
        return make_url(database_url)
    except (ArgumentError, ValueError):
        typer.echo("数据库 URL 无效。")
        raise typer.Exit(code=1) from None


def _echo_worker_run(run: WorkerRun) -> None:
    job = run.job_id or "无"
    job_type = run.job_type or "无"
    typer.echo(f"Worker | {run.outcome.value} | 任务 {job} | 类型 {job_type}")


def _utc_now_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


if __name__ == "__main__":
    app()
