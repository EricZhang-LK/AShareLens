import type { JsonSchema, JsonSchemaProperty } from "./types";

export type ParameterValues = Record<string, unknown>;
export type ParameterErrors = Record<string, string>;

const supportedTypes = new Set(["integer", "number", "boolean", "string"]);

export function schemaDefaults(schema: JsonSchema): ParameterValues {
  return Object.fromEntries(
    Object.entries(schema.properties ?? {})
      .filter(([, property]) => property.default !== undefined)
      .map(([name, property]) => [name, property.default]),
  );
}

export function normalizedInitialValues(
  schema: JsonSchema,
  supplied: ParameterValues,
): ParameterValues {
  return { ...schemaDefaults(schema), ...supplied };
}

export function isSupportedProperty(property: JsonSchemaProperty): boolean {
  return Boolean(
    property.enum?.length ||
      (property.type && supportedTypes.has(property.type)),
  );
}

export function validateParameters(
  schema: JsonSchema,
  values: ParameterValues,
): ParameterErrors {
  const errors: ParameterErrors = {};
  const required = new Set(schema.required ?? []);
  for (const [name, property] of Object.entries(schema.properties ?? {})) {
    const value = values[name];
    if (value === undefined || value === null || value === "") {
      if (required.has(name)) {
        errors[name] = "这是必填参数。";
      }
      continue;
    }
    if (!isSupportedProperty(property)) {
      errors[name] = "当前界面暂不支持这个参数类型。";
      continue;
    }
    if (property.enum && !property.enum.some((item) => item === value)) {
      errors[name] = "请选择列表中的有效值。";
      continue;
    }
    if (property.type === "integer" && !Number.isInteger(value)) {
      errors[name] = "请输入整数。";
      continue;
    }
    if (
      (property.type === "integer" || property.type === "number") &&
      typeof value !== "number"
    ) {
      errors[name] = "请输入数字。";
      continue;
    }
    if (typeof value === "number") {
      if (property.minimum !== undefined && value < property.minimum) {
        errors[name] = `不能小于 ${property.minimum}。`;
      } else if (
        property.exclusiveMinimum !== undefined &&
        value <= property.exclusiveMinimum
      ) {
        errors[name] = `必须大于 ${property.exclusiveMinimum}。`;
      } else if (property.maximum !== undefined && value > property.maximum) {
        errors[name] = `不能大于 ${property.maximum}。`;
      } else if (
        property.exclusiveMaximum !== undefined &&
        value >= property.exclusiveMaximum
      ) {
        errors[name] = `必须小于 ${property.exclusiveMaximum}。`;
      }
    }
  }
  return errors;
}

export function constraintHint(property: JsonSchemaProperty): string {
  const hints: string[] = [];
  if (property.minimum !== undefined) hints.push(`≥ ${property.minimum}`);
  if (property.exclusiveMinimum !== undefined) {
    hints.push(`> ${property.exclusiveMinimum}`);
  }
  if (property.maximum !== undefined) hints.push(`≤ ${property.maximum}`);
  if (property.exclusiveMaximum !== undefined) {
    hints.push(`< ${property.exclusiveMaximum}`);
  }
  return hints.join(" 且 ");
}
