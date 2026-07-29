import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import ParameterForm from "@/components/ParameterForm.vue";
import type { JsonSchema } from "@/lib/types";

const schema: JsonSchema = {
  type: "object",
  title: "TestParams",
  required: ["label"],
  properties: {
    fast_period: {
      type: "integer",
      title: "短期均线",
      default: 20,
      minimum: 2,
      maximum: 250,
    },
    ratio: {
      type: "number",
      title: "比例",
      default: 0.2,
      exclusiveMinimum: 0,
      maximum: 1,
    },
    enabled: {
      type: "boolean",
      title: "启用过滤",
      default: true,
    },
    mode: {
      type: "string",
      title: "模式",
      default: "steady",
      enum: ["steady", "fast"],
    },
    label: {
      type: "string",
      title: "标签",
    },
    unsupported: {
      type: "array",
      title: "未来字段",
      default: [],
    },
  },
};

describe("ParameterForm", () => {
  it("renders defaults and accessible controls from JSON Schema", () => {
    const wrapper = mount(ParameterForm, { props: { schema } });

    expect(wrapper.get("label[for='parameter-fast_period']").text()).toContain(
      "短期均线",
    );
    expect(
      (wrapper.get("#parameter-fast_period").element as HTMLInputElement).value,
    ).toBe("20");
    expect(
      (wrapper.get("#parameter-enabled").element as HTMLInputElement).checked,
    ).toBe(true);
    expect(wrapper.get("#parameter-mode").element.tagName).toBe("SELECT");
    expect(wrapper.text()).toContain("未支持的 Schema 类型：array");
  });

  it("coerces numeric input and emits the complete parameter object", async () => {
    const wrapper = mount(ParameterForm, { props: { schema } });

    await wrapper.get("#parameter-fast_period").setValue("12");

    const updates = wrapper.emitted("update:modelValue");
    const latest = updates?.at(-1)?.[0] as Record<string, unknown>;
    expect(latest.fast_period).toBe(12);
    expect(latest.ratio).toBe(0.2);
    expect(latest.enabled).toBe(true);
  });

  it("shows local constraints and server errors without unsafe markup", async () => {
    const wrapper = mount(ParameterForm, {
      props: {
        schema,
        serverErrors: {
          label: "<b>服务端拒绝</b>",
        },
      },
    });

    await wrapper.get("#parameter-fast_period").setValue("1");

    expect(wrapper.text()).toContain("不能小于 2。");
    expect(wrapper.text()).toContain("<b>服务端拒绝</b>");
    expect(wrapper.find("b").exists()).toBe(false);
    expect(wrapper.get("#parameter-fast_period").attributes("aria-invalid")).toBe(
      "true",
    );
  });

  it("restores plugin defaults", async () => {
    const wrapper = mount(ParameterForm, {
      props: { schema, modelValue: { fast_period: 42, label: "自定义" } },
    });
    expect(
      (wrapper.get("#parameter-fast_period").element as HTMLInputElement).value,
    ).toBe("42");

    await wrapper.get("button").trigger("click");

    expect(
      (wrapper.get("#parameter-fast_period").element as HTMLInputElement).value,
    ).toBe("20");
    const updates = wrapper.emitted("update:modelValue");
    const latest = updates?.at(-1)?.[0] as Record<string, unknown>;
    expect(latest.label).toBeUndefined();
  });
});
