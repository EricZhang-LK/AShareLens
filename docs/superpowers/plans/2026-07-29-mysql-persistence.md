# AShareLens MySQL Persistence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 使用 MySQL 8.4 LTS 持久化数据批次、单源分区、质量报告和当前发布指针，并提供可迁移、幂等、事务化的仓储接口。

**Architecture:** `asharelens.storage` 是数据层之外的适配器，不进入 `asharelens.core`。SQLAlchemy 2 定义跨测试数据库可执行的 ORM 模型，Alembic 是唯一生产建表方式。写入流程先保存不可变批次和分区，再在同一事务中原子更新 `(dataset, partition_date)` 发布指针。

**Tech Stack:** Python 3.12、SQLAlchemy 2、Alembic、PyMySQL、MySQL 8.4 LTS、pytest。

## Global Constraints

- 生产数据库固定为 MySQL 8.4 LTS、InnoDB、utf8mb4。
- ORM 使用 SQLAlchemy 2 类型化声明，迁移使用 Alembic。
- 应用时间按 `Asia/Shanghai` 展示；数据库时间统一保存为 UTC。
- 价格使用定点 `DECIMAL`，不得以 MySQL FLOAT 保存成交或行情价格。
- 原始批次和数据分区不可更新，只能新增版本。
- 当前发布指针可以更新，但必须与分区写入处于同一事务。
- `(provider_id, source_batch_id, dataset)`、分区内容哈希和当前发布键必须有唯一约束。
- 不可发布的质量报告不得更新当前指针。
- 单元测试可用 SQLite 验证仓储行为；MySQL 方言 DDL 和 CI 中的 MySQL 8.4 集成测试是额外强制门禁。
- Core 继续禁止导入 SQLAlchemy 或 Alembic。

---

### Task 1: Storage dependencies, engine factory, and ORM schema

**Files:**
- Modify: `pyproject.toml`
- Create: `src/asharelens/storage/__init__.py`
- Create: `src/asharelens/storage/database.py`
- Create: `src/asharelens/storage/models.py`
- Create: `tests/storage/test_schema.py`

**Interfaces:**
- Consumes: SQLAlchemy URL and engine options.
- Produces: `Base`, `create_database_engine(url)`, `create_session_factory(engine)`, `IngestionBatchRow`, `DataPartitionRow`, `DailyBarRow`, and `PublishedPartitionRow`.

- [ ] **Step 1: Add optional server dependencies**

Add an extra containing:

```toml
server = [
  "alembic>=1.14,<2",
  "pymysql>=1.1,<2",
  "sqlalchemy>=2.0.36,<3",
]
```

Add the same packages to the development extra so storage tests run in CI.

- [ ] **Step 2: Write failing schema tests**

Tests must prove:

- SQLite memory metadata creation succeeds for repository unit tests.
- MySQL DDL compiles with `ENGINE=InnoDB` and `utf8mb4`.
- Daily prices compile as `DECIMAL`, not `FLOAT`.
- Required unique constraints exist.
- `asharelens.core` imports no storage module.

- [ ] **Step 3: Run and verify RED**

Run: `python -m pytest tests/storage/test_schema.py -v`

- [ ] **Step 4: Implement the engine and typed schema**

Use SQLAlchemy `DeclarativeBase`, `Mapped`, and `mapped_column`. Store UUID-like IDs as lowercase 36-character strings for readable Alpha diagnostics. Use JSON columns for request and quality details, and `DateTime(timezone=False)` for UTC-normalized persistence.

- [ ] **Step 5: Run full verification and commit**

```text
python -m pytest -q
python -m ruff check .
python -m mypy src
git add pyproject.toml src/asharelens/storage tests/storage
git commit -m "feat: define mysql persistence schema"
```

### Task 2: Initial Alembic migration

**Files:**
- Create: `alembic.ini`
- Create: `migrations/env.py`
- Create: `migrations/script.py.mako`
- Create: `migrations/versions/20260729_0001_initial.py`
- Create: `tests/storage/test_migration.py`

**Interfaces:**
- Consumes: `ASHARELENS_DATABASE_URL` and ORM metadata.
- Produces: upgrade from an empty database to revision `20260729_0001`, plus downgrade for disposable test databases.

- [ ] **Step 1: Write failing migration tests**

Tests must create a temporary SQLite database, run Alembic upgrade to head, inspect the four required tables and constraints, run downgrade to base, and verify the tables are removed.

- [ ] **Step 2: Run and verify RED**

Run: `python -m pytest tests/storage/test_migration.py -v`

- [ ] **Step 3: Implement configuration and migration**

`migrations/env.py` must read `ASHARELENS_DATABASE_URL`, fall back to `sqlite:///./asharelens.db` only for local SDK development, import `Base.metadata`, and enable batch mode only for SQLite.

- [ ] **Step 4: Verify migration and commit**

```text
python -m pytest tests/storage/test_migration.py -v
python -m pytest -q
git add alembic.ini migrations tests/storage/test_migration.py
git commit -m "feat: add initial database migration"
```

### Task 3: Idempotent batch and partition repository

**Files:**
- Create: `src/asharelens/storage/data_repository.py`
- Create: `tests/storage/test_data_repository.py`

**Interfaces:**
- Consumes: `DataBatch`, `DataPartition`, and `QualityReport`.
- Produces: `DataRepository.record_batch(...)`, `publish_daily_partition(...)`, `get_published_daily_bars(...)`, and stable publication result IDs.

- [ ] **Step 1: Write failing repository tests**

Tests must prove:

- Recording the same source batch twice returns the same row.
- Publishing the same content twice returns the same partition ID and does not duplicate bars.
- Publishing a newer content hash atomically moves the current pointer.
- A failure-level quality report raises `UnpublishablePartition` and leaves the previous pointer unchanged.
- Retrieved bars and lineage identify the exact Provider, source batch and content hash.

- [ ] **Step 2: Run and verify RED**

Run: `python -m pytest tests/storage/test_data_repository.py -v`

- [ ] **Step 3: Implement transaction boundaries**

Repository methods accept a SQLAlchemy `Session` owned by the caller. They may flush but must not commit; service and Runner layers own commit or rollback. Normalize aware datetimes to naive UTC on write.

- [ ] **Step 4: Run full verification and commit**

```text
python -m pytest -q
python -m ruff check .
python -m mypy src
git add src/asharelens/storage/data_repository.py tests/storage/test_data_repository.py
git commit -m "feat: publish data partitions transactionally"
```

### Task 4: MySQL 8.4 integration gate

**Files:**
- Create: `tests/integration/test_mysql_storage.py`
- Modify: `.github/workflows/ci.yml`
- Modify: `pyproject.toml`

**Interfaces:**
- Consumes: `ASHARELENS_TEST_DATABASE_URL`.
- Produces: pytest marker `mysql` and CI job backed by `mysql:8.4`.

- [ ] **Step 1: Write the opt-in integration test**

The test skips only when the environment variable is absent. When present it must run the migration, record and publish a partition twice, prove idempotency, query `information_schema` for InnoDB and utf8mb4, then downgrade the disposable schema.

- [ ] **Step 2: Add the GitHub Actions MySQL service**

Use `mysql:8.4`, a health command, a dedicated test database and non-root application user. Do not expose credentials in logs.

- [ ] **Step 3: Verify locally available checks**

Run:

```text
python -m pytest -m "not mysql" -q
python -m ruff check .
python -m mypy src
```

Local MySQL execution is recorded as unavailable when Docker and local MySQL are absent; CI remains the authoritative MySQL runtime gate.

- [ ] **Step 4: Commit**

```text
git add tests/integration/test_mysql_storage.py .github/workflows/ci.yml pyproject.toml
git commit -m "ci: verify persistence against mysql 8.4"
```

### Task 5: Database diagnostics and phase audit

**Files:**
- Modify: `src/asharelens/cli.py`
- Create: `tests/test_database_cli.py`
- Modify: `README.md`
- Modify: `docs/superpowers/plans/2026-07-29-mysql-persistence.md`

**Interfaces:**
- Consumes: a database URL from environment or option.
- Produces: `asharelens database check` with sanitized dialect, migration revision and connection status.

- [ ] **Step 1: Write failing CLI tests**

Tests must prove a healthy SQLite test database reports the current revision, an unreachable MySQL URL returns code 1 without printing the password, and no stack trace is displayed by default.

- [ ] **Step 2: Implement diagnostics and documentation**

Document MySQL 8.4 requirements, UTC storage, migration commands, backup-before-upgrade policy and the fact that SQLite is a test/SDK convenience rather than a supported server database.

- [ ] **Step 3: Run phase verification**

```text
python -m pytest --cov=asharelens --cov-report=term-missing
python -m ruff check .
python -m mypy src
python -m build --no-isolation
python -m asharelens.cli demo --json
```

- [ ] **Step 4: Record evidence and commit**

```text
git add src/asharelens/cli.py tests/test_database_cli.py README.md docs/superpowers/plans/2026-07-29-mysql-persistence.md
git commit -m "docs: record mysql persistence verification"
```

