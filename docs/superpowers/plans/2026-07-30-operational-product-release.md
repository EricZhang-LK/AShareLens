# AShareLens Operational Product Release Plan

> Execute task-by-task with tests first. A container that merely starts is not
> accepted; the deployed daily research loop must be functional.

**Goal:** Complete the first public alpha as a dependable local product:
configure trusted strategy plugins and market-data sources, synchronize
traceable data, advance paper portfolios with the shared engine, enqueue
explainable notifications, run the workflow on a durable schedule, and deploy
the Web and Runner services with one Docker Compose command.

**Architecture:** Keep market data, strategy, execution, persistence and
transport behind existing contracts. Add a small application composition layer
that converts validated environment/job configuration into provider, strategy,
notifier and executor registries. The durable MySQL Runner remains the only
queue; separate default and notification workers avoid head-of-line blocking
without requiring Redis or Celery. Python entry points are the supported plugin
boundary and are explicitly documented as trusted code.

**Operational contract:** BaoStock is the first zero-registration source;
AkShare is an optional fallback and Tushare is opt-in. A daily pipeline
synchronizes an immutable historical window, publishes only quality-approved
partitions, processes missing sessions chronologically, and sends only the
latest new result. No-data holidays are successful no-ops; provider outages are
retryable; invalid configuration and quality failures are terminal and visible.

---

### Task 1: Close reproducibility gaps in the shared engine

**Files:**
- Modify: `src/asharelens/core/engine.py`
- Modify: `src/asharelens/storage/models.py`
- Modify: `src/asharelens/storage/simulation_repository.py`
- Modify: `src/asharelens/runner/workflows/daily_simulation.py`
- Create: `migrations/versions/20260730_0006_simulation_execution_config.py`
- Modify/Create: relevant Core, migration and simulation tests

- [x] Pass point-in-time fundamentals through historical and daily invocations.
- [x] Persist and fingerprint execution model, initial cash, top-N and max weight.
- [x] Reject same-date replays whose execution configuration changed.
- [x] Verify migration, unit tests, lint and types; commit.

### Task 2: Public trusted Python strategy plugin boundary

**Files:**
- Modify: `pyproject.toml`
- Modify: `src/asharelens/strategies/registry.py`
- Modify: `src/asharelens/server/services/research.py`
- Create: `docs/strategy-plugin.md`
- Modify/Create: registry and API tests

- [x] Discover `asharelens.strategies` entry points in deterministic order.
- [x] Validate metadata, plugin API compatibility, duplicate IDs and parameter
  models before exposing a plugin.
- [x] Merge built-ins and installed plugins into the same JSON-Schema catalog.
- [x] Provide a minimal independently installable strategy example and state
  clearly that plugins are trusted Python code.
- [x] Verify tests, lint and types; commit.

### Task 3: Traceable market synchronization and daily pipeline

**Files:**
- Modify: `src/asharelens/storage/data_repository.py`
- Create: `src/asharelens/runner/workflows/market_sync.py`
- Create: `src/asharelens/runner/workflows/daily_pipeline.py`
- Create: workflow tests

- [x] Fetch a date range through ordered whole-batch provider fallback.
- [x] Quality-check every returned daily partition before atomic publication.
- [x] Load ordered published history with exact partition lineage.
- [x] Create or resume a named paper account, catch up missed trading sessions,
  and enqueue one explainable notification for the latest new run.
- [x] Classify no-data, provider outages, quality failures and bad configuration
  into deterministic no-op, retryable or permanent outcomes.
- [x] Verify tests, lint and types; commit.

### Task 4: Production composition and operator commands

**Files:**
- Create: `src/asharelens/config.py`
- Create: `src/asharelens/runtime.py`
- Modify: `src/asharelens/cli.py`
- Create/Modify: CLI and runtime tests

- [x] Parse environment configuration without logging credentials.
- [x] Register daily-pipeline and notification executors in real Runner commands.
- [x] Register console plus optional HTTPS webhook notifiers.
- [x] Add idempotent commands to initialize the daily schedule and run a manual
  daily cycle.
- [x] Fail fast on migrations/configuration and expose safe diagnostics.
- [x] Verify tests, lint and types; commit.

### Task 5: Docker one-command deployment

**Files:**
- Create: `Dockerfile`
- Create: `compose.yaml`
- Create: `.dockerignore`
- Create: `.env.example`
- Modify: `.github/workflows/ci.yml`
- Modify/Create: deployment tests and documentation

- [ ] Build Vue assets and Python runtime in reproducible multi-stage images.
- [ ] Run as a non-root user with health checks and graceful shutdown.
- [ ] Compose MySQL 8.4, one-shot migration, Web, default Runner and notification
  Runner; expose only the Web port on loopback by default.
- [ ] Persist MySQL data, keep secrets outside images, and declare startup order.
- [ ] Validate Dockerfile/Compose structure locally and build images in CI.
- [ ] Verify tests; commit.

### Task 6: GitHub-ready open-source release surface

**Files:**
- Modify: `README.md`
- Create: `CONTRIBUTING.md`
- Create: `SECURITY.md`
- Create: `CODE_OF_CONDUCT.md`
- Create: `CHANGELOG.md`
- Create: `.github/ISSUE_TEMPLATE/*`
- Create: `.github/pull_request_template.md`
- Create: `docs/architecture.md`
- Create: `docs/operations.md`

- [ ] Write a Chinese-first five-minute quick start and honest capability matrix.
- [ ] Document architecture, execution timing, data lineage, plugin development,
  backup/upgrade/recovery and troubleshooting.
- [ ] Add contribution, security, conduct, issue and pull-request workflows.
- [ ] Add release metadata, final license/security scan and clean-install checks.
- [ ] Run the full Python/frontend/build test matrix and record evidence; commit.
