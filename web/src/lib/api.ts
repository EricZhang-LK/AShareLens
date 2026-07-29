import type {
  ApiErrorDetail,
  HealthResponse,
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
  const response = await fetch(path, {
    headers: { Accept: "application/json" },
  });
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
};
