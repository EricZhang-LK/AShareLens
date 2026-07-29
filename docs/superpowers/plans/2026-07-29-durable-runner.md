# AShareLens Durable Runner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不引入 Redis 和 Celery 的前提下，实现可恢复、可重试、幂等且适合单机 Docker 部署的 MySQL 持久任务队列，并让每日模拟与历史回测调用同一个 `DailyCycleEngine`。

**Architecture:** `asharelens.runner` 只依赖稳定的任务仓储协议和执行器协议；首个 `TaskBroker` 适配器使用 MySQL。Scheduler 只负责按计划幂等地产生任务，Worker 通过租约领取任务，Heartbeat 延长所有权，Reaper 回收崩溃 Worker 的过期任务。任务采用至少一次交付，业务写入通过幂等键和运行指纹实现“效果恰好一次”。

**Tech Stack:** Python 3.12、SQLAlchemy 2、Alembic、MySQL 8.4、Pydantic 2、Typer、pytest。

## State machine

```text
queued ──claim──> running ──complete──> succeeded
  ▲                  │
  │                  ├──retryable failure──> retry_wait ──due──> running
  │                  │
  └──expired lease───┘
                     └──attempts exhausted──> failed
```

## Global constraints

- 领取任务在 MySQL 中必须使用 `SELECT ... FOR UPDATE SKIP LOCKED`。
- `attempt` 在成功领取租约时递增；达到 `max_attempts` 后不得再次执行。
- 只有持有匹配 `worker_id` 且租约未丢失的 Worker 可以 heartbeat、完成或失败任务。
- 同一 `(job_type, idempotency_key)` 只能产生一条逻辑任务。
- payload、结果和错误信息必须可序列化；错误不得包含凭据或完整堆栈。
- Worker 进程退出不改变业务状态；租约到期后由 Reaper 恢复。
- Runner 的轮询和重试不得依赖应用进程内存。
- Core 不得导入 runner、SQLAlchemy 或 ORM。
- SQLite 只用于确定性单元测试；并发领取和锁语义由 MySQL CI 测试验证。

---

### Task 1: Job schema and migration

**Files:**
- Modify: `src/asharelens/storage/models.py`
- Create: `migrations/versions/20260729_0002_runner_jobs.py`
- Create: `tests/runner/test_job_schema.py`
- Modify: `tests/storage/test_migration.py`

- [ ] **Step 1: Write failing schema and migration tests**

Prove the job table contains status, priority, availability, attempts, lease, heartbeat, payload, result, timestamps, a unique idempotency key, and the claim-path index.

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/runner/test_job_schema.py tests/storage/test_migration.py -v`

- [ ] **Step 3: Implement `RunnerJobRow` and Alembic revision**

Use bounded strings for type/status/worker/error and JSON for payload/result. Store UTC as naive `DATETIME(6)`.

- [ ] **Step 4: Verify and commit**

Commit: `feat: add durable runner job schema`

### Task 2: Lease-based task broker

**Files:**
- Create: `src/asharelens/runner/__init__.py`
- Create: `src/asharelens/runner/models.py`
- Create: `src/asharelens/runner/job_repository.py`
- Create: `tests/runner/test_job_repository.py`

- [ ] **Step 1: Write failing repository tests**

Prove idempotent enqueue, deterministic priority ordering, claim ownership, heartbeat, completion, retry backoff, terminal failure and expired-lease recovery.

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/runner/test_job_repository.py -v`

- [ ] **Step 3: Implement repository-owned state transitions**

Repository methods may flush but never commit. The caller owns transaction commit/rollback.

- [ ] **Step 4: Add opt-in MySQL concurrent-claim coverage**

Two independent sessions must never claim the same job. This test joins the existing `mysql` CI gate.

- [ ] **Step 5: Verify and commit**

Commit: `feat: implement lease based task broker`

### Task 3: Executor registry, worker and reaper

**Files:**
- Create: `src/asharelens/runner/executor.py`
- Create: `src/asharelens/runner/worker.py`
- Create: `tests/runner/test_worker.py`

- [ ] **Step 1: Write failing worker tests**

Prove successful dispatch, unknown job failure, retryable exception, permanent exception, heartbeat during long execution, and safe recovery after simulated process loss.

- [ ] **Step 2: Implement `ExecutorRegistry`, `Worker.run_once` and `Reaper.run_once`**

Executors receive an immutable job snapshot and an explicit heartbeat callback. No executor may commit the queue transaction itself.

- [ ] **Step 3: Verify and commit**

Commit: `feat: execute and recover durable jobs`

### Task 4: Persistent schedules

**Files:**
- Modify: `src/asharelens/storage/models.py`
- Create: `migrations/versions/20260729_0003_runner_schedules.py`
- Create: `src/asharelens/runner/scheduler.py`
- Create: `tests/runner/test_scheduler.py`

- [ ] **Step 1: Write failing schedule tests**

Prove enabled schedules emit exactly one job per planned fire time, missed fires are bounded, disabled schedules do nothing, and timezone conversion uses `Asia/Shanghai` at the boundary while persistence stays UTC.

- [ ] **Step 2: Implement schedule model and scheduler**

The first format is a daily local time plus weekdays. Keep a schedule calculator protocol so cron support can be added without changing the queue.

- [ ] **Step 3: Verify and commit**

Commit: `feat: schedule daily jobs persistently`

### Task 5: Daily simulation workflow

**Files:**
- Create: `src/asharelens/runner/workflows/daily_simulation.py`
- Create: `src/asharelens/storage/simulation_repository.py`
- Modify: `src/asharelens/storage/models.py`
- Create: `migrations/versions/20260729_0004_simulation_ledger.py`
- Create: `tests/runner/test_daily_simulation.py`

- [ ] **Step 1: Write failing equivalence and idempotency tests**

For the same snapshot, strategy identity and parameters, replaying sessions through daily jobs must produce the same candidates, orders, fills and NAV as `DailyCycleEngine.run`. Re-running one date must not duplicate any ledger row.

- [ ] **Step 2: Implement immutable run and ledger persistence**

Persist the run fingerprint, exact partition IDs, strategy version, parameters, engine version, input state hash and output state hash.

- [ ] **Step 3: Verify and commit**

Commit: `feat: run daily simulation on shared engine`

### Task 6: Runner CLI and phase audit

**Files:**
- Modify: `src/asharelens/cli.py`
- Create: `tests/test_runner_cli.py`
- Modify: `README.md`
- Modify: `.github/workflows/ci.yml`
- Modify: `docs/superpowers/plans/2026-07-29-durable-runner.md`

- [ ] **Step 1: Add `runner work`, `runner reap`, `runner schedule` and `runner doctor`**

Commands must support one-shot mode for tests and long-running mode for Docker. Graceful shutdown must stop claiming new work, then finish or release the active lease.

- [ ] **Step 2: Run phase verification**

```text
python -m pytest --cov=asharelens --cov-report=term-missing
python -m ruff check .
python -m mypy src
python -m build --no-isolation
```

- [ ] **Step 3: Record evidence and commit**

Commit: `docs: record durable runner verification`
