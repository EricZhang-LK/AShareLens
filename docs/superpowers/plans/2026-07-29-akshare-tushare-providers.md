# AShareLens AkShare and Tushare Provider Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans and superpowers:test-driven-development task by task.

**Goal:** 在 BaoStock 默认免注册数据源之外，增加 AkShare 免费补充 Provider 与 Tushare 可选 Token Provider，统一输出沪深京股票、完整交易日历和标准化日线，同时保留原始请求、批次哈希、单位换算和来源版本。

**Architecture:** SDK 均延迟导入并隔离在 Gateway 中，Provider 只依赖可注入协议。三个 Provider 通过相同 `DataProviderPlugin` 契约接入现有整分区路由器；路由器绝不混合不同来源的行。默认优先级保持 BaoStock → AkShare → Tushare（用户可配置）。

**Verified upstream contracts (2026-07-29):**

- AkShare 1.18.81：`stock_info_a_code_name` 返回当前沪深京代码和简称；`stock_zh_a_hist` 支持沪深京日线，成交量单位为手、成交额为元；`tool_trade_date_hist_sina` 只返回开市日。
- Tushare Pro：`stock_basic`、`trade_cal`、`daily`；日线成交量单位为手、成交额为千元；Token 和相应积分/权限由用户自行配置。

## Global constraints

- Core 和 Provider 协议不得导入 akshare、tushare 或 pandas。
- SDK 缺失必须返回 `dependency_missing`，不得导致基础包导入失败。
- Tushare Token 只从显式参数或 `TUSHARE_TOKEN` 读取，任何健康检查、异常、日志、批次请求均不得包含 Token。
- 标准化成交量统一为股，成交额统一为元。
- AkShare 当前股票列表不得伪装成历史时点股票池。
- Provider 返回空结果仍形成可追溯批次，由质量门禁决定是否发布。
- SDK 异常转换为稳定、脱敏的 `ProviderError`。
- 真实网络测试为手动契约探针，不纳入默认 CI；CI 使用注入 Gateway 的确定性测试。

---

### Task 1: Shared Provider normalization helpers

**Files:**
- Create: `src/asharelens/data/providers/common.py`
- Modify: `src/asharelens/data/providers/baostock.py`
- Create: `tests/data/providers/test_common.py`

- [x] Write failing tests for沪深京代码映射、非法代码拒绝、规范哈希和批次 ID。
- [x] Extract reusable symbol and canonical-hash logic without changing BaoStock output.
- [x] Run BaoStock regression tests and commit.

### Task 2: AkShare zero-registration supplement

**Files:**
- Create: `src/asharelens/data/providers/akshare.py`
- Create: `tests/data/providers/test_akshare.py`
- Modify: `pyproject.toml`

- [x] Write failing Gateway contract tests for lazy dependency errors, health, current instruments, synthesized closed calendar days, daily normalization and all adjustment modes.
- [x] Implement current-only instrument guard and unit conversion (`手 × 100`).
- [x] Add optional extra `akshare`; do not add it to mandatory SDK dependencies.
- [x] Verify and commit `feat: add akshare supplement provider`.

### Task 3: Tushare configurable Provider

**Files:**
- Create: `src/asharelens/data/providers/tushare.py`
- Create: `tests/data/providers/test_tushare.py`
- Modify: `pyproject.toml`

- [x] Write failing tests for missing Token, secret redaction, listing history, calendar, single-day market query, date-range symbol query and unit conversion.
- [x] Implement lazy SDK Gateway and explicit permissions failures.
- [x] Add optional extra `tushare`; never place it in the default install.
- [x] Verify and commit `feat: add configurable tushare provider`.

### Task 4: Registry, routing documentation and phase audit

**Files:**
- Modify: `src/asharelens/cli.py`
- Modify: `tests/test_provider_cli.py`
- Modify: `README.md`
- Modify: `docs/superpowers/plans/2026-07-29-akshare-tushare-providers.md`

- [x] List all installed-capability Providers without importing optional SDKs.
- [x] Document default order, Token configuration, units, historical-universe limitation and upstream terms.
- [x] Run full tests, coverage, Ruff, mypy and build.
- [x] Record evidence and commit `docs: verify optional data providers`.

## Verification Evidence

- 2026-07-29：收集 133 项测试，131 项通过，2 项 MySQL 8.4 集成测试因本机无测试数据库而跳过；总覆盖率 86%，并设置 85% 最低门禁。
- AkShare 契约覆盖可选依赖缺失、当前股票池限制、沪深京代码、闭市日补全、三种复权参数、成交量/成交额单位和上游错误脱敏。
- Tushare 契约覆盖 SDK/Token 缺失、历史上市与退市、交易日历、单日全市场与区间逐股票查询、单位换算、复权能力拒绝和凭据脱敏。
- `ruff check .` 通过；`mypy src` 严格检查 38 个源文件通过；源码包和 wheel 构建成功。
- `provider list` 在未导入可选 SDK 的情况下列出 BaoStock（默认）、AkShare（补充）和 Tushare（可选注册）。
- 真实外部网络探针不进入默认 CI，避免上游不稳定造成随机失败；数据发布仍必须通过质量门禁。
