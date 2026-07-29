<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";

import NavChart from "@/components/NavChart.vue";
import ParameterForm from "@/components/ParameterForm.vue";
import SignalTable from "@/components/SignalTable.vue";
import { useBacktest } from "@/composables/useBacktest";
import { api } from "@/lib/api";
import type { ParameterValues } from "@/lib/jsonSchema";
import type { StrategyCatalogItem } from "@/lib/types";

const route = useRoute();
const strategies = ref<StrategyCatalogItem[]>([]);
const loading = ref(true);
const error = ref("");
const parameters = ref<ParameterValues>({});
const parametersValid = ref(false);
const sessions = ref(160);
const initialCash = ref(100000);
const topN = ref(2);
const maxWeight = ref(0.5);
const copied = ref(false);
const {
  status,
  result,
  message,
  serverErrors,
  busy,
  run,
  reset,
  clearErrors,
} = useBacktest();

const selectedId = computed(() =>
  typeof route.query.strategy === "string" ? route.query.strategy : "",
);
const selected = computed(() =>
  strategies.value.find((item) => item.strategy_id === selectedId.value),
);
const settingsValid = computed(
  () =>
    Number.isInteger(sessions.value) &&
    sessions.value >= 40 &&
    sessions.value <= 500 &&
    initialCash.value > 0 &&
    initialCash.value <= 1_000_000_000 &&
    Number.isInteger(topN.value) &&
    topN.value >= 1 &&
    topN.value <= 3 &&
    maxWeight.value > 0 &&
    maxWeight.value <= 1,
);

onMounted(async () => {
  try {
    strategies.value = (await api.strategies()).items.filter(
      (item) => item.demo_supported,
    );
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "回测配置读取失败。";
  } finally {
    loading.value = false;
  }
});

watch(selectedId, () => {
  reset();
  parameters.value = {};
});

watch(parameters, clearErrors, { deep: true });

async function runBacktest(): Promise<void> {
  if (
    !selected.value ||
    !parametersValid.value ||
    !settingsValid.value ||
    busy.value
  ) {
    return;
  }
  await run({
    strategy_id: selected.value.strategy_id,
    parameters: parameters.value,
    sessions: sessions.value,
    initial_cash: initialCash.value,
    top_n: topN.value,
    max_weight: maxWeight.value,
  });
}

async function copyFingerprint(): Promise<void> {
  if (!result.value) return;
  await navigator.clipboard.writeText(result.value.fingerprint);
  copied.value = true;
  window.setTimeout(() => {
    copied.value = false;
  }, 1600);
}

const money = new Intl.NumberFormat("zh-CN", {
  style: "currency",
  currency: "CNY",
  maximumFractionDigits: 2,
});
</script>

<template>
  <article>
    <header class="page-heading">
      <div>
        <span class="section-kicker">Backtest laboratory</span>
        <h1>把想法放进<br />时间里检验。</h1>
      </div>
      <p class="page-heading__note">
        信号在收盘后生成，订单只在下一交易日开盘尝试成交。所有费用明确列出，
        历史回测与每日模拟使用同一套内核。
      </p>
    </header>

    <div v-if="loading" class="loading-state" role="status">正在准备回测实验室……</div>
    <div v-else-if="error" class="error-state" role="alert">{{ error }}</div>
    <section v-else class="lab-layout">
      <aside class="experiment-index">
        <span class="section-kicker">Experiment</span>
        <h2>选择实验策略</h2>
        <nav aria-label="回测策略">
          <RouterLink
            v-for="(item, index) in strategies"
            :key="item.strategy_id"
            :to="{ path: '/backtest', query: { strategy: item.strategy_id } }"
            :class="{ active: item.strategy_id === selectedId }"
          >
            <span>{{ String(index + 1).padStart(2, "0") }}</span>
            <strong>{{ item.name }}</strong>
          </RouterLink>
        </nav>
      </aside>

      <div class="experiment-canvas panel">
        <template v-if="selected">
          <span class="eyebrow">SELECTED STRATEGY</span>
          <h2>{{ selected.name }}</h2>
          <p>{{ selected.description }}</p>
          <ParameterForm
            :key="selected.strategy_id"
            v-model="parameters"
            :schema="selected.parameter_schema"
            :server-errors="serverErrors"
            @validity-change="parametersValid = $event"
          />
          <fieldset class="run-settings">
            <legend>回测设置</legend>
            <label>
              <span>交易日数</span>
              <input v-model.number="sessions" type="number" min="40" max="500" />
            </label>
            <label>
              <span>初始资金</span>
              <input
                v-model.number="initialCash"
                type="number"
                min="1000"
                max="1000000000"
              />
            </label>
            <label>
              <span>最多持股</span>
              <input v-model.number="topN" type="number" min="1" max="3" />
            </label>
            <label>
              <span>单股上限</span>
              <input
                v-model.number="maxWeight"
                type="number"
                min="0.01"
                max="1"
                step="0.01"
              />
            </label>
          </fieldset>
          <div class="dataset-stamp">
            <strong>确定性合成数据</strong>
            <span>
              不联网 · 3 只演示股票 ·
              {{ parametersValid ? "参数格式通过" : "请检查参数" }}
            </span>
          </div>
          <div v-if="message" class="run-error" role="alert">
            {{ message }}
          </div>
          <button
            type="button"
            class="run-button"
            :disabled="!parametersValid || !settingsValid || busy"
            @click="runBacktest"
          >
            <span v-if="status === 'validating'">正在用 Python 模型校验参数……</span>
            <span v-else-if="status === 'running'">正在按交易日推进回测……</span>
            <span v-else>运行离线回测</span>
            <span aria-hidden="true">→</span>
          </button>
        </template>
        <div v-else class="empty-experiment">
          <span class="empty-experiment__lens"></span>
          <h2>从左侧选择一个策略</h2>
          <p>下一步将根据策略的 Python 参数模型自动生成配置表单。</p>
        </div>
      </div>
    </section>

    <section v-if="result" class="results" aria-live="polite">
      <div class="demo-warning">
        <strong>演示数据</strong>
        <span>{{ result.warning }}</span>
      </div>
      <div class="summary-grid">
        <div>
          <span>总收益率</span>
          <strong :class="{ positive: result.summary.total_return_pct >= 0 }">
            {{ result.summary.total_return_pct.toFixed(2) }}%
          </strong>
        </div>
        <div>
          <span>最大回撤</span>
          <strong>{{ result.summary.max_drawdown_pct.toFixed(2) }}%</strong>
        </div>
        <div>
          <span>期末净值</span>
          <strong class="summary-money">{{ money.format(result.summary.final_nav) }}</strong>
        </div>
        <div>
          <span>模拟成交</span>
          <strong>{{ result.summary.fills }}</strong>
          <small>{{ result.summary.orders }} 笔订单</small>
        </div>
      </div>

      <div class="result-grid">
        <NavChart :points="result.nav" />
        <aside class="cost-sheet">
          <span class="eyebrow">EXECUTION COSTS</span>
          <h3>成交费用</h3>
          <dl>
            <dt>佣金</dt><dd>{{ money.format(result.costs.commission) }}</dd>
            <dt>过户费</dt><dd>{{ money.format(result.costs.transfer_fee) }}</dd>
            <dt>印花税</dt><dd>{{ money.format(result.costs.stamp_duty) }}</dd>
            <dt class="total">合计</dt>
            <dd class="total">{{ money.format(result.costs.total) }}</dd>
          </dl>
          <p>信号在收盘生成，成交发生于严格更晚的交易日开盘。</p>
        </aside>
      </div>

      <SignalTable :candidates="result.latest_candidates" />

      <div class="fingerprint">
        <div>
          <span class="eyebrow">REPRODUCIBLE RUN</span>
          <strong>运行指纹</strong>
          <p>覆盖策略版本、参数、数据快照、资金、仓位约束与成交模型。</p>
        </div>
        <code>{{ result.fingerprint }}</code>
        <button type="button" @click="copyFingerprint">
          {{ copied ? "已复制" : "复制" }}
        </button>
      </div>
    </section>
  </article>
</template>

<style scoped>
.lab-layout {
  display: grid;
  grid-template-columns: minmax(220px, 0.32fr) minmax(0, 1fr);
  gap: 34px;
  align-items: start;
}

.experiment-index {
  position: sticky;
  top: 28px;
  padding-top: 4px;
}

.experiment-index h2 {
  margin: 12px 0 25px;
  font-family: var(--display);
  font-size: 25px;
  font-weight: 520;
}

.experiment-index nav {
  border-top: 1px solid var(--line-strong);
}

.experiment-index a {
  display: grid;
  grid-template-columns: 35px 1fr;
  gap: 8px;
  padding: 15px 8px;
  color: var(--ink-soft);
  border-bottom: 1px solid var(--line);
  text-decoration: none;
}

.experiment-index a span {
  color: var(--ink-faint);
  font-family: var(--mono);
  font-size: 9px;
}

.experiment-index a strong {
  font-family: var(--display);
  font-size: 15px;
  font-weight: 520;
}

.experiment-index a.active {
  color: var(--cinnabar);
  background: linear-gradient(90deg, rgba(182, 61, 46, 0.08), transparent);
}

.experiment-canvas {
  min-height: 490px;
  padding: 40px;
}

.experiment-canvas h2 {
  margin: 12px 0 8px;
  font-family: var(--display);
  font-size: 38px;
  font-weight: 520;
}

.experiment-canvas > p {
  max-width: 650px;
  color: var(--ink-soft);
  font-size: 13px;
  line-height: 1.8;
}

.dataset-stamp {
  display: flex;
  justify-content: space-between;
  margin-top: 32px;
  padding-top: 17px;
  color: var(--jade);
  border-top: 1px solid var(--line);
  font-size: 11px;
}

.dataset-stamp span {
  color: var(--ink-faint);
}

.run-settings {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 14px;
  margin: 24px 0 0;
  padding: 19px 0 0;
  border: 0;
  border-top: 1px solid var(--line);
}

.run-settings legend {
  padding: 0;
  color: var(--ink-faint);
  font-family: var(--mono);
  font-size: 9px;
}

.run-settings label span {
  display: block;
  margin-bottom: 7px;
  color: var(--ink-soft);
  font-size: 9px;
}

.run-settings input {
  width: 100%;
  min-height: 38px;
  padding: 0 10px;
  color: var(--ink);
  background: rgba(255, 253, 247, 0.72);
  border: 1px solid var(--line-strong);
}

.run-button {
  display: flex;
  width: 100%;
  min-height: 52px;
  align-items: center;
  justify-content: space-between;
  margin-top: 22px;
  padding: 0 20px;
  color: #fff8ec;
  background: var(--cinnabar);
  border: 0;
  cursor: pointer;
  font-family: var(--display);
  font-size: 15px;
}

.run-button:hover:not(:disabled) {
  background: var(--cinnabar-dark);
}

.run-button:disabled {
  cursor: not-allowed;
  opacity: 0.48;
}

.run-error {
  margin-top: 17px;
  padding: 11px 13px;
  color: var(--cinnabar-dark);
  background: rgba(182, 61, 46, 0.07);
  border-left: 2px solid var(--cinnabar);
  font-size: 11px;
}

.empty-experiment {
  display: grid;
  min-height: 400px;
  place-content: center;
  text-align: center;
}

.empty-experiment__lens {
  width: 68px;
  height: 68px;
  margin: 0 auto 14px;
  border: 1px solid var(--line-strong);
  border-radius: 50%;
  box-shadow: 18px 18px 0 -16px var(--cinnabar);
}

.empty-experiment h2 {
  font-size: 25px;
}

.empty-experiment p {
  color: var(--ink-faint);
  font-size: 12px;
}

.results {
  margin-top: 74px;
  scroll-margin-top: 20px;
}

.demo-warning {
  display: flex;
  gap: 18px;
  align-items: center;
  padding: 13px 17px;
  color: #f9f2e4;
  background: var(--cinnabar-dark);
  font-size: 11px;
}

.demo-warning strong {
  padding-right: 18px;
  border-right: 1px solid rgba(255, 255, 255, 0.3);
  font-family: var(--display);
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  margin-top: 24px;
  border-top: 1px solid var(--line-strong);
  border-bottom: 1px solid var(--line-strong);
}

.summary-grid > div {
  min-height: 145px;
  padding: 23px;
  border-right: 1px solid var(--line);
}

.summary-grid > div:last-child {
  border-right: 0;
}

.summary-grid span,
.summary-grid small {
  display: block;
  color: var(--ink-faint);
  font-size: 9px;
}

.summary-grid strong {
  display: block;
  margin-top: 23px;
  font-family: var(--display);
  font-size: 31px;
  font-weight: 520;
}

.summary-grid strong.positive {
  color: var(--cinnabar);
}

.summary-grid .summary-money {
  font-size: 23px;
}

.summary-grid small {
  margin-top: 6px;
}

.result-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 235px;
  gap: 24px;
  margin-top: 25px;
}

.cost-sheet {
  padding: 24px;
  color: #f6f0e2;
  background: var(--ink);
}

.cost-sheet h3 {
  margin: 8px 0 23px;
  font-family: var(--display);
  font-size: 20px;
}

.cost-sheet dl {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 12px;
  margin: 0;
  font-family: var(--mono);
  font-size: 9px;
}

.cost-sheet dt {
  color: rgba(246, 240, 226, 0.55);
}

.cost-sheet dd {
  margin: 0;
}

.cost-sheet .total {
  margin-top: 8px;
  padding-top: 12px;
  color: #ef8a76;
  border-top: 1px solid rgba(255, 255, 255, 0.18);
}

.cost-sheet p {
  margin: 27px 0 0;
  color: rgba(246, 240, 226, 0.48);
  font-family: var(--display);
  font-size: 10px;
  line-height: 1.7;
}

.fingerprint {
  display: grid;
  grid-template-columns: minmax(170px, 0.5fr) minmax(0, 1fr) auto;
  gap: 25px;
  align-items: center;
  margin-top: 31px;
  padding: 24px 26px;
  border: 1px solid var(--line-strong);
}

.fingerprint strong {
  display: block;
  margin-top: 6px;
  font-family: var(--display);
  font-size: 18px;
}

.fingerprint p {
  margin: 7px 0 0;
  color: var(--ink-faint);
  font-size: 9px;
  line-height: 1.5;
}

.fingerprint > code {
  overflow: hidden;
  color: var(--jade);
  font-family: var(--mono);
  font-size: 9px;
  text-overflow: ellipsis;
}

.fingerprint button {
  padding: 8px 12px;
  color: var(--ink);
  background: transparent;
  border: 1px solid var(--line-strong);
  cursor: pointer;
  font-size: 10px;
}

@media (max-width: 760px) {
  .lab-layout {
    grid-template-columns: 1fr;
  }

  .experiment-index {
    position: static;
  }

  .experiment-index nav {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
  }

  .experiment-index a {
    grid-template-columns: 1fr;
    text-align: center;
  }

  .experiment-canvas {
    padding: 28px 22px;
  }

  .run-settings,
  .summary-grid {
    grid-template-columns: repeat(2, 1fr);
  }

  .result-grid {
    grid-template-columns: 1fr;
  }

  .fingerprint {
    grid-template-columns: 1fr auto;
  }

  .fingerprint > div {
    grid-column: 1 / -1;
  }

  .dataset-stamp {
    display: grid;
    gap: 6px;
  }
}

@media (max-width: 500px) {
  .run-settings,
  .summary-grid {
    grid-template-columns: 1fr;
  }

  .summary-grid > div {
    border-right: 0;
    border-bottom: 1px solid var(--line);
  }

  .fingerprint {
    grid-template-columns: 1fr;
  }

  .fingerprint button {
    justify-self: start;
  }
}
</style>
