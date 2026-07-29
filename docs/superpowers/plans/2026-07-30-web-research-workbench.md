# AShareLens Web Research Workbench Implementation Plan

> Execute task-by-task with tests first. Keep the domain Core independent from
> FastAPI and Vue.

**Goal:** Ship a Chinese-first, non-technical research workbench backed by real
AShareLens APIs: system overview, provider capabilities, strategy discovery,
schema-driven parameters, validation, offline backtests, explanations, and
reproducible fingerprints.

**Architecture:** `asharelens.server` is a thin FastAPI adapter over application
services and existing registries. It never embeds strategy-specific fields.
`web/` is a Vue 3 + TypeScript static SPA built by Vite and served from the same
origin in production. API models remain explicit and versioned under `/api/v1`.
The frontend consumes Pydantic JSON Schema directly through a constrained form
renderer, so a new compatible Python strategy gains a Web form without frontend
code changes.

**Visual direction:** “Research folio + precision instrument”: warm paper,
charcoal ink, cinnabar action color, jade health accents, fine rules, tabular
numerals, and restrained page-entry motion. Dense evidence is progressive:
plain-language conclusions first, fingerprints and raw indicators on demand.

**Verified references:** current official FastAPI documentation for TestClient
and static frontend hosting; current official Vue guidance for Composition API,
TypeScript and Vite; official Vue Router and Vite release guidance.

---

### Task 1: Versioned FastAPI application boundary

**Files:**
- Modify: `pyproject.toml`
- Create: `src/asharelens/server/app.py`
- Create: `src/asharelens/server/models.py`
- Create: `src/asharelens/server/errors.py`
- Create: `tests/server/test_app.py`

- [x] Add pinned-compatible FastAPI/Uvicorn server dependencies and HTTPX tests.
- [x] Test app metadata, `/api/v1/health`, request IDs, JSON error envelopes, and
  no accidental database requirement for the liveness endpoint.
- [x] Implement an application factory with dependency injection seams.
- [x] Verify and commit.

### Task 2: Strategy catalog, validation and offline backtest API

**Files:**
- Modify: `src/asharelens/strategies/registry.py`
- Create: `src/asharelens/server/services/research.py`
- Create: `src/asharelens/server/routes/research.py`
- Create: `tests/server/test_research_api.py`

- [x] Test provider catalog and stable strategy catalog ordering.
- [x] Test schema-driven parameter validation and field-level 422 errors.
- [x] Test deterministic demo backtests, explanations, NAV series, summary
  metrics, and identical fingerprints for identical inputs.
- [x] Keep all four strategies discoverable; disclose when demo fundamentals are
  unavailable instead of fabricating them.
- [x] Verify and commit.

### Task 3: Vue TypeScript shell and design system

**Files:**
- Create: `web/package.json`
- Create: `web/package-lock.json`
- Create: `web/vite.config.ts`
- Create: `web/tsconfig*.json`
- Create: `web/index.html`
- Create: `web/src/main.ts`
- Create: `web/src/App.vue`
- Create: `web/src/router.ts`
- Create: `web/src/styles/*`
- Create: `web/src/views/*`

- [x] Scaffold Vue 3, TypeScript, Vue Router and Vite with reproducible lockfile.
- [x] Implement responsive desktop/mobile navigation, semantic focus states,
  reduced-motion support, loading/empty/error states, and the research-folio
  visual system.
- [x] Build Overview, Strategies, Backtest and Data Sources routes against the
  real API client.
- [x] Verify type-check and production build; commit.

### Task 4: JSON Schema automatic parameter form

**Files:**
- Create: `web/src/components/ParameterForm.vue`
- Create: `web/src/components/ParameterField.vue`
- Create: `web/src/lib/jsonSchema.ts`
- Create: `web/src/components/__tests__/ParameterForm.spec.ts`

- [ ] Support the strategy schema subset: integer, number, boolean, string,
  enum, defaults, descriptions, bounds, and required fields.
- [ ] Test defaults, coercion, accessible labels, constraints, errors, reset, and
  emitted normalized parameter values.
- [ ] Preserve unknown future schema fields as an explicit unsupported warning.
- [ ] Verify and commit.

### Task 5: Interactive backtest and explainable result views

**Files:**
- Create: `web/src/components/NavChart.vue`
- Create: `web/src/components/SignalTable.vue`
- Modify: `web/src/views/StrategyView.vue`
- Modify: `web/src/views/BacktestView.vue`
- Create: `web/src/lib/api.ts`
- Create: `web/src/lib/types.ts`

- [ ] Validate parameters through the API before running.
- [ ] Render summary, SVG NAV chart, selected/excluded signals, reason codes,
  indicator evidence, costs, and run fingerprint.
- [ ] Make demo-data labeling and investment-risk wording impossible to miss.
- [ ] Test the API client and core interaction state; verify and commit.

### Task 6: Same-origin production serving and CLI

**Files:**
- Create: `src/asharelens/server/frontend.py`
- Modify: `src/asharelens/server/app.py`
- Modify: `src/asharelens/cli.py`
- Modify: `pyproject.toml`
- Create: `tests/server/test_frontend.py`
- Modify: `README.md`

- [ ] Serve built assets with SPA fallback after `/api/v1` routes.
- [ ] Add `asharelens web` with local-only default host and explicit opt-in for
  other bindings.
- [ ] Test missing-build diagnostics, API route precedence, index/assets and SPA
  fallback.
- [ ] Verify and commit.

### Task 7: Phase audit

- [ ] Run Python tests with coverage, Ruff, mypy and package build.
- [ ] Run frontend unit tests, TypeScript checking and production build.
- [ ] Record versions and evidence without claiming real MySQL validation when
  no disposable MySQL URL is configured.
- [ ] Update README status and commit `docs: verify web research workbench`.
