import { describe, expect, it } from "vitest";
import { fmtCost, fmtPct, fmtTokens, sourceStatusText } from "../lib/format";

describe("format", () => {
  it("null 与 0 必须区分", () => {
    expect(fmtCost(null)).toBe("—");
    expect(fmtCost(0)).toBe("$0.00");
    expect(fmtPct(null)).toBe("—");
    expect(fmtPct(0)).toBe("0.00%");
  });

  it("token 用万/亿", () => {
    expect(fmtTokens(15000)).toBe("1.5万");
    expect(fmtTokens(230000000)).toBe("2.30亿");
    expect(fmtTokens(0)).toBe("0");
  });

  it("suppressed 优先于 status", () => {
    expect(sourceStatusText("ok", true)).toBe("双计已拒绝");
    expect(sourceStatusText("error", false)).toBe("读取失败");
  });
});
