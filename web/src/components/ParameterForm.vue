<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";

import ParameterField from "./ParameterField.vue";
import {
  normalizedInitialValues,
  schemaDefaults,
  validateParameters,
  type ParameterErrors,
  type ParameterValues,
} from "@/lib/jsonSchema";
import type { JsonSchema } from "@/lib/types";

const props = withDefaults(
  defineProps<{
    schema: JsonSchema;
    modelValue?: ParameterValues;
    serverErrors?: ParameterErrors;
  }>(),
  {
    modelValue: () => ({}),
    serverErrors: () => ({}),
  },
);

const emit = defineEmits<{
  "update:modelValue": [value: ParameterValues];
  "validity-change": [valid: boolean];
}>();

const values = ref<ParameterValues>({});
const touched = ref(new Set<string>());

const properties = computed(() => Object.entries(props.schema.properties ?? {}));
const localErrors = computed(() => validateParameters(props.schema, values.value));
const errors = computed<ParameterErrors>(() => ({
  ...localErrors.value,
  ...props.serverErrors,
}));
const valid = computed(() => Object.keys(errors.value).length === 0);

function initialize(): void {
  values.value = normalizedInitialValues(props.schema, props.modelValue);
  touched.value = new Set();
  emit("update:modelValue", { ...values.value });
  void nextTick(() => emit("validity-change", valid.value));
}

function updateField(name: string, value: unknown): void {
  values.value = { ...values.value, [name]: value };
  touched.value.add(name);
  emit("update:modelValue", { ...values.value });
  void nextTick(() => emit("validity-change", valid.value));
}

function reset(): void {
  values.value = schemaDefaults(props.schema);
  touched.value = new Set();
  emit("update:modelValue", { ...values.value });
  void nextTick(() => emit("validity-change", valid.value));
}

watch(() => props.schema, initialize, { immediate: true, deep: true });
</script>

<template>
  <form class="parameter-form" @submit.prevent>
    <div class="parameter-form__heading">
      <div>
        <span class="eyebrow">PLUGIN PARAMETERS</span>
        <h3>{{ schema.title ?? "策略参数" }}</h3>
      </div>
      <button type="button" class="reset-button" @click="reset">恢复默认值</button>
    </div>
    <p v-if="schema.description" class="parameter-form__description">
      {{ schema.description }}
    </p>

    <div v-if="properties.length" class="parameter-form__fields">
      <ParameterField
        v-for="[name, property] in properties"
        :key="name"
        :name="name"
        :schema="property"
        :model-value="values[name]"
        :required="schema.required?.includes(name)"
        :error="errors[name]"
        @update:model-value="updateField(name, $event)"
      />
    </div>
    <div v-else class="empty-state">这个策略没有可配置参数。</div>

    <div class="parameter-form__status" aria-live="polite">
      <span :class="{ valid }">
        {{ valid ? "本地格式检查通过" : `还有 ${Object.keys(errors).length} 个参数需要处理` }}
      </span>
      <small>最终以 Python 策略模型的服务端校验为准</small>
    </div>
  </form>
</template>

<style scoped>
.parameter-form {
  margin-top: 30px;
  padding: 25px 28px 18px;
  background: rgba(241, 236, 223, 0.6);
  border-top: 2px solid var(--ink);
}

.parameter-form__heading {
  display: flex;
  align-items: start;
  justify-content: space-between;
}

.parameter-form h3 {
  margin: 7px 0 0;
  font-family: var(--display);
  font-size: 21px;
  font-weight: 560;
}

.parameter-form__description {
  margin: 13px 0 4px;
  color: var(--ink-faint);
  font-size: 10px;
}

.reset-button {
  padding: 7px 0;
  color: var(--ink-soft);
  background: transparent;
  border: 0;
  border-bottom: 1px solid var(--line-strong);
  cursor: pointer;
  font-size: 10px;
}

.reset-button:hover {
  color: var(--cinnabar);
  border-color: currentColor;
}

.parameter-form__status {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-top: 16px;
  color: var(--cinnabar);
  font-size: 10px;
}

.parameter-form__status .valid {
  color: var(--jade);
}

.parameter-form__status small {
  color: var(--ink-faint);
  font-size: 8px;
}

@media (max-width: 580px) {
  .parameter-form {
    padding-inline: 18px;
  }

  .parameter-form__status {
    display: grid;
    gap: 5px;
  }
}
</style>
