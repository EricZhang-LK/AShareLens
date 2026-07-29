import { computed, ref } from "vue";

import {
  ApiError,
  api as defaultApi,
  type ResearchApi,
} from "@/lib/api";
import type {
  DemoBacktestRequest,
  DemoBacktestResponse,
} from "@/lib/types";

export type BacktestStatus =
  | "idle"
  | "validating"
  | "running"
  | "succeeded"
  | "failed";

export function useBacktest(client: ResearchApi = defaultApi) {
  const status = ref<BacktestStatus>("idle");
  const result = ref<DemoBacktestResponse | null>(null);
  const message = ref("");
  const serverErrors = ref<Record<string, string>>({});
  const busy = computed(
    () => status.value === "validating" || status.value === "running",
  );

  async function run(request: DemoBacktestRequest): Promise<void> {
    status.value = "validating";
    message.value = "";
    serverErrors.value = {};
    try {
      const validation = await client.validateStrategy(
        request.strategy_id,
        request.parameters,
      );
      status.value = "running";
      result.value = await client.runDemoBacktest({
        ...request,
        parameters: validation.parameters,
      });
      status.value = "succeeded";
    } catch (reason) {
      status.value = "failed";
      message.value =
        reason instanceof Error ? reason.message : "回测请求未能完成。";
      if (reason instanceof ApiError) {
        serverErrors.value = fieldErrors(reason.detail?.details);
      }
    }
  }

  function reset(): void {
    status.value = "idle";
    result.value = null;
    message.value = "";
    serverErrors.value = {};
  }

  function clearErrors(): void {
    message.value = "";
    serverErrors.value = {};
    if (status.value === "failed") status.value = "idle";
  }

  return {
    status,
    result,
    message,
    serverErrors,
    busy,
    run,
    reset,
    clearErrors,
  };
}

function fieldErrors(
  details: Record<string, unknown> | undefined,
): Record<string, string> {
  const fields = details?.fields;
  if (!Array.isArray(fields)) return {};
  return Object.fromEntries(
    fields.flatMap((item) => {
      if (
        typeof item === "object" &&
        item !== null &&
        "field" in item &&
        "message" in item &&
        typeof item.field === "string" &&
        typeof item.message === "string"
      ) {
        return [[item.field, item.message]];
      }
      return [];
    }),
  );
}
