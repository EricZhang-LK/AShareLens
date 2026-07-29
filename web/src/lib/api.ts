import type {
  ApiErrorDetail,
  DemoBacktestRequest,
  DemoBacktestResponse,
  HealthResponse,
  ParameterValidationResponse,
  ProviderCatalogResponse,
  StrategyCatalogResponse,
} from "./types";

export class ApiError extends Error {
  readonly status: number;
  readonly detail: ApiErrorDetail | null;

  constructor(status: number, detail: ApiErrorDetail | null) {
    super(detail?.message ?? `请求失败（HTTP ${status}）`);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

async function getJson<T extends object>(path: string): Promise<T> {
  return requestJson<T>(path, {
    headers: { Accept: "application/json" },
  });
}

async function postJson<T extends object>(
  path: string,
  payload: object,
): Promise<T> {
  return requestJson<T>(path, {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
}

async function requestJson<T extends object>(
  path: string,
  init: RequestInit,
): Promise<T> {
  const response = await fetch(path, init);
  const body = (await response.json()) as
    | T
    | { error?: ApiErrorDetail };
  if (!response.ok) {
    const detail = "error" in body ? body.error ?? null : null;
    throw new ApiError(response.status, detail);
  }
  return body as T;
}

export const api = {
  health: () => getJson<HealthResponse>("/api/v1/health"),
  strategies: () =>
    getJson<StrategyCatalogResponse>("/api/v1/strategies"),
  providers: () => getJson<ProviderCatalogResponse>("/api/v1/providers"),
  validateStrategy: (
    strategyId: string,
    parameters: Record<string, unknown>,
  ) =>
    postJson<ParameterValidationResponse>(
      `/api/v1/strategies/${encodeURIComponent(strategyId)}/validate`,
      { parameters },
    ),
  runDemoBacktest: (request: DemoBacktestRequest) =>
    postJson<DemoBacktestResponse>("/api/v1/backtests/demo", request),
};

export type ResearchApi = typeof api;
