<script setup lang="ts">
import { onMounted, ref } from "vue";
import { RouterLink, RouterView, useRoute } from "vue-router";

import { api } from "@/lib/api";

const route = useRoute();
const apiVersion = ref("连接中");
const apiHealthy = ref(false);

const navigation = [
  { to: "/", index: "01", label: "总览", detail: "今日研究台" },
  { to: "/strategies", index: "02", label: "策略", detail: "规则与参数" },
  { to: "/backtest", index: "03", label: "回测", detail: "验证与证据" },
  { to: "/providers", index: "04", label: "数据源", detail: "来源与边界" },
] as const;

onMounted(async () => {
  try {
    const health = await api.health();
    apiVersion.value = `v${health.version}`;
    apiHealthy.value = true;
  } catch {
    apiVersion.value = "未连接";
  }
});
</script>

<template>
  <div class="app-frame">
    <aside class="sidebar">
      <RouterLink class="brand" to="/" aria-label="AShareLens 首页">
        <span class="brand-lens" aria-hidden="true">
          <span class="brand-lens__line"></span>
        </span>
        <span>
          <strong>AShareLens</strong>
          <small>A 股透镜</small>
        </span>
      </RouterLink>

      <nav class="primary-nav" aria-label="主导航">
        <RouterLink
          v-for="item in navigation"
          :key="item.to"
          :to="item.to"
          class="nav-entry"
          :class="{ 'nav-entry--active': route.path === item.to }"
        >
          <span class="nav-entry__index">{{ item.index }}</span>
          <span class="nav-entry__copy">
            <strong>{{ item.label }}</strong>
            <small>{{ item.detail }}</small>
          </span>
          <span class="nav-entry__rule" aria-hidden="true"></span>
        </RouterLink>
      </nav>

      <div class="sidebar-note">
        <span class="eyebrow">LOCAL FIRST</span>
        <p>数据、策略与运行记录默认只留在你的设备。</p>
      </div>
    </aside>

    <section class="workspace">
      <header class="topbar">
        <div class="topbar__crumb">
          <span>研究工作台</span>
          <span aria-hidden="true">/</span>
          <strong>{{ navigation.find((item) => item.to === route.path)?.label ?? "总览" }}</strong>
        </div>
        <div
          class="health-chip"
          :class="{ 'health-chip--online': apiHealthy }"
          role="status"
        >
          <span class="health-chip__dot"></span>
          <span>{{ apiHealthy ? "本地服务正常" : "等待本地服务" }}</span>
          <code>{{ apiVersion }}</code>
        </div>
      </header>

      <main id="main-content" class="page-stage">
        <RouterView v-slot="{ Component }">
          <Transition name="page" mode="out-in">
            <component :is="Component" />
          </Transition>
        </RouterView>
      </main>

      <footer class="legal-line">
        <span>AShareLens · MIT 开源</span>
        <span>研究工具，不构成投资建议</span>
      </footer>
    </section>
  </div>
</template>
