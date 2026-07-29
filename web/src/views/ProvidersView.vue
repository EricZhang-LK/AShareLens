<script setup lang="ts">
import { onMounted, ref } from "vue";

import { api } from "@/lib/api";
import type { ProviderCatalogItem } from "@/lib/types";

const providers = ref<ProviderCatalogItem[]>([]);
const loading = ref(true);
const error = ref("");

const roleLabel = {
  default: "默认来源",
  supplemental: "免注册补充",
  optional: "可选增强",
} as const;

const datasetLabel: Record<string, string> = {
  instruments: "股票列表",
  calendar: "交易日历",
  daily_bars: "日线行情",
};

onMounted(async () => {
  try {
    providers.value = (await api.providers()).items;
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "数据源目录读取失败。";
  } finally {
    loading.value = false;
  }
});
</script>

<template>
  <article>
    <header class="page-heading">
      <div>
        <span class="section-kicker">Data provenance</span>
        <h1>每一行行情，<br />都知道从哪里来。</h1>
      </div>
      <p class="page-heading__note">
        数据源按完整分区切换，不把多个来源的零散股票拼接成“完整数据”。
        原始请求、单位换算、批次哈希和质量结果都会留下证据。
      </p>
    </header>

    <div v-if="loading" class="loading-state" role="status">正在读取数据能力……</div>
    <div v-else-if="error" class="error-state" role="alert">{{ error }}</div>
    <section v-else class="provider-stack" aria-label="数据源">
      <article
        v-for="(provider, index) in providers"
        :key="provider.provider_id"
        class="provider-row"
      >
        <div class="provider-row__rail">
          <span>{{ String(index + 1).padStart(2, "0") }}</span>
          <i></i>
        </div>
        <div class="provider-row__identity">
          <span class="provider-role">{{ roleLabel[provider.role] }}</span>
          <h2>{{ provider.name }}</h2>
          <code>{{ provider.provider_id }} · v{{ provider.version }}</code>
        </div>
        <div class="provider-row__detail">
          <p>{{ provider.description }}</p>
          <div class="provider-row__datasets">
            <span v-for="dataset in provider.datasets" :key="dataset">
              {{ datasetLabel[dataset] ?? dataset }}
            </span>
          </div>
        </div>
        <div class="provider-row__access">
          <strong>{{ provider.requires_registration ? "需配置凭据" : "免注册" }}</strong>
          <small>{{ provider.requires_registration ? "由用户主动启用" : "开箱可用" }}</small>
        </div>
      </article>
    </section>

    <aside class="provenance-note">
      <span class="provenance-note__mark">源</span>
      <div>
        <strong>数据质量门禁</strong>
        <p>
          缺列、重复、价格关系异常、交易日缺失或覆盖率不足时，分区会被拒绝发布。
          策略不会在有问题的数据上悄悄给出“正常结果”。
        </p>
      </div>
    </aside>
  </article>
</template>

<style scoped>
.provider-stack {
  border-top: 1px solid var(--line-strong);
}

.provider-row {
  display: grid;
  grid-template-columns: 45px minmax(170px, 0.7fr) minmax(300px, 1.4fr) 130px;
  min-height: 190px;
  border-bottom: 1px solid var(--line-strong);
}

.provider-row__rail {
  display: grid;
  grid-template-rows: auto 1fr;
  justify-items: center;
  padding-top: 27px;
  color: var(--cinnabar);
  font-family: var(--mono);
  font-size: 9px;
}

.provider-row__rail i {
  width: 1px;
  margin-top: 13px;
  background: var(--line);
}

.provider-row__identity,
.provider-row__detail,
.provider-row__access {
  padding: 27px 24px;
  border-left: 1px solid var(--line);
}

.provider-role {
  color: var(--jade);
  font-size: 10px;
  letter-spacing: 0.08em;
}

.provider-row h2 {
  margin: 15px 0 8px;
  font-family: var(--display);
  font-size: 28px;
  font-weight: 520;
}

.provider-row code {
  color: var(--ink-faint);
  font-family: var(--mono);
  font-size: 9px;
}

.provider-row__detail p {
  max-width: 620px;
  margin: 0;
  color: var(--ink-soft);
  font-size: 12px;
  line-height: 1.8;
}

.provider-row__datasets {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
  margin-top: 22px;
}

.provider-row__datasets span {
  padding: 5px 8px;
  color: var(--ink-soft);
  border: 1px solid var(--line);
  font-size: 9px;
}

.provider-row__access {
  display: flex;
  flex-direction: column;
  justify-content: center;
}

.provider-row__access strong {
  font-family: var(--display);
  font-size: 16px;
  font-weight: 600;
}

.provider-row__access small {
  margin-top: 7px;
  color: var(--ink-faint);
  font-size: 9px;
}

.provenance-note {
  display: grid;
  grid-template-columns: 64px 1fr;
  gap: 24px;
  align-items: center;
  margin-top: 54px;
  padding: 29px 32px;
  color: #f6f0e2;
  background: var(--ink);
}

.provenance-note__mark {
  display: grid;
  width: 55px;
  height: 55px;
  place-items: center;
  color: #e47a68;
  border: 1px solid #e47a68;
  font-family: var(--display);
  font-size: 22px;
}

.provenance-note strong {
  font-family: var(--display);
  font-size: 20px;
}

.provenance-note p {
  max-width: 780px;
  margin: 8px 0 0;
  color: rgba(246, 240, 226, 0.62);
  font-size: 11px;
  line-height: 1.8;
}

@media (max-width: 900px) {
  .provider-row {
    grid-template-columns: 35px 0.65fr 1fr;
  }

  .provider-row__access {
    grid-column: 2 / -1;
    flex-direction: row;
    gap: 10px;
    align-items: baseline;
    padding-block: 14px;
  }
}

@media (max-width: 620px) {
  .provider-row {
    grid-template-columns: 32px 1fr;
  }

  .provider-row__detail,
  .provider-row__access {
    grid-column: 2;
  }

  .provider-row__detail {
    border-top: 1px solid var(--line);
  }

  .provider-row__access {
    flex-direction: column;
  }

  .provenance-note {
    grid-template-columns: 1fr;
  }
}
</style>
