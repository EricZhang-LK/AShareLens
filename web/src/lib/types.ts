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
