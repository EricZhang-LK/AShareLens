export interface JsonSchemaProperty {
  type?: string;
  title?: string;
  description?: string;
  default?: unknown;
  enum?: unknown[];
  minimum?: number;
  maximum?: number;
  exclusiveMinimum?: number;
  exclusiveMaximum?: number;
  [key: string]: unknown;
}

export interface JsonSchema {
  title?: string;
  description?: string;
  type?: string;
  properties?: Record<string, JsonSchemaProperty>;
  required?: string[];
  additionalProperties?: boolean;
  [key: string]: unknown;
}

export interface StrategyCatalogItem {
  strategy_id: string;
  name: string;
  version: string;
  description: string;
  min_history_sessions: number;
  parameter_schema: JsonSchema;
  demo_supported: boolean;
  demo_limitation: string | null;
}

export interface ProviderCatalogItem {
  provider_id: string;
  name: string;
  version: string;
  description: string;
  datasets: string[];
  requires_registration: boolean;
  role: "default" | "supplemental" | "optional";
}

export interface HealthResponse {
  service: "asharelens";
  status: "ok";
  version: string;
}

export interface StrategyCatalogResponse {
  items: StrategyCatalogItem[];
}

export interface ProviderCatalogResponse {
  items: ProviderCatalogItem[];
}

export interface ApiErrorDetail {
  code: string;
  message: string;
  request_id: string;
  details?: Record<string, unknown>;
}

export interface ParameterValidationResponse {
  strategy_id: string;
  parameters: Record<string, unknown>;
}

export interface DemoBacktestRequest {
  strategy_id: string;
  parameters: Record<string, unknown>;
  sessions: number;
  initial_cash: number;
  top_n: number;
  max_weight: number;
}

export interface SelectionReason {
  code: string;
  message: string;
}

export interface SelectionCandidate {
  symbol: string;
  signal_date: string;
  selected: boolean;
  score: number;
  rank: number | null;
  reasons: SelectionReason[];
  metrics: Record<string, number>;
  data_warnings: string[];
}

export interface NavPoint {
  trade_date: string;
  cash: number;
  market_value: number;
  total_value: number;
}

export interface BacktestSummary {
  sessions: number;
  initial_cash: number;
  final_nav: number;
  total_return_pct: number;
  max_drawdown_pct: number;
  selected_signals: number;
  orders: number;
  fills: number;
}

export interface BacktestCosts {
  commission: number;
  transfer_fee: number;
  stamp_duty: number;
  total: number;
}

export interface DemoBacktestResponse {
  strategy_id: string;
  strategy_version: string;
  parameters: Record<string, unknown>;
  is_demo: true;
  data_source: "deterministic_synthetic";
  warning: string;
  fingerprint: string;
  summary: BacktestSummary;
  costs: BacktestCosts;
  nav: NavPoint[];
  latest_candidates: SelectionCandidate[];
}
