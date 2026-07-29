# AShareLens Strategies and Notifications Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans and superpowers:test-driven-development task by task.

**Goal:** 完成横截面动量/RPS、价值质量多因子、上升趋势回调三种解释型策略，并提供可靠、可扩展、可幂等重试的选股结果推送。

**Architecture:** 策略仍是纯 Core 插件。基本面通过带 `available_on` 的不可变快照进入 `StrategyContext`，上下文验证器阻止未来发布数据。通知位于 Core 之外：Renderer 生成渠道无关消息，Notifier 插件负责传输，MySQL Outbox 记录幂等键、尝试、状态和脱敏错误，Runner 执行发送。

## Global constraints

- 每个策略参数都由冻结、禁止额外字段的 Pydantic 模型声明，并可生成 JSON Schema。
- 策略不得读取数据库、文件、环境变量或网络。
- 所有未入选结果也必须给出稳定原因码和指标快照。
- 价值质量策略不得用价格因子冒充基本面；财务快照 `available_on` 必须不晚于信号日。
- 排名必须确定性处理并列和证券代码顺序。
- 通知内容消费已持久化运行结果，不重新计算策略。
- 同一 `(notifier_id, dedupe_key)` 只能产生一次成功发送效果。
- 凭据不得进入通知表、任务 payload、结果、错误或日志。
- Webhook 只允许显式配置的 HTTPS 地址；测试传输通过注入协议完成。

---

### Task 1: Point-in-time fundamental context

**Files:**
- Modify: `src/asharelens/core/models.py`
- Create: `tests/core/test_fundamental_context.py`

- [x] Write failing tests for future-publication rejection, symbol mismatch, latest-visible lookup and immutable metrics.
- [x] Add `FundamentalSnapshot` and optional fundamentals to `StrategyContext`.
- [x] Verify Core remains independent of data/storage modules and commit.

### Task 2: Cross-sectional momentum/RPS strategy

**Files:**
- Create: `src/asharelens/strategies/momentum_rps.py`
- Create: `tests/strategies/test_momentum_rps.py`

- [x] Test schema bounds, lookback/skip validation, insufficient history, deterministic ranks, selected percentile and explanations.
- [x] Implement total-return momentum ranking without future bars.
- [x] Verify and commit `feat: add momentum rps strategy`.

### Task 3: Value-quality strategy

**Files:**
- Create: `src/asharelens/strategies/value_quality.py`
- Create: `tests/strategies/test_value_quality.py`

- [x] Test configurable PE/PB/ROE/growth/debt thresholds, missing metrics, future snapshots and deterministic score/rank.
- [x] Implement multi-factor score from point-in-time fundamentals only.
- [x] Verify and commit `feat: add point in time value quality strategy`.

### Task 4: Uptrend pullback and built-in registry

**Files:**
- Create: `src/asharelens/strategies/trend_pullback.py`
- Create: `src/asharelens/strategies/registry.py`
- Create: `tests/strategies/test_trend_pullback.py`
- Create: `tests/strategies/test_registry.py`

- [ ] Test trend, rising moving average, recent-high pullback band, volume contraction, insufficient history and explanations.
- [ ] Register four built-ins and expose metadata plus Pydantic JSON Schema without constructing parameters.
- [ ] Verify and commit `feat: complete built in strategy catalog`.

### Task 5: Notifier protocol and message renderer

**Files:**
- Create: `src/asharelens/notifications/models.py`
- Create: `src/asharelens/notifications/notifier.py`
- Create: `src/asharelens/notifications/render.py`
- Create: `tests/notifications/test_render.py`

- [ ] Test deterministic Chinese summary, selected/excluded counts, reasons, orders, fingerprint and disclaimer.
- [ ] Define `NotifierPlugin`, capabilities and sanitized delivery result.
- [ ] Verify and commit.

### Task 6: Transactional notification outbox

**Files:**
- Modify: `src/asharelens/storage/models.py`
- Create: `migrations/versions/20260729_0005_notification_outbox.py`
- Create: `src/asharelens/storage/notification_repository.py`
- Create: `tests/notifications/test_outbox.py`
- Modify: `tests/storage/test_migration.py`

- [ ] Test enqueue idempotency, claim lease, success, retry, terminal failure and secret-free errors.
- [ ] Add MySQL `SKIP LOCKED` integration coverage.
- [ ] Verify and commit.

### Task 7: Console and generic Webhook plugins

**Files:**
- Create: `src/asharelens/notifications/console.py`
- Create: `src/asharelens/notifications/webhook.py`
- Create: `tests/notifications/test_notifiers.py`
- Modify: `pyproject.toml`

- [ ] Test HTTPS validation, injected transport, timeout, non-2xx classification and secret-safe failures.
- [ ] Implement Console for local preview and JSON Webhook for Feishu/WeCom/DingTalk-compatible relays.
- [ ] Verify and commit.

### Task 8: Runner delivery executor and phase audit

**Files:**
- Create: `src/asharelens/runner/workflows/notification_delivery.py`
- Create: `tests/runner/test_notification_delivery.py`
- Modify: `README.md`
- Modify: `docs/superpowers/plans/2026-07-29-strategies-notifications.md`

- [ ] Execute Outbox messages via notifier registry with heartbeat and retry classification.
- [ ] Run full tests, coverage, Ruff, mypy and build.
- [ ] Record evidence and commit `docs: verify strategies and notifications`.
