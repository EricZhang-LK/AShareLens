# AShareLens Foundation and Demo Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立干净、可发布的 AShareLens Python 工程，并交付一个确定性合成数据驱动的“收盘选股 → D+1 开盘成交 → 净值与运行指纹”命令行闭环。

**Architecture:** 单一 PyPI 包使用 `src` 布局，领域模型、策略、组合、成交、回测和演示数据分别放在独立模块中。首阶段不接入 Web、MySQL 或真实数据源，确保 `asharelens.core` 可以独立运行和测试；后续服务只调用这些公开接口。

**Tech Stack:** Python 3.12、Pydantic 2、Typer、pytest、Ruff、Mypy、GitHub Actions。

## Global Constraints

- 项目名称为 `AShareLens`，Python 导入包名为 `asharelens`。
- 许可证固定为 MIT，中文为主，英文摘要随公开 Alpha 提供。
- Python 支持范围为 `>=3.12,<3.14`。
- `asharelens.core` 不得导入 FastAPI、SQLAlchemy、MySQL 驱动或具体数据源 SDK。
- 所有时间点必须显式使用 `Asia/Shanghai` 语义；交易日使用 `datetime.date`。
- 新增行为严格遵循测试先失败、最小实现、全量测试通过的循环。
- 演示数据必须确定性生成，不下载或再分发真实行情。
- 策略在 D 日收盘产生信号，订单最早在下一交易日开盘成交。
- 首阶段只实现演示闭环所需能力，不提前加入 Web、ORM、Redis、Celery 或实盘接口。

---

### Task 1: Repository and Python package baseline

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `.editorconfig`
- Create: `LICENSE`
- Create: `README.md`
- Create: `src/asharelens/__init__.py`
- Create: `src/asharelens/core/__init__.py`
- Create: `tests/test_package.py`
- Create: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: none.
- Produces: importable `asharelens.__version__` and standard commands `pytest`, `ruff check .`, and `mypy src`.

- [ ] **Step 1: Write the failing package import test**

```python
from asharelens import __version__


def test_package_exposes_semantic_version() -> None:
    major, minor, patch = __version__.split(".")
    assert (major, minor, patch) == ("0", "1", "0")
```

- [ ] **Step 2: Run the test and verify RED**

Run: `python -m pytest tests/test_package.py -v`

Expected: FAIL because `asharelens` does not exist.

- [ ] **Step 3: Add the minimal package and project configuration**

Create a Hatchling-based `pyproject.toml` with runtime dependencies `pydantic>=2.8,<3` and `typer>=0.12,<1`, and development dependencies `pytest>=8,<9`, `pytest-cov>=5,<7`, `ruff>=0.6,<1`, and `mypy>=1.11,<2`. Set `__version__ = "0.1.0"` and configure the `asharelens` CLI entry point.

- [ ] **Step 4: Run baseline verification**

Run:

```text
python -m pytest tests/test_package.py -v
python -m ruff check .
python -m mypy src
```

Expected: all commands exit with code 0.

- [ ] **Step 5: Commit**

```text
git add .
git commit -m "chore: initialize asharelens package"
```

### Task 2: Domain data and explainable strategy contracts

**Files:**
- Create: `src/asharelens/core/models.py`
- Create: `src/asharelens/core/strategy.py`
- Modify: `src/asharelens/core/__init__.py`
- Create: `tests/core/test_strategy_contract.py`

**Interfaces:**
- Consumes: Pydantic 2.
- Produces: `DailyBar`, `StrategyContext`, `SelectionReason`, `SelectionCandidate`, `StrategyMetadata`, and generic `StrategyPlugin[ParamsT]`.

- [ ] **Step 1: Write failing tests for validation and JSON Schema**

```python
from datetime import date

import pytest
from pydantic import ValidationError

from asharelens.core.models import DailyBar, SelectionCandidate
from asharelens.core.strategy import StrategyMetadata


def test_daily_bar_rejects_high_below_open() -> None:
    with pytest.raises(ValidationError):
        DailyBar(
            symbol="sh.600000",
            trade_date=date(2026, 7, 1),
            open=10,
            high=9,
            low=8,
            close=9,
            volume=1000,
            amount=9000,
        )


def test_candidate_preserves_structured_explanation() -> None:
    candidate = SelectionCandidate(
        symbol="sh.600000",
        signal_date=date(2026, 7, 1),
        selected=True,
        score=0.92,
        rank=1,
        reasons=[{"code": "ma_cross", "message": "短期均线高于长期均线"}],
        metrics={"ma_fast": 10.2, "ma_slow": 9.8},
    )
    assert candidate.reasons[0].code == "ma_cross"
    assert candidate.metrics["ma_fast"] == 10.2


def test_strategy_metadata_schema_is_machine_readable() -> None:
    schema = StrategyMetadata.model_json_schema()
    assert schema["properties"]["plugin_api_version"]["type"] == "string"
```

- [ ] **Step 2: Run and verify RED**

Run: `python -m pytest tests/core/test_strategy_contract.py -v`

Expected: FAIL because the model and strategy modules do not exist.

- [ ] **Step 3: Implement immutable contracts**

Use frozen Pydantic models. Validate `low <= min(open, close)`, `high >= max(open, close)`, non-negative volume and amount, scores in `[0, 1]`, and positive ranks. Define `StrategyPlugin.generate(context, params) -> tuple[SelectionCandidate, ...]` as the public protocol.

- [ ] **Step 4: Run focused and full tests**

Run:

```text
python -m pytest tests/core/test_strategy_contract.py -v
python -m pytest -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```text
git add src/asharelens/core tests/core
git commit -m "feat: define explainable strategy contracts"
```

### Task 3: Deterministic synthetic market data

**Files:**
- Create: `src/asharelens/demo/__init__.py`
- Create: `src/asharelens/demo/data.py`
- Create: `tests/demo/test_synthetic_data.py`

**Interfaces:**
- Consumes: `DailyBar`.
- Produces: `generate_demo_bars(start: date, sessions: int) -> dict[str, tuple[DailyBar, ...]]`.

- [ ] **Step 1: Write failing deterministic-data tests**

```python
from datetime import date

from asharelens.demo.data import generate_demo_bars


def test_demo_data_is_deterministic_and_has_three_symbols() -> None:
    first = generate_demo_bars(date(2026, 1, 5), sessions=80)
    second = generate_demo_bars(date(2026, 1, 5), sessions=80)
    assert first == second
    assert tuple(first) == ("demo.000001", "demo.000002", "demo.000003")
    assert all(len(bars) == 80 for bars in first.values())


def test_demo_data_contains_distinct_market_behaviors() -> None:
    bars = generate_demo_bars(date(2026, 1, 5), sessions=80)
    assert bars["demo.000001"][-1].close > bars["demo.000001"][0].close
    assert bars["demo.000002"][-1].close < bars["demo.000002"][0].close
```

- [ ] **Step 2: Run and verify RED**

Run: `python -m pytest tests/demo/test_synthetic_data.py -v`

Expected: FAIL because `asharelens.demo` does not exist.

- [ ] **Step 3: Implement deterministic weekday bars**

Generate exactly three symbols with rising, falling, and oscillating price paths. Skip weekends, derive OHLC and volume using fixed arithmetic only, round prices to two decimals, and avoid random-number generators.

- [ ] **Step 4: Run focused and full tests**

Run:

```text
python -m pytest tests/demo/test_synthetic_data.py -v
python -m pytest -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```text
git add src/asharelens/demo tests/demo
git commit -m "feat: add deterministic demo market data"
```

### Task 4: Parameterized moving-average strategy

**Files:**
- Create: `src/asharelens/strategies/__init__.py`
- Create: `src/asharelens/strategies/moving_average.py`
- Create: `tests/strategies/test_moving_average.py`

**Interfaces:**
- Consumes: `StrategyContext`, `SelectionCandidate`, and demo bars.
- Produces: `MovingAverageParams` and `MovingAverageStrategy`.

- [ ] **Step 1: Write failing strategy tests**

```python
from datetime import date

from asharelens.core.models import StrategyContext
from asharelens.demo.data import generate_demo_bars
from asharelens.strategies.moving_average import (
    MovingAverageParams,
    MovingAverageStrategy,
)


def test_moving_average_schema_contains_web_constraints() -> None:
    schema = MovingAverageParams.model_json_schema()
    assert schema["properties"]["fast_period"]["minimum"] == 2
    assert schema["properties"]["slow_period"]["maximum"] == 500


def test_moving_average_selects_rising_symbol_with_explanation() -> None:
    bars = generate_demo_bars(date(2026, 1, 5), sessions=80)
    context = StrategyContext(signal_date=max(v[-1].trade_date for v in bars.values()), bars=bars)
    results = MovingAverageStrategy().generate(
        context,
        MovingAverageParams(fast_period=10, slow_period=30, confirm_days=3),
    )
    rising = next(item for item in results if item.symbol == "demo.000001")
    falling = next(item for item in results if item.symbol == "demo.000002")
    assert rising.selected is True
    assert rising.reasons[0].code == "ma_trend_confirmed"
    assert falling.selected is False
```

- [ ] **Step 2: Run and verify RED**

Run: `python -m pytest tests/strategies/test_moving_average.py -v`

Expected: FAIL because the moving-average strategy does not exist.

- [ ] **Step 3: Implement the minimum strategy**

Validate `fast_period < slow_period`. Use only bars whose date is not later than `context.signal_date`. Select a symbol when the fast average is strictly above the slow average for all confirmation dates. Return metrics for both averages and a reason code for either selection or exclusion.

- [ ] **Step 4: Run focused and full tests**

Run:

```text
python -m pytest tests/strategies/test_moving_average.py -v
python -m pytest -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```text
git add src/asharelens/strategies tests/strategies
git commit -m "feat: add parameterized moving average strategy"
```

### Task 5: Target portfolio and A-share opening execution

**Files:**
- Create: `src/asharelens/core/portfolio.py`
- Create: `src/asharelens/core/execution.py`
- Create: `tests/core/test_portfolio.py`
- Create: `tests/core/test_execution.py`

**Interfaces:**
- Consumes: ranked `SelectionCandidate` values and `DailyBar`.
- Produces: `build_equal_weight_targets(...)`, `Order`, `Fill`, `PortfolioState`, and `OpeningExecutionModel.execute(...)`.

- [ ] **Step 1: Write failing equal-weight tests**

```python
from datetime import date

from asharelens.core.models import SelectionCandidate
from asharelens.core.portfolio import build_equal_weight_targets


def test_equal_weight_targets_respect_top_n() -> None:
    candidates = [
        SelectionCandidate(symbol=f"demo.{i}", signal_date=date(2026, 1, 5), selected=True, score=1 - i / 10, rank=i + 1)
        for i in range(3)
    ]
    targets = build_equal_weight_targets(candidates, top_n=2, max_weight=0.6)
    assert targets == {"demo.0": 0.5, "demo.1": 0.5}
```

- [ ] **Step 2: Run and verify portfolio RED**

Run: `python -m pytest tests/core/test_portfolio.py -v`

Expected: FAIL because the portfolio module does not exist.

- [ ] **Step 3: Implement equal-weight targets and verify GREEN**

Sort selected candidates by rank and symbol, take `top_n`, allocate equal weights, and reject configurations where `top_n * max_weight < 1`.

Run: `python -m pytest tests/core/test_portfolio.py -v`

Expected: PASS.

- [ ] **Step 4: Write failing D+1 execution tests**

```python
from datetime import date

from asharelens.core.execution import OpeningExecutionModel, Order, Side
from asharelens.core.models import DailyBar


def test_buy_fills_at_adverse_slipped_next_open_and_board_lot() -> None:
    model = OpeningExecutionModel(slippage_bps=10, commission_rate=0)
    bar = DailyBar(
        symbol="demo.000001",
        trade_date=date(2026, 1, 6),
        open=10,
        high=10.2,
        low=9.9,
        close=10.1,
        volume=1_000_000,
        amount=10_000_000,
    )
    fill = model.execute(Order("demo.000001", Side.BUY, 1234, date(2026, 1, 5)), bar)
    assert fill.quantity == 1200
    assert fill.price == 10.01
```

- [ ] **Step 5: Run and verify execution RED**

Run: `python -m pytest tests/core/test_execution.py -v`

Expected: FAIL because the execution module does not exist.

- [ ] **Step 6: Implement minimum opening execution and verify all tests**

Apply adverse basis-point slippage, two-decimal adverse tick rounding, high/low clamping, 100-share buy-lot rounding, commission, and explicit rejection for a missing next-day bar.

Run:

```text
python -m pytest tests/core/test_execution.py -v
python -m pytest -q
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```text
git add src/asharelens/core tests/core
git commit -m "feat: add target portfolio and opening execution"
```

### Task 6: Shared daily-cycle backtest engine and run fingerprint

**Files:**
- Create: `src/asharelens/core/fingerprint.py`
- Create: `src/asharelens/core/engine.py`
- Create: `tests/core/test_fingerprint.py`
- Create: `tests/core/test_engine.py`

**Interfaces:**
- Consumes: strategy, parameters, bars, target builder, and opening execution model.
- Produces: `build_run_fingerprint(...)`, `DailyCycleEngine`, `BacktestResult`, signal ledger, fill ledger, and NAV series.

- [ ] **Step 1: Write failing fingerprint test**

```python
from asharelens.core.fingerprint import build_run_fingerprint


def test_fingerprint_is_canonical_for_parameter_key_order() -> None:
    first = build_run_fingerprint("strategy-hash", {"slow": 60, "fast": 20}, "snapshot-1", "engine-1")
    second = build_run_fingerprint("strategy-hash", {"fast": 20, "slow": 60}, "snapshot-1", "engine-1")
    assert first == second
    assert len(first) == 64
```

- [ ] **Step 2: Run and verify fingerprint RED**

Run: `python -m pytest tests/core/test_fingerprint.py -v`

Expected: FAIL because the fingerprint module does not exist.

- [ ] **Step 3: Implement canonical SHA-256 fingerprint**

Serialize UTF-8 JSON with sorted keys and compact separators, include all arguments in a named object, and return lowercase hexadecimal SHA-256.

- [ ] **Step 4: Write failing end-to-end engine test**

Create a test using 80 synthetic sessions, the moving-average strategy, `100_000` initial cash, `top_n=1`, and zero fees. Assert that no fill occurs on a signal date, every fill date is later than its order signal date, cash never becomes negative, and final NAV is positive.

- [ ] **Step 5: Run and verify engine RED**

Run: `python -m pytest tests/core/test_engine.py -v`

Expected: FAIL because `DailyCycleEngine` does not exist.

- [ ] **Step 6: Implement the minimum chronological engine**

The engine must process prior pending orders before generating the current close signal, value positions at close, create next-session orders, and return immutable ledgers. Reuse the same public `process_session` method that the future paper portfolio runner will call.

- [ ] **Step 7: Run focused and full tests**

Run:

```text
python -m pytest tests/core/test_fingerprint.py tests/core/test_engine.py -v
python -m pytest -q
```

Expected: all tests pass.

- [ ] **Step 8: Commit**

```text
git add src/asharelens/core tests/core
git commit -m "feat: add shared daily cycle backtest engine"
```

### Task 7: Demo CLI and user-facing verification

**Files:**
- Create: `src/asharelens/cli.py`
- Create: `tests/test_cli.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: demo data, moving-average strategy, and daily-cycle engine.
- Produces: `asharelens demo` command with human-readable summary and `--json` machine-readable output.

- [ ] **Step 1: Write failing CLI behavior test**

```python
import json

from typer.testing import CliRunner

from asharelens.cli import app


def test_demo_json_reports_reproducible_closed_loop() -> None:
    result = CliRunner().invoke(app, ["demo", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["sessions"] == 80
    assert payload["strategy"] == "moving_average"
    assert payload["signals"] > 0
    assert payload["fills"] > 0
    assert len(payload["fingerprint"]) == 64
```

- [ ] **Step 2: Run and verify RED**

Run: `python -m pytest tests/test_cli.py -v`

Expected: FAIL because the CLI module does not exist.

- [ ] **Step 3: Implement the demo command**

Use fixed dates, fixed parameters, fixed starting cash, deterministic data, and stable JSON keys. Human output must state that the data is synthetic and the result is not investment advice.

- [ ] **Step 4: Run automated and manual verification**

Run:

```text
python -m pytest -q
python -m asharelens.cli demo --json
python -m ruff check .
python -m mypy src
```

Expected: tests and static checks pass; CLI prints valid JSON with non-zero signals and fills.

- [ ] **Step 5: Commit**

```text
git add src/asharelens/cli.py tests/test_cli.py README.md
git commit -m "feat: deliver deterministic demo selection loop"
```

### Task 8: Phase audit

**Files:**
- Modify: `docs/superpowers/plans/2026-07-29-foundation-demo-core.md`

**Interfaces:**
- Consumes: all Task 1–7 outputs.
- Produces: checked task boxes and authoritative verification evidence.

- [ ] **Step 1: Run the complete verification suite**

Run:

```text
python -m pytest --cov=asharelens --cov-report=term-missing
python -m ruff check .
python -m mypy src
python -m build
python -m asharelens.cli demo --json
git status --short
```

Expected: all commands succeed; demo JSON is deterministic across two consecutive runs; only the plan checkbox update remains uncommitted.

- [ ] **Step 2: Verify architectural constraints**

Run a repository search confirming that files under `src/asharelens/core` do not import `fastapi`, `sqlalchemy`, `redis`, `celery`, `baostock`, `akshare`, or `tushare`.

- [ ] **Step 3: Mark completed boxes and commit the audit**

```text
git add docs/superpowers/plans/2026-07-29-foundation-demo-core.md
git commit -m "docs: record foundation phase verification"
```

