<script setup lang="ts">
import type { SelectionCandidate } from "@/lib/types";

defineProps<{
  candidates: SelectionCandidate[];
}>();

const score = new Intl.NumberFormat("zh-CN", {
  style: "percent",
  maximumFractionDigits: 1,
});
</script>

<template>
  <section class="signal-ledger">
    <header>
      <div>
        <span class="eyebrow">SIGNAL EVIDENCE</span>
        <h3>最新收盘信号</h3>
      </div>
      <span>{{ candidates.length }} 个候选</span>
    </header>
    <div class="signal-ledger__table">
      <details v-for="candidate in candidates" :key="candidate.symbol">
        <summary>
          <span class="rank">{{ candidate.rank ?? "—" }}</span>
          <strong>{{ candidate.symbol }}</strong>
          <span
            class="decision"
            :class="{ 'decision--selected': candidate.selected }"
          >
            {{ candidate.selected ? "入选" : "排除" }}
          </span>
          <span class="score">{{ score.format(candidate.score) }}</span>
          <span class="disclosure" aria-hidden="true">＋</span>
        </summary>
        <div class="signal-evidence">
          <div>
            <h4>判断理由</h4>
            <ul>
              <li v-for="reason in candidate.reasons" :key="reason.code">
                <code>{{ reason.code }}</code>
                <span>{{ reason.message }}</span>
              </li>
            </ul>
          </div>
          <div>
            <h4>指标快照</h4>
            <dl v-if="Object.keys(candidate.metrics).length">
              <template v-for="(value, key) in candidate.metrics" :key="key">
                <dt>{{ key }}</dt>
                <dd>{{ Number(value).toFixed(4) }}</dd>
              </template>
            </dl>
            <p v-else>该候选没有可显示的数值指标。</p>
          </div>
          <p v-if="candidate.data_warnings.length" class="data-warning">
            数据提醒：{{ candidate.data_warnings.join("、") }}
          </p>
        </div>
      </details>
    </div>
  </section>
</template>

<style scoped>
.signal-ledger {
  margin-top: 25px;
  border-top: 2px solid var(--ink);
}

header {
  display: flex;
  align-items: end;
  justify-content: space-between;
  padding: 22px 4px 16px;
}

header h3 {
  margin: 6px 0 0;
  font-family: var(--display);
  font-size: 22px;
  font-weight: 560;
}

header > span {
  color: var(--ink-faint);
  font-family: var(--mono);
  font-size: 9px;
}

details {
  border-top: 1px solid var(--line);
}

details:last-child {
  border-bottom: 1px solid var(--line);
}

summary {
  display: grid;
  grid-template-columns: 45px minmax(110px, 1fr) 70px 80px 24px;
  gap: 12px;
  align-items: center;
  min-height: 60px;
  padding: 0 7px;
  cursor: pointer;
  list-style: none;
}

summary::-webkit-details-marker {
  display: none;
}

summary:hover {
  background: rgba(251, 248, 240, 0.6);
}

.rank,
.score {
  color: var(--ink-faint);
  font-family: var(--mono);
  font-size: 9px;
}

.decision {
  color: var(--ink-faint);
  font-size: 10px;
}

.decision--selected {
  color: var(--cinnabar);
  font-weight: 700;
}

.disclosure {
  color: var(--cinnabar);
  transition: transform 160ms ease;
}

details[open] .disclosure {
  transform: rotate(45deg);
}

.signal-evidence {
  display: grid;
  grid-template-columns: 1.25fr 1fr;
  gap: 35px;
  padding: 22px 28px 27px 64px;
  background: rgba(231, 222, 201, 0.35);
  border-top: 1px solid var(--line);
}

.signal-evidence h4 {
  margin: 0 0 13px;
  color: var(--ink-faint);
  font-family: var(--mono);
  font-size: 9px;
  letter-spacing: 0.1em;
}

.signal-evidence ul {
  display: grid;
  gap: 10px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.signal-evidence li {
  display: grid;
  gap: 4px;
}

.signal-evidence code {
  color: var(--jade);
  font-family: var(--mono);
  font-size: 8px;
}

.signal-evidence li span,
.signal-evidence p {
  color: var(--ink-soft);
  font-size: 11px;
  line-height: 1.7;
}

dl {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 7px 15px;
  margin: 0;
  font-family: var(--mono);
  font-size: 9px;
}

dt {
  color: var(--ink-soft);
}

dd {
  margin: 0;
  color: var(--ink);
}

.signal-evidence .data-warning {
  grid-column: 1 / -1;
  margin: 0;
  color: var(--amber);
}

@media (max-width: 620px) {
  summary {
    grid-template-columns: 30px 1fr 45px 21px;
  }

  .score {
    display: none;
  }

  .signal-evidence {
    grid-template-columns: 1fr;
    padding-left: 26px;
  }
}
</style>
