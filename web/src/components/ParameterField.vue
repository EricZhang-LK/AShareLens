<script setup lang="ts">
import { computed } from "vue";

import { constraintHint, isSupportedProperty } from "@/lib/jsonSchema";
import type { JsonSchemaProperty } from "@/lib/types";

const props = defineProps<{
  name: string;
  schema: JsonSchemaProperty;
  modelValue: unknown;
  required?: boolean;
  error?: string;
}>();

const emit = defineEmits<{
  "update:modelValue": [value: unknown];
}>();

const inputId = computed(() => `parameter-${props.name}`);
const supported = computed(() => isSupportedProperty(props.schema));
const hint = computed(() => constraintHint(props.schema));

function updateText(event: Event): void {
  const target = event.target as HTMLInputElement;
  emit("update:modelValue", target.value);
}

function updateNumber(event: Event): void {
  const target = event.target as HTMLInputElement;
  emit(
    "update:modelValue",
    target.value === "" ? undefined : Number(target.value),
  );
}

function updateBoolean(event: Event): void {
  emit("update:modelValue", (event.target as HTMLInputElement).checked);
}

function updateEnum(event: Event): void {
  const raw = (event.target as HTMLSelectElement).value;
  const match = props.schema.enum?.find((item) => String(item) === raw);
  emit("update:modelValue", match);
}
</script>

<template>
  <div
    class="parameter-field"
    :class="{
      'parameter-field--error': error,
      'parameter-field--unsupported': !supported,
    }"
  >
    <div class="parameter-field__label">
      <label :for="inputId">
        {{ schema.title ?? name }}
        <span v-if="required" aria-label="必填">*</span>
      </label>
      <code>{{ name }}</code>
    </div>

    <select
      v-if="schema.enum?.length"
      :id="inputId"
      :value="String(modelValue ?? '')"
      :aria-invalid="Boolean(error)"
      :aria-describedby="`${inputId}-help`"
      @change="updateEnum"
    >
      <option v-if="modelValue === undefined" value="">请选择</option>
      <option v-for="option in schema.enum" :key="String(option)" :value="String(option)">
        {{ String(option) }}
      </option>
    </select>

    <label v-else-if="schema.type === 'boolean'" class="parameter-switch">
      <input
        :id="inputId"
        type="checkbox"
        :checked="Boolean(modelValue)"
        :aria-describedby="`${inputId}-help`"
        @change="updateBoolean"
      />
      <span aria-hidden="true"></span>
      <em>{{ modelValue ? "启用" : "停用" }}</em>
    </label>

    <input
      v-else-if="schema.type === 'integer' || schema.type === 'number'"
      :id="inputId"
      type="number"
      :value="modelValue ?? ''"
      :step="schema.type === 'integer' ? 1 : 'any'"
      :min="schema.minimum"
      :max="schema.maximum"
      :required="required"
      :aria-invalid="Boolean(error)"
      :aria-describedby="`${inputId}-help`"
      @input="updateNumber"
    />

    <input
      v-else-if="schema.type === 'string'"
      :id="inputId"
      type="text"
      :value="modelValue ?? ''"
      :required="required"
      :aria-invalid="Boolean(error)"
      :aria-describedby="`${inputId}-help`"
      @input="updateText"
    />

    <div v-else :id="inputId" class="unsupported-control" role="note">
      未支持的 Schema 类型：{{ schema.type ?? "未声明" }}
    </div>

    <div :id="`${inputId}-help`" class="parameter-field__help">
      <span v-if="error" class="parameter-field__error" role="alert">{{ error }}</span>
      <span v-else>{{ schema.description || hint || "由策略参数模型校验" }}</span>
      <span v-if="schema.default !== undefined" class="parameter-field__default">
        默认 {{ String(schema.default) }}
      </span>
    </div>
  </div>
</template>

<style scoped>
.parameter-field {
  display: grid;
  grid-template-columns: minmax(170px, 0.7fr) minmax(180px, 1fr);
  column-gap: 28px;
  align-items: center;
  min-height: 102px;
  padding: 18px 0;
  border-bottom: 1px solid var(--line);
}

.parameter-field__label label {
  display: block;
  font-family: var(--display);
  font-size: 16px;
  font-weight: 600;
}

.parameter-field__label label span {
  color: var(--cinnabar);
}

.parameter-field__label code {
  display: block;
  margin-top: 6px;
  color: var(--ink-faint);
  font-family: var(--mono);
  font-size: 8px;
}

input[type="number"],
input[type="text"],
select,
.unsupported-control {
  width: 100%;
  min-height: 43px;
  padding: 0 13px;
  color: var(--ink);
  background: rgba(255, 253, 247, 0.72);
  border: 1px solid var(--line-strong);
  border-radius: 0;
}

input:focus,
select:focus {
  background: var(--paper-light);
  border-color: var(--cinnabar);
  outline: 0;
  box-shadow: 0 0 0 3px rgba(182, 61, 46, 0.1);
}

.parameter-field--error input,
.parameter-field--error select {
  border-color: var(--cinnabar);
}

.parameter-field__help {
  display: flex;
  grid-column: 2;
  justify-content: space-between;
  margin-top: 7px;
  color: var(--ink-faint);
  font-size: 9px;
}

.parameter-field__error {
  color: var(--cinnabar-dark);
}

.parameter-field__default {
  margin-left: auto;
  padding-left: 10px;
  font-family: var(--mono);
}

.parameter-switch {
  display: flex;
  gap: 10px;
  align-items: center;
  cursor: pointer;
}

.parameter-switch input {
  position: absolute;
  opacity: 0;
}

.parameter-switch span {
  position: relative;
  width: 42px;
  height: 23px;
  background: var(--paper-deep);
  border: 1px solid var(--line-strong);
  transition: background 150ms ease;
}

.parameter-switch span::after {
  position: absolute;
  top: 3px;
  left: 3px;
  width: 15px;
  height: 15px;
  content: "";
  background: var(--ink-faint);
  transition:
    transform 150ms ease,
    background 150ms ease;
}

.parameter-switch input:checked + span {
  background: var(--jade-light);
  border-color: var(--jade);
}

.parameter-switch input:checked + span::after {
  background: var(--jade);
  transform: translateX(18px);
}

.parameter-switch input:focus-visible + span {
  outline: 3px solid rgba(182, 61, 46, 0.38);
  outline-offset: 3px;
}

.parameter-switch em {
  color: var(--ink-soft);
  font-size: 11px;
  font-style: normal;
}

.unsupported-control {
  display: flex;
  align-items: center;
  color: var(--amber);
  border-style: dashed;
  font-size: 10px;
}

@media (max-width: 580px) {
  .parameter-field {
    grid-template-columns: 1fr;
    gap: 12px;
  }

  .parameter-field__help {
    grid-column: 1;
  }
}
</style>
