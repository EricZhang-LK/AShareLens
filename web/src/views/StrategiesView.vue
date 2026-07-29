<script setup lang="ts">
import { onMounted, ref } from "vue";
import { RouterLink } from "vue-router";

import { api } from "@/lib/api";
import type { StrategyCatalogItem } from "@/lib/types";

const items = ref<StrategyCatalogItem[]>([]);
const loading = ref(true);
const error = ref("");

onMounted(async () => {
  try {
    items.value = (await api.strategies()).items;
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "策略目录读取失败。";
  } finally {
    loading.value = false;
  }
});

function parameterCount(item: StrategyCatalogItem): number {
  return Object.keys(item.parameter_schema.properties ?? {}).length;
}
</script>

<template>
  <article>
    <header class="page-heading">
      <div>
        <span class="section-kicker">Strategy folio</span>
        <h1>策略不是黑箱，<br />是一组可检验的规则。</h1>
      </div>
      <p class="page-heading__note">
        每个参数都来自 Python 策略自己的模型。增加新策略时，Web
        表单会随参数定义自动生成，不需要重复维护页面。
      </p>
    </header>

    <div v-if="loading" class="loading-state" role="status">正在读取策略目录……</div>
    <div v-else-if="error" class="error-state" role="alert">{{ error }}</div>
    <section v-else class="strategy-list" aria-label="可用策略">
      <article
        v-for="(item, index) in items"
        :key="item.strategy_id"
        class="strategy-sheet"
      >
        <div class="strategy-sheet__number">
          {{ String(index + 1).padStart(2, "0") }}
        </div>
        <div class="strategy-sheet__body">
          <div class="strategy-sheet__meta">
            <code>{{ item.strategy_id }}</code>
            <span>v{{ item.version }}</span>
          </div>
          <h2>{{ item.name }}</h2>
          <p>{{ item.description }}</p>
          <div class="strategy-sheet__facts">
            <span>至少 {{ item.min_history_sessions }} 个交易日</span>
            <span>{{ parameterCount(item) }} 个可调参数</span>
          </div>
          <p v-if="item.demo_limitation" class="strategy-sheet__limitation">
            {{ item.demo_limitation }}
          </p>
        </div>
        <RouterLink
          v-if="item.demo_supported"
          class="strategy-sheet__action"
          :to="{ path: '/backtest', query: { strategy: item.strategy_id } }"
          :aria-label="`配置并回测${item.name}`"
        >
          <span>配置</span><span aria-hidden="true">↗</span>
        </RouterLink>
        <span v-else class="strategy-sheet__status">待基本面数据</span>
      </article>
    </section>
  </article>
</template>

<style scoped>
.strategy-list {
  border-top: 1px solid var(--line-strong);
}

.strategy-sheet {
  display: grid;
  grid-template-columns: 72px minmax(0, 1fr) 104px;
  min-height: 200px;
  border-bottom: 1px solid var(--line-strong);
  transition: background 180ms ease;
}

.strategy-sheet:hover {
  background: rgba(251, 248, 240, 0.62);
}

.strategy-sheet__number {
  padding-top: 30px;
  color: var(--cinnabar);
  font-family: var(--mono);
  font-size: 11px;
}

.strategy-sheet__body {
  padding: 26px 30px 27px 0;
  border-right: 1px solid var(--line);
}

.strategy-sheet__meta {
  display: flex;
  gap: 14px;
  color: var(--ink-faint);
  font-family: var(--mono);
  font-size: 9px;
  letter-spacing: 0.08em;
}

.strategy-sheet h2 {
  margin: 16px 0 8px;
  font-family: var(--display);
  font-size: 30px;
  font-weight: 520;
}

.strategy-sheet p {
  max-width: 720px;
  margin: 0;
  color: var(--ink-soft);
  font-size: 13px;
  line-height: 1.8;
}

.strategy-sheet__facts {
  display: flex;
  gap: 8px;
  margin-top: 20px;
}

.strategy-sheet__facts span {
  padding: 5px 9px;
  color: var(--jade);
  background: var(--jade-light);
  font-size: 10px;
}

.strategy-sheet .strategy-sheet__limitation {
  margin-top: 15px;
  color: var(--amber);
  font-size: 11px;
}

.strategy-sheet__action {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: var(--ink);
  font-family: var(--display);
  text-decoration: none;
  transition:
    color 160ms ease,
    background 160ms ease;
}

.strategy-sheet__action span:last-child {
  margin-top: 10px;
  color: var(--cinnabar);
  font-family: var(--body);
}

.strategy-sheet__action:hover {
  color: #fff8ec;
  background: var(--cinnabar);
}

.strategy-sheet__action:hover span:last-child {
  color: inherit;
}

.strategy-sheet__status {
  display: grid;
  place-items: center;
  padding: 18px;
  color: var(--ink-faint);
  font-size: 10px;
  text-align: center;
}

@media (max-width: 650px) {
  .strategy-sheet {
    grid-template-columns: 42px 1fr;
  }

  .strategy-sheet__body {
    padding-right: 0;
    border-right: 0;
  }

  .strategy-sheet__action,
  .strategy-sheet__status {
    min-height: 52px;
    grid-column: 2;
    flex-direction: row;
    gap: 8px;
    justify-content: flex-start;
  }

  .strategy-sheet__action span:last-child {
    margin-top: 0;
  }
}
</style>
