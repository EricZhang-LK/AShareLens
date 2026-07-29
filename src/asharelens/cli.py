"""Chinese-first operator and offline demonstration commands."""

from __future__ import annotations

import hashlib
import json
import os
import socket
from datetime import UTC, date, datetime
from typing import Annotated

import typer
from alembic.migration import MigrationContext
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.engine import URL, Engine, make_url
from sqlalchemy.exc import ArgumentError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from asharelens.config import RuntimeSettings
from asharelens.core.engine import DailyCycleEngine
from asharelens.core.execution import OpeningExecutionModel
from asharelens.data.provider import DataProviderPlugin
from asharelens.data.providers.akshare import AkShareProvider
from asharelens.data.providers.baostock import BaoStockProvider
from asharelens.data.providers.tushare import TushareProvider
from asharelens.demo.data import generate_demo_bars
from asharelens.runner.executor import ExecutorRegistry
from asharelens.runner.job_repository import JobRepository
from asharelens.runner.models import JobStatus
from asharelens.runner.runtime import run_until_stopped
from asharelens.runner.scheduler import PersistentScheduler, ScheduleConflict
from asharelens.runner.worker import Reaper, Worker, WorkerRun
from asharelens.runner.workflows.daily_pipeline import DailyPipelineRequest
from asharelens.runner.workflows.market_sync import MarketSyncFailure
from asharelens.runtime import (
    RuntimeConfigurationError,
    build_daily_pipeline_service,
    build_executor_registry,
)
from asharelens.storage.database import (
    create_database_engine,
    create_session_factory,
)
from asharelens.storage.models import RunnerJobRow
from asharelens.strategies.moving_average import (
    MovingAverageParams,
    MovingAverageStrategy,
)

CURRENT_SCHEMA_REVISION = "20260730_0006"

app = typer.Typer(
    name="asharelens",
    help="AShareLens 本地 A 股量化选股平台。",
    no_args_is_help=True,
)
provider_app = typer.Typer(help="查看和诊断市场数据源。")
database_app = typer.Typer(help="检查持久化数据库和迁移版本。")
runner_app = typer.Typer(help="运行持久任务、日程和失联任务回收。")
app.add_typer(provider_app, name="provider")
app.add_typer(database_app, name="database")
app.add_typer(runner_app, name="runner")


@app.callback()
def main() -> None:
    """AShareLens 命令组。"""


@app.command("web")
def web_server(
    host: Annotated[
        str,
        typer.Option("--host", help="监听地址；默认仅本机可访问。"),
    ] = "127.0.0.1",
    port: Annotated[
        int,
        typer.Option("--port", min=1, max=65535, help="监听端口。"),
    ] = 8000,
    reload: Annotated[
        bool,
        typer.Option("--reload", help="开发时监视 Python 文件变更。"),
    ] = False,
    allow_network: Annotated[
        bool,
        typer.Option("--allow-network", help="明确允许绑定非回环地址。"),
    ] = False,
) -> None:
    """启动同源 Web 研究台和版本化 API。"""

    if host not in {"127.0.0.1", "::1", "localhost"} and not allow_network:
        typer.echo("拒绝监听非本机地址；如确有需要，请增加 --allow-network。")
        raise typer.Exit(code=2)
    try:
        import uvicorn
    except ImportError:
        typer.echo('Web 依赖未安装；请执行 pip install "asharelens[server]"。')
        raise typer.Exit(code=1) from None

    typer.echo(f"AShareLens Web：http://{host}:{port}")
    uvicorn.run(
        "asharelens.server.app:app",
        host=host,
        port=port,
        reload=reload,
    )


def _provider_registry() -> dict[str, DataProviderPlugin]:
    return {
        "baostock": BaoStockProvider(),
        "akshare": AkShareProvider(),
        "tushare": TushareProvider(),
    }


@provider_app.command("list")
def provider_list() -> None:
    """列出内置 Provider，不连接外部服务。"""

    labels = {"baostock": "默认", "akshare": "补充", "tushare": "可选"}
    for provider_id, provider in _provider_registry().items():
        registration = (
            "需要注册" if provider.metadata.requires_registration else "免注册"
        )
        typer.echo(
            f"{provider_id} | {labels[provider_id]} | {registration} | "
            f'可选安装：pip install "asharelens[{provider_id}]"'
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

    database_url = _database_url(url)
    parsed = _parse_database_url(database_url)
    sanitized = parsed.render_as_string(hide_password=True)
    try:
        engine = create_database_engine(database_url)
        revision = _database_revision(engine)
        engine.dispose()
    except (SQLAlchemyError, OSError):
        typer.echo(f"{sanitized} | 连接失败")
        raise typer.Exit(code=1) from None
    state = "正常" if revision == CURRENT_SCHEMA_REVISION else "需要迁移"
    typer.echo(
        f"{sanitized} | {parsed.get_backend_name()} | {state} | "
        f"{revision or '未迁移'}"
    )
    if revision != CURRENT_SCHEMA_REVISION:
        raise typer.Exit(code=1)


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
    if revision != CURRENT_SCHEMA_REVISION:
        typer.echo(
            f"Runner 需要迁移 | 当前 {revision or '未迁移'} | "
            f"要求 {CURRENT_SCHEMA_REVISION}"
        )
        raise typer.Exit(code=1)
    typer.echo(
        f"Runner 正常 | {parsed.get_backend_name()} | "
        f"迁移 {revision} | 待处理 {pending or 0}"
    )


@runner_app.command("init")
def runner_init(
    url: Annotated[
        str | None,
        typer.Option("--url", help="覆盖 ASHARELENS_DATABASE_URL。"),
    ] = None,
) -> None:
    """按环境配置幂等创建每日选股日程。"""

    settings = _settings(url)
    engine = create_database_engine(settings.database_url)
    _require_current_schema(engine)
    factory = create_session_factory(engine)
    try:
        _executor_registry(factory, settings)
        with factory.begin() as session:
            schedule = PersistentScheduler(session).ensure_daily(
                name=settings.schedule_name,
                job_type="daily.pipeline",
                local_time=settings.schedule_time,
                weekdays=settings.schedule_weekdays,
                payload=settings.daily_configuration().model_dump(mode="json"),
                now=_utc_now_naive(),
                timezone=settings.schedule_timezone,
                queue="default",
                max_attempts=3,
                catch_up_limit=1,
            )
    except ScheduleConflict as error:
        typer.echo(f"日程配置冲突：{error}")
        raise typer.Exit(code=1) from None
    finally:
        engine.dispose()
    typer.echo(
        f"每日选股日程已就绪 | {schedule.local_time} "
        f"{schedule.timezone} | {schedule.id}"
    )


@runner_app.command("enqueue-daily")
def runner_enqueue_daily(
    target_date: Annotated[
        str,
        typer.Option("--date", help="需要研究的本地市场日期。"),
    ],
    url: Annotated[
        str | None,
        typer.Option("--url", help="覆盖 ASHARELENS_DATABASE_URL。"),
    ] = None,
) -> None:
    """手动投递一个幂等的每日选股任务。"""

    parsed_date = _parse_target_date(target_date)
    settings = _settings(url)
    engine = create_database_engine(settings.database_url)
    _require_current_schema(engine)
    factory = create_session_factory(engine)
    payload = settings.daily_configuration().model_dump(mode="json")
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:16]
    try:
        with factory.begin() as session:
            job = JobRepository(session).enqueue(
                job_type="daily.pipeline",
                idempotency_key=(
                    f"manual:{parsed_date.isoformat()}:{digest}"
                ),
                payload={
                    "input": payload,
                    "target_date": parsed_date.isoformat(),
                },
                queue="default",
                max_attempts=3,
                now=_utc_now_naive(),
            )
    finally:
        engine.dispose()
    typer.echo(f"每日任务已投递 | {parsed_date.isoformat()} | {job.id}")


@app.command("run-daily")
def run_daily(
    target_date: Annotated[
        str,
        typer.Option("--date", help="需要研究的本地市场日期。"),
    ],
    url: Annotated[
        str | None,
        typer.Option("--url", help="覆盖 ASHARELENS_DATABASE_URL。"),
    ] = None,
) -> None:
    """同步执行一次真实数据选股、模拟和通知入队。"""

    parsed_date = _parse_target_date(target_date)
    settings = _settings(url)
    engine = create_database_engine(settings.database_url)
    _require_current_schema(engine)
    factory = create_session_factory(engine)
    try:
        service = build_daily_pipeline_service(
            session_factory=factory,
            settings=settings,
            clock=_utc_now_naive,
        )
        request = DailyPipelineRequest(
            **settings.daily_configuration().model_dump(),
            target_date=parsed_date,
        )
        result = service.run(request)
    except MarketSyncFailure as error:
        label = "可重试" if error.retryable else "质量阻断"
        typer.echo(f"每日运行失败 | {label}")
        raise typer.Exit(code=1) from None
    finally:
        engine.dispose()
    typer.echo(
        f"每日运行 {result.status.value} | "
        f"处理 {len(result.processed_sessions)} 个交易日 | "
        f"数据源 {result.provider_id or '-'}"
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

    settings = _settings(url)
    engine = create_database_engine(settings.database_url)
    _require_current_schema(engine)
    factory = create_session_factory(engine)
    worker = Worker(
        session_factory=factory,
        registry=_executor_registry(factory, settings),
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
    """在一个进程中协调 Scheduler、Reaper 和一个队列 Worker。"""

    settings = _settings(url)
    engine = create_database_engine(settings.database_url)
    _require_current_schema(engine)
    factory = create_session_factory(engine)
    worker = Worker(
        session_factory=factory,
        registry=_executor_registry(factory, settings),
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
    """将到期日程幂等投递到持久队列。"""

    database_url = _database_url(url)
    engine = create_database_engine(database_url)
    _require_current_schema(engine)
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
    _require_current_schema(engine)
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
    """运行无需网络和账号的选股、回测与模拟成交闭环。"""

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


def _settings(url: str | None) -> RuntimeSettings:
    try:
        settings = RuntimeSettings.from_env()
        if url:
            settings = settings.model_copy(update={"database_url": url})
        return settings
    except (ValidationError, ValueError) as error:
        typer.echo(f"运行配置无效：{error}")
        raise typer.Exit(code=2) from None


def _executor_registry(
    factory: sessionmaker[Session],
    settings: RuntimeSettings,
) -> ExecutorRegistry:
    try:
        return build_executor_registry(
            session_factory=factory,
            settings=settings,
            clock=_utc_now_naive,
        )
    except RuntimeConfigurationError as error:
        typer.echo(f"运行配置无效：{error}")
        raise typer.Exit(code=2) from None


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


def _parse_target_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        typer.echo("日期必须使用 YYYY-MM-DD 格式。")
        raise typer.Exit(code=2) from None


def _database_revision(engine: Engine) -> str | None:
    with engine.connect() as connection:
        return MigrationContext.configure(connection).get_current_revision()


def _require_current_schema(engine: Engine) -> None:
    try:
        revision = _database_revision(engine)
    except (SQLAlchemyError, OSError):
        typer.echo("数据库连接失败。")
        raise typer.Exit(code=1) from None
    if revision != CURRENT_SCHEMA_REVISION:
        typer.echo(
            f"数据库需要迁移：当前 {revision or '未迁移'}，"
            f"要求 {CURRENT_SCHEMA_REVISION}。"
        )
        raise typer.Exit(code=1)


def _echo_worker_run(run: WorkerRun) -> None:
    typer.echo(
        f"Worker | {run.outcome.value} | "
        f"任务 {run.job_id or '无'} | 类型 {run.job_type or '无'}"
    )


def _utc_now_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


if __name__ == "__main__":
    app()
