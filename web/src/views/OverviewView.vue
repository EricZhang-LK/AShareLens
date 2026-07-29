<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { RouterLink } from "vue-router";

import { api } from "@/lib/api";
import type {
  ProviderCatalogItem,
  StrategyCatalogItem,
} from "@/lib/types";

const strategies = ref<StrategyCatalogItem[]>([]);
const providers = ref<ProviderCatalogItem[]>([]);
const loading = ref(true);
const error = ref("");

const freeProviders = computed(
  () => providers.value.filter((item) => !item.requires_registration).length,
);
const defaultProvider = computed(
  () => providers.value.find((item) => item.role === "default")?.name ?? "—",
);
const today = new Intl.DateTimeFormat("zh-CN", {
  month: "long",
  day: "numeric",
  weekday: "long",
}).format(new Date());

onMounted(async () => {
  try {
    const [strategyResponse, providerResponse] = await Promise.all([
      api.strategies(),
      api.providers(),
    ]);
    strategies.value = strategyResponse.items;
    providers.value = providerResponse.items;
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "无法读取研究配置。";
  } finally {
    loading.value = false;
  }
});
</script>

<template>
  <article>
    <header class="page-heading">
      <div>
        <span class="section-kicker">{{ today }}</span>
        <h1>先看证据，<br />再做判断。</h1>
      </div>
      <p class="page-heading__note">
        AShareLens 把每次选股拆成可解释信号、明确数据来源和可复现运行指纹。
        这里没有“神秘分数”，只有可以回到原始条件的研究记录。
      </p>
    </header>

    <div v-if="loading" class="loading-state" role="status">
      正在整理本地研究资料……
    </div>
    <div v-else-if="error" class="error-state" role="alert">
      {{ error }}
    </div>
    <template v-else>
      <section class="ledger-grid" aria-label="系统概览">
        <div class="ledger-stat ledger-stat--primary">
          <span class="ledger-stat__label">可用策略</span>
          <strong>{{ strategies.length }}</strong>
          <small>参数均由策略自身定义</small>
        </div>
        <div class="ledger-stat">
          <span class="ledger-stat__label">数据接入</span>
          <strong>{{ providers.length }}</strong>
          <small>{{ freeProviders }} 个免注册来源</small>
        </div>
        <div class="ledger-stat">
          <span class="ledger-stat__label">默认来源</span>
          <strong class="ledger-stat__word">{{ defaultProvider }}</strong>
          <small>可按完整分区自动切换</small>
        </div>
        <div class="ledger-stat ledger-stat--seal">
          <span class="seal">本地</span>
          <p>策略、凭据与研究记录默认不离开设备。</p>
        </div>
      </section>

      <section class="workbench-section">
        <div class="section-title">
          <div>
            <span class="section-kicker">Research flow</span>
            <h2>一条可追溯的研究链</h2>
          </div>
          <RouterLink class="action-link action-link--quiet" to="/strategies">
            选择策略 <span aria-hidden="true">→</span>
          </RouterLink>
        </div>

        <ol class="research-flow">
          <li>
            <span>01</span>
            <strong>数据门禁</strong>
            <p>记录来源、批次与质量结果；不合格的数据不会静默进入策略。</p>
          </li>
          <li>
            <span>02</span>
            <strong>收盘信号</strong>
            <p>策略只看信号日当时可见的信息，逐项给出入选或排除原因。</p>
          </li>
          <li>
            <span>03</span>
            <strong>次日成交</strong>
            <p>订单在下一交易日开盘模拟，并单列滑点、佣金与税费。</p>
          </li>
          <li>
            <span>04</span>
            <strong>运行指纹</strong>
            <p>策略、参数、数据、资金与成交配置共同生成唯一证据。</p>
          </li>
        </ol>
      </section>

      <section class="first-run">
        <div class="first-run__mark" aria-hidden="true">试</div>
        <div>
          <span class="section-kicker">Zero setup</span>
          <h2>先用合成数据完成第一次回测</h2>
          <p>
            无需账号、无需网络。选一个经典策略，调整参数，观察收盘信号如何在
            下一交易日转化为模拟成交。
          </p>
        </div>
        <RouterLink class="action-link" to="/backtest">
          开始离线回测 <span aria-hidden="true">↗</span>
        </RouterLink>
      </section>
    </template>
  </article>
</template>

<style scoped>
.ledger-grid {
  display: grid;
  grid-template-columns: 1.2fr 1fr 1.35fr 1fr;
  border-top: 1px solid var(--line-strong);
  border-bottom: 1px solid var(--line-strong);
}

.ledger-stat {
  min-height: 184px;
  padding: 24px 24px 20px;
  border-right: 1px solid var(--line);
}

.ledger-stat:last-child {
  border-right: 0;
}

.ledger-stat__label {
  display: block;
  color: var(--ink-faint);
  font-family: var(--mono);
  font-size: 9px;
  letter-spacing: 0.14em;
}

.ledger-stat strong {
  display: block;
  margin: 22px 0 13px;
  font-family: var(--display);
  font-size: 55px;
  font-weight: 500;
  line-height: 1;
}

.ledger-stat small {
  color: var(--ink-soft);
  font-size: 11px;
}

.ledger-stat--primary strong {
  color: var(--cinnabar);
}

.ledger-stat .ledger-stat__word {
  margin-top: 31px;
  font-size: 30px;
}

.ledger-stat--seal {
  display: grid;
  place-content: center;
  text-align: center;
}

.ledger-stat--seal p {
  max-width: 150px;
  margin: 14px auto 0;
  color: var(--ink-soft);
  font-size: 11px;
  line-height: 1.7;
}

.seal {
  display: grid;
  width: 53px;
  height: 53px;
  margin: 0 auto;
  place-items: center;
  color: var(--cinnabar);
  border: 2px solid var(--cinnabar);
  font-family: var(--display);
  font-size: 20px;
  transform: rotate(-4deg);
}

.workbench-section {
  margin-top: 84px;
}

.section-title {
  display: flex;
  align-items: end;
  justify-content: space-between;
  margin-bottom: 28px;
}

.section-title h2,
.first-run h2 {
  margin: 8px 0 0;
  font-family: var(--display);
  font-size: clamp(28px, 3.2vw, 42px);
  font-weight: 520;
}

.research-flow {
  display: grid;
  margin: 0;
  padding: 0;
  grid-template-columns: repeat(4, 1fr);
  list-style: none;
  border-top: 1px solid var(--line);
}

.research-flow li {
  position: relative;
  min-height: 220px;
  padding: 24px 25px;
  border-right: 1px solid var(--line);
}

.research-flow li::before {
  position: absolute;
  top: -4px;
  left: 25px;
  width: 7px;
  height: 7px;
  content: "";
  background: var(--paper);
  border: 1px solid var(--cinnabar);
  border-radius: 50%;
}

.research-flow li:last-child {
  border-right: 0;
}

.research-flow span {
  color: var(--cinnabar);
  font-family: var(--mono);
  font-size: 10px;
}

.research-flow strong {
  display: block;
  margin-top: 44px;
  font-family: var(--display);
  font-size: 20px;
}

.research-flow p {
  margin: 12px 0 0;
  color: var(--ink-soft);
  font-size: 12px;
  line-height: 1.8;
}

.first-run {
  position: relative;
  display: grid;
  grid-template-columns: 80px 1fr auto;
  gap: 28px;
  align-items: center;
  margin-top: 74px;
  padding: 32px 34px;
  overflow: hidden;
  color: #f8f2e4;
  background: var(--ink);
}

.first-run::after {
  position: absolute;
  right: 13%;
  bottom: -90px;
  width: 220px;
  height: 220px;
  content: "";
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 50%;
}

.first-run__mark {
  display: grid;
  width: 64px;
  height: 64px;
  place-items: center;
  border: 1px solid rgba(255, 255, 255, 0.24);
  font-family: var(--display);
  font-size: 29px;
}

.first-run p {
  max-width: 650px;
  margin: 11px 0 0;
  color: rgba(248, 242, 228, 0.64);
  font-size: 12px;
  line-height: 1.75;
}

.first-run .section-kicker {
  color: #d8705f;
}

.first-run .action-link {
  position: relative;
  z-index: 1;
}

@media (max-width: 1040px) {
  .ledger-grid {
    grid-template-columns: repeat(2, 1fr);
  }

  .ledger-stat:nth-child(2) {
    border-right: 0;
  }

  .ledger-stat:nth-child(-n + 2) {
    border-bottom: 1px solid var(--line);
  }

  .research-flow {
    grid-template-columns: repeat(2, 1fr);
  }

  .research-flow li:nth-child(-n + 2) {
    border-bottom: 1px solid var(--line);
  }

  .first-run {
    grid-template-columns: 64px 1fr;
  }

  .first-run .action-link {
    grid-column: 2;
    justify-self: start;
  }
}

@media (max-width: 600px) {
  .ledger-grid,
  .research-flow {
    grid-template-columns: 1fr;
  }

  .ledger-stat,
  .ledger-stat:nth-child(2),
  .research-flow li {
    border-right: 0;
    border-bottom: 1px solid var(--line);
  }

  .section-title {
    display: grid;
    gap: 20px;
  }

  .section-title .action-link {
    justify-self: start;
  }

  .first-run {
    grid-template-columns: 1fr;
    padding: 28px 24px;
  }

  .first-run .action-link {
    grid-column: 1;
  }
}
</style>
