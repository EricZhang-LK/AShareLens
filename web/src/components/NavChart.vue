<script setup lang="ts">
import { computed } from "vue";

import type { NavPoint } from "@/lib/types";

const props = defineProps<{
  points: NavPoint[];
}>();

const width = 900;
const height = 260;
const padding = { top: 24, right: 24, bottom: 34, left: 58 };

const values = computed(() => props.points.map((point) => point.total_value));
const minimum = computed(() => Math.min(...values.value));
const maximum = computed(() => Math.max(...values.value));
const range = computed(() => Math.max(maximum.value - minimum.value, 1));
const path = computed(() =>
  props.points
    .map((point, index) => {
      const x =
        padding.left +
        (index / Math.max(props.points.length - 1, 1)) *
          (width - padding.left - padding.right);
      const y =
        padding.top +
        ((maximum.value - point.total_value) / range.value) *
          (height - padding.top - padding.bottom);
      return `${index === 0 ? "M" : "L"} ${x.toFixed(2)} ${y.toFixed(2)}`;
    })
    .join(" "),
);
const areaPath = computed(
  () =>
    `${path.value} L ${width - padding.right} ${height - padding.bottom} ` +
    `L ${padding.left} ${height - padding.bottom} Z`,
);

const money = new Intl.NumberFormat("zh-CN", {
  maximumFractionDigits: 0,
});
</script>

<template>
  <figure class="nav-chart">
    <figcaption>
      <div>
        <span class="eyebrow">NET ASSET VALUE</span>
        <strong>组合净值轨迹</strong>
      </div>
      <span v-if="points.length">
        {{ points[0]?.trade_date }} — {{ points.at(-1)?.trade_date }}
      </span>
    </figcaption>
    <svg
      v-if="points.length"
      :viewBox="`0 0 ${width} ${height}`"
      role="img"
      :aria-label="`组合净值从 ${money.format(points[0]?.total_value ?? 0)} 变化到 ${money.format(points.at(-1)?.total_value ?? 0)}`"
    >
      <defs>
        <linearGradient id="nav-area" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stop-color="#267765" stop-opacity=".24" />
          <stop offset="1" stop-color="#267765" stop-opacity="0" />
        </linearGradient>
      </defs>
      <line
        v-for="tick in [0, 0.5, 1]"
        :key="tick"
        :x1="padding.left"
        :x2="width - padding.right"
        :y1="padding.top + tick * (height - padding.top - padding.bottom)"
        :y2="padding.top + tick * (height - padding.top - padding.bottom)"
        class="grid-line"
      />
      <text :x="4" :y="padding.top + 4">{{ money.format(maximum) }}</text>
      <text :x="4" :y="height - padding.bottom + 4">{{ money.format(minimum) }}</text>
      <path :d="areaPath" fill="url(#nav-area)" />
      <path :d="path" class="nav-line" />
      <circle
        :cx="width - padding.right"
        :cy="
          padding.top +
          ((maximum - (points.at(-1)?.total_value ?? maximum)) / range) *
            (height - padding.top - padding.bottom)
        "
        r="5"
        class="end-point"
      />
    </svg>
  </figure>
</template>

<style scoped>
.nav-chart {
  margin: 0;
  padding: 24px 25px 18px;
  background: rgba(251, 248, 240, 0.68);
  border: 1px solid var(--line);
}

figcaption {
  display: flex;
  align-items: end;
  justify-content: space-between;
  margin-bottom: 16px;
}

figcaption strong {
  display: block;
  margin-top: 6px;
  font-family: var(--display);
  font-size: 19px;
}

figcaption > span {
  color: var(--ink-faint);
  font-family: var(--mono);
  font-size: 8px;
}

svg {
  display: block;
  width: 100%;
  overflow: visible;
}

.grid-line {
  stroke: rgba(20, 42, 37, 0.12);
  stroke-dasharray: 3 5;
}

text {
  fill: var(--ink-faint);
  font-family: var(--mono);
  font-size: 9px;
}

.nav-line {
  fill: none;
  stroke: var(--jade);
  stroke-width: 2.5;
  vector-effect: non-scaling-stroke;
}

.end-point {
  fill: var(--paper-light);
  stroke: var(--cinnabar);
  stroke-width: 3;
  vector-effect: non-scaling-stroke;
}
</style>
