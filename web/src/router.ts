import { createRouter, createWebHistory } from "vue-router";

import BacktestView from "@/views/BacktestView.vue";
import OverviewView from "@/views/OverviewView.vue";
import ProvidersView from "@/views/ProvidersView.vue";
import StrategiesView from "@/views/StrategiesView.vue";

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", name: "overview", component: OverviewView },
    { path: "/strategies", name: "strategies", component: StrategiesView },
    { path: "/backtest", name: "backtest", component: BacktestView },
    { path: "/providers", name: "providers", component: ProvidersView },
    { path: "/:pathMatch(.*)*", redirect: "/" },
  ],
  scrollBehavior: () => ({ top: 0 }),
});

export default router;
