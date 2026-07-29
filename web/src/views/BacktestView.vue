<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute } from "vue-router";

import ParameterForm from "@/components/ParameterForm.vue";
import { api } from "@/lib/api";
import type { ParameterValues } from "@/lib/jsonSchema";
import type { StrategyCatalogItem } from "@/lib/types";

const route = useRoute();
const strategies = ref<StrategyCatalogItem[]>([]);
const loading = ref(true);
const error = ref("");
const parameters = ref<ParameterValues>({});
const parametersValid = ref(false);

const selectedId = computed(() =>
  typeof route.query.strategy === "string" ? route.query.strategy : "",
);
const selected = computed(() =>
  strategies.value.find((item) => item.strategy_id === selectedId.value),
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
            @validity-change="parametersValid = $event"
          />
          <div class="dataset-stamp">
            <strong>确定性合成数据</strong>
            <span>
              不联网 · 3 只演示股票 ·
              {{ parametersValid ? "参数格式通过" : "请检查参数" }}
            </span>
          </div>
        </template>
        <div v-else class="empty-experiment">
          <span class="empty-experiment__lens"></span>
          <h2>从左侧选择一个策略</h2>
          <p>下一步将根据策略的 Python 参数模型自动生成配置表单。</p>
        </div>
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

  .dataset-stamp {
    display: grid;
    gap: 6px;
  }
}
</style>
