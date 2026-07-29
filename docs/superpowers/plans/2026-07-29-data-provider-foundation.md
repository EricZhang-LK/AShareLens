# AShareLens Data Provider Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立带数据血缘、质量门禁和整分区故障转移的数据平台契约，并交付 BaoStock 0.9.3 默认 Provider。

**Architecture:** `asharelens.data` 依赖 `asharelens.core` 的规范化 `DailyBar`，但 Core 不反向依赖数据层。Provider 返回不可变、带来源的批次；批次先按交易日形成单源分区，再通过质量门禁进入快照。真实 SDK 隐藏在 Gateway 后面，单元测试使用完整协议的内存客户端。

**Tech Stack:** Python 3.12、Pydantic 2、BaoStock 0.9.3（可选 extra）、pytest。

## Global Constraints

- BaoStock 是默认免注册真实数据源，版本范围固定为 `>=0.9.3,<1`。
- AkShare 和 Tushare 不成为 `asharelens` 基础安装的强制依赖。
- 每个“数据集 + 交易日”分区只能有一个 Provider，禁止行级混源。
- Provider 返回值必须包含提供方、拉取时间、请求参数、原始批次标识和内容哈希。
- 所有 `datetime` 必须带时区；交易日期使用 `datetime.date`。
- 质量问题分为 `warning` 和 `failure`；存在 failure 时分区不能发布。
- SDK 网络访问必须有超时，并把第三方错误转换为稳定的 AShareLens 错误码。
- BaoStock 未安装时，Core 和离线演示仍须正常工作。
- 新增行为严格执行测试先失败、最小实现和全量回归。

---

### Task 1: Normalized data and Provider contracts

**Files:**
- Create: `src/asharelens/data/__init__.py`
- Create: `src/asharelens/data/models.py`
- Create: `src/asharelens/data/provider.py`
- Create: `tests/data/test_provider_contract.py`

**Interfaces:**
- Consumes: `asharelens.core.models.DailyBar`.
- Produces: `Dataset`, `Adjustment`, `Instrument`, `TradingSession`, `ProviderMetadata`, `ProviderHealth`, generic `DataBatch[RecordT]`, `DataProviderPlugin`, and `ProviderError`.

- [x] **Step 1: Write failing contract tests**

Tests must prove that:

- `DataBatch` rejects a naive `fetched_at`.
- `DataBatch` preserves provider and request metadata.
- `Instrument` accepts Shanghai, Shenzhen and Beijing normalized symbols.
- `ProviderMetadata.model_json_schema()` exposes a string `plugin_api_version`.
- `ProviderError` exposes stable `provider_id`, `error_code`, and retryability.

- [x] **Step 2: Run and verify RED**

Run: `python -m pytest tests/data/test_provider_contract.py -v`

Expected: import failure because `asharelens.data` does not exist.

- [x] **Step 3: Implement immutable contracts**

Use frozen Pydantic models and a structural `DataProviderPlugin` protocol with:

```python
def healthcheck(self) -> ProviderHealth: ...
def fetch_instruments(self, as_of: date) -> DataBatch[Instrument]: ...
def fetch_calendar(self, start: date, end: date) -> DataBatch[TradingSession]: ...
def fetch_daily_bars(
    self,
    symbols: tuple[str, ...],
    start: date,
    end: date,
    adjustment: Adjustment,
) -> DataBatch[DailyBar]: ...
```

- [x] **Step 4: Run tests, Ruff, and Mypy**

Run:

```text
python -m pytest tests/data/test_provider_contract.py -v
python -m pytest -q
python -m ruff check .
python -m mypy src
```

- [x] **Step 5: Commit**

```text
git add src/asharelens/data tests/data
git commit -m "feat: define normalized data provider contracts"
```

### Task 2: Immutable partitions, lineage, and snapshot manifests

**Files:**
- Create: `src/asharelens/data/partition.py`
- Create: `tests/data/test_partition.py`

**Interfaces:**
- Consumes: `DataBatch[DailyBar]`.
- Produces: `PartitionKey`, `DataPartition`, `SnapshotManifest`, and `partition_daily_bars(batch)`.

- [x] **Step 1: Write failing lineage tests**

Tests must prove that:

- A two-day batch becomes two `daily_bars` partitions.
- Each partition inherits exactly one provider and batch ID.
- Partition content hashes are stable under input record order.
- Snapshot IDs are stable under partition order.
- Constructing one partition with records from multiple providers is impossible through the public API.

- [x] **Step 2: Run and verify RED**

Run: `python -m pytest tests/data/test_partition.py -v`

- [x] **Step 3: Implement canonical content hashing**

Canonicalize records with Pydantic JSON mode, sort by `(trade_date, symbol)`, serialize with sorted UTF-8 JSON keys and compact separators, then hash with SHA-256. The snapshot manifest stores partition keys, hashes, provider IDs, source batch IDs and schema versions.

- [x] **Step 4: Run focused and full verification**

Run:

```text
python -m pytest tests/data/test_partition.py -v
python -m pytest -q
python -m ruff check .
python -m mypy src
```

- [x] **Step 5: Commit**

```text
git add src/asharelens/data/partition.py tests/data/test_partition.py
git commit -m "feat: add versioned data partitions and lineage"
```

### Task 3: Daily-bar data quality gate

**Files:**
- Create: `src/asharelens/data/quality.py`
- Create: `tests/data/test_quality_gate.py`

**Interfaces:**
- Consumes: `DataPartition`.
- Produces: `QualitySeverity`, `QualityIssue`, `QualityReport`, and `DailyBarQualityGate.evaluate(...)`.

- [x] **Step 1: Write failing quality behavior tests**

Tests must prove that:

- Duplicate `(symbol, trade_date)` records are failures.
- Missing expected symbols above the configured coverage threshold are failures.
- Zero-volume non-suspended data is a warning.
- A complete partition passes and exposes `publishable=True`.
- Warning-only partitions remain publishable but are marked degraded.

- [x] **Step 2: Run and verify RED**

Run: `python -m pytest tests/data/test_quality_gate.py -v`

- [x] **Step 3: Implement deterministic issue codes**

Use stable codes `duplicate_record`, `coverage_below_threshold`, `zero_volume`, and `unexpected_trade_date`. Sort issues by severity, code, symbol and date so reports are reproducible.

- [x] **Step 4: Run focused and full verification**

Run:

```text
python -m pytest tests/data/test_quality_gate.py -v
python -m pytest -q
python -m ruff check .
python -m mypy src
```

- [x] **Step 5: Commit**

```text
git add src/asharelens/data/quality.py tests/data/test_quality_gate.py
git commit -m "feat: gate daily data quality before publication"
```

### Task 4: Whole-partition provider routing

**Files:**
- Create: `src/asharelens/data/router.py`
- Create: `tests/data/test_provider_router.py`

**Interfaces:**
- Consumes: ordered Providers and `DailyBarQualityGate`.
- Produces: `ProviderRouter.fetch_daily_partition(...) -> RoutedPartition`.

- [x] **Step 1: Write failing routing tests with real in-memory fakes**

Tests must prove that:

- A healthy primary Provider is used without calling fallback.
- A failed primary causes the fallback to supply the complete partition.
- A quality-failed primary causes a complete fallback retry.
- Rows from primary and fallback are never combined.
- If all Providers fail, the raised aggregate error preserves each attempt.

- [x] **Step 2: Run and verify RED**

Run: `python -m pytest tests/data/test_provider_router.py -v`

- [x] **Step 3: Implement sequential partition routing**

For each Provider, request the complete symbol set for one trading date, form one partition, run the gate, and accept only a publishable result. Never fill primary gaps with fallback rows.

- [x] **Step 4: Run focused and full verification**

Run:

```text
python -m pytest tests/data/test_provider_router.py -v
python -m pytest -q
python -m ruff check .
python -m mypy src
```

- [x] **Step 5: Commit**

```text
git add src/asharelens/data/router.py tests/data/test_provider_router.py
git commit -m "feat: route complete data partitions across providers"
```

### Task 5: BaoStock 0.9.3 adapter

**Files:**
- Create: `src/asharelens/data/providers/__init__.py`
- Create: `src/asharelens/data/providers/baostock.py`
- Create: `tests/data/providers/test_baostock.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Consumes: BaoStock login, query, ResultSet, and logout APIs through `BaoStockGateway`.
- Produces: `BaoStockProvider` implementing `DataProviderPlugin`.

- [x] **Step 1: Add the optional dependency**

Add:

```toml
baostock = ["baostock>=0.9.3,<1"]
```

The base package and `asharelens demo` must remain usable without this extra.

- [x] **Step 2: Write failing adapter tests**

Use an injected fake Gateway and complete fake ResultSet. Tests must prove:

- Login failure becomes `ProviderError(error_code="authentication_failed")`.
- Daily fields map to normalized symbol, date, OHLC, volume and amount.
- Empty numeric strings and non-trading rows are skipped deliberately.
- Adjustment mapping is `none -> "3"`, `forward -> "2"`, `backward -> "1"`.
- Logout runs after success and after query failure.
- Returned batch metadata identifies `baostock` and the original request.

- [x] **Step 3: Run and verify RED**

Run: `python -m pytest tests/data/providers/test_baostock.py -v`

- [x] **Step 4: Implement the Gateway and Provider**

Import BaoStock lazily. Use the documented daily fields:

```text
date,code,open,high,low,close,volume,amount,tradestatus,isST
```

Query one symbol at a time, set `frequency="d"`, use ISO dates, convert SDK errors to stable provider errors, and always logout in `finally`.

- [x] **Step 5: Run focused and full verification**

Run:

```text
python -m pytest tests/data/providers/test_baostock.py -v
python -m pytest -q
python -m ruff check .
python -m mypy src
python -m asharelens.cli demo --json
```

- [x] **Step 6: Commit**

```text
git add pyproject.toml src/asharelens/data/providers tests/data/providers
git commit -m "feat: add zero-registration baostock provider"
```

### Task 6: Provider diagnostics and phase audit

**Files:**
- Modify: `src/asharelens/cli.py`
- Create: `tests/test_provider_cli.py`
- Modify: `README.md`
- Modify: `docs/superpowers/plans/2026-07-29-data-provider-foundation.md`

**Interfaces:**
- Consumes: Provider metadata and healthcheck.
- Produces: `asharelens provider list` and `asharelens provider check baostock`.

- [x] **Step 1: Write failing CLI tests**

Tests must prove that provider listing works without BaoStock installed, identifies it as an optional default Provider, and health-check errors are printed without exposing credentials or tracebacks.

- [x] **Step 2: Run and verify RED**

Run: `python -m pytest tests/test_provider_cli.py -v`

- [x] **Step 3: Implement diagnostics and Chinese documentation**

Document installation with `pip install "asharelens[baostock]"`, the no-registration property, network requirements, data-license responsibility, and the distinction between offline demo and real data.

- [x] **Step 4: Run phase verification**

Run:

```text
python -m pytest --cov=asharelens --cov-report=term-missing
python -m ruff check .
python -m mypy src
python -m build --no-isolation
python -m asharelens.cli demo --json
python -m asharelens.cli provider list
```

- [x] **Step 5: Record evidence and commit**

```text
git add src/asharelens/cli.py tests/test_provider_cli.py README.md docs/superpowers/plans/2026-07-29-data-provider-foundation.md
git commit -m "docs: record data provider phase verification"
```

## Verification Evidence

- `pytest --cov=asharelens`: 61 项测试通过，综合覆盖率 90%。
- `ruff check .`：通过。
- `mypy src`：严格模式通过。
- `python -m build --no-isolation`：成功生成源码包和 wheel。
- `asharelens demo --json`：离线闭环继续可用且输出确定。
- `asharelens provider list`：BaoStock 被标记为默认、免注册、可选安装。
- BaoStock 0.9.3 真实匿名查询验证：`sh.600000` 在 2026-07-27 至
  2026-07-28 返回两条规范化日线，收盘价、交易状态、批次哈希均正确。
- 路由测试证明质量失败时切换完整分区，主源与备用源记录没有行级混合。
