import { describe, expect, it, vi } from "vitest";

import { ApiError, type ResearchApi } from "@/lib/api";
import { useBacktest } from "@/composables/useBacktest";
import type {
  DemoBacktestRequest,
  DemoBacktestResponse,
} from "@/lib/types";

const request: DemoBacktestRequest = {
  strategy_id: "moving_average",
  parameters: { fast_period: 10, slow_period: 30 },
  sessions: 80,
  initial_cash: 100000,
  top_n: 1,
  max_weight: 1,
};

const result = {
  strategy_id: "moving_average",
  strategy_version: "1.0.0",
  parameters: { fast_period: 10, slow_period: 30, confirm_days: 3 },
  is_demo: true,
  data_source: "deterministic_synthetic",
  warning: "demo",
  fingerprint: "a".repeat(64),
  summary: {
    sessions: 80,
    initial_cash: 100000,
    final_nav: 101000,
    total_return_pct: 1,
    max_drawdown_pct: 0.5,
    selected_signals: 2,
    orders: 2,
    fills: 1,
  },
  costs: { commission: 5, transfer_fee: 0.1, stamp_duty: 0, total: 5.1 },
  nav: [],
  latest_candidates: [],
} satisfies DemoBacktestResponse;

function client(overrides: Partial<ResearchApi> = {}): ResearchApi {
  return {
    health: vi.fn(),
    strategies: vi.fn(),
    providers: vi.fn(),
    validateStrategy: vi.fn().mockResolvedValue({
      strategy_id: "moving_average",
      parameters: result.parameters,
    }),
    runDemoBacktest: vi.fn().mockResolvedValue(result),
    ...overrides,
  };
}

describe("useBacktest", () => {
  it("validates through Python before running with normalized defaults", async () => {
    const researchApi = client();
    const backtest = useBacktest(researchApi);

    await backtest.run(request);

    expect(researchApi.validateStrategy).toHaveBeenCalledWith(
      "moving_average",
      request.parameters,
    );
    expect(researchApi.runDemoBacktest).toHaveBeenCalledWith({
      ...request,
      parameters: result.parameters,
    });
    expect(backtest.status.value).toBe("succeeded");
    expect(backtest.result.value?.fingerprint).toBe("a".repeat(64));
  });

  it("maps safe server field errors back to the generated form", async () => {
    const error = new ApiError(422, {
      code: "invalid_strategy_parameters",
      message: "策略参数校验失败。",
      request_id: "request-1",
      details: {
        fields: [
          {
            field: "fast_period",
            message: "Input should be greater than or equal to 2",
          },
        ],
      },
    });
    const backtest = useBacktest(
      client({ validateStrategy: vi.fn().mockRejectedValue(error) }),
    );

    await backtest.run(request);

    expect(backtest.status.value).toBe("failed");
    expect(backtest.serverErrors.value).toEqual({
      fast_period: "Input should be greater than or equal to 2",
    });
    expect(backtest.message.value).toBe("策略参数校验失败。");

    backtest.clearErrors();
    expect(backtest.status.value).toBe("idle");
    expect(backtest.serverErrors.value).toEqual({});
    expect(backtest.message.value).toBe("");
  });
});
