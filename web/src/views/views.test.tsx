import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { stubSnapshot } from "../api/stub";
import type { Settings, Snapshot } from "../types";
import { CardView } from "./CardView";
import { DiagnosticsView } from "./DiagnosticsView";
import { InsightsView } from "./InsightsView";
import { SettingsView } from "./SettingsView";

const base = stubSnapshot("7d", 1);

function emptySnap(): Snapshot {
  return {
    ...base,
    status: "empty",
    daily: [],
    models: [],
    apps: [],
    totals: { reqs: 0, credits: 0, fresh_in: 0, out: 0, cache_read: 0, cache_write: 0, cost: 0, tokens: 0 },
    kpis: { sessions: 0, active_days: 0, cost: null, tokens: 0, cache_hit: null, credits: null },
    sources: base.sources.map((s) => ({ ...s, status: "empty" as const, reason: "本期无记录" }))
  };
}

const settings: Settings = {
  alpha: 0.96, topmost: true, peek: true, range: "7d", layout: "insights", theme: "dark", hollow: false
};

const noop = () => {};

describe("InsightsView", () => {
  it("渲染 KPI、九个来源卡与模型表", () => {
    render(<InsightsView snap={base} range="7d" refreshing={false} onRange={noop}
      onRefresh={noop} onExport={noop} onNavigate={noop} />);
    expect(screen.getByTestId("insights")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "上下文洞察" })).toBeInTheDocument();
    expect(document.querySelectorAll("article.source")).toHaveLength(base.sources.length);
    const rows = screen.getByTestId("models-table").querySelectorAll("tbody tr");
    expect(rows.length).toBeGreaterThan(0);
  });

  it("tiles 顺序固定：热力/工具、模型整行、耗时/守恒", () => {
    render(<InsightsView snap={base} range="7d" refreshing={false} onRange={noop}
      onRefresh={noop} onExport={noop} onNavigate={noop} />);
    const ids = ["tile-heat", "tile-tools", "tile-models", "tile-timing", "tile-conservation"];
    const nodes = ids.map((id) => screen.getByTestId(id));
    expect(nodes.map((n) => n.getAttribute("data-testid"))).toEqual(ids);
    expect(nodes[2]).toHaveClass("wide");
  });

  it("空数据用「本期无记录」且成本显示 —", () => {
    render(<InsightsView snap={emptySnap()} range="7d" refreshing={false} onRange={noop}
      onRefresh={noop} onExport={noop} onNavigate={noop} />);
    expect(screen.getAllByText("本期无记录").length).toBeGreaterThan(0);
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
  });

  it("工具调用卡显示真实计数", () => {
    render(<InsightsView snap={base} range="7d" refreshing={false} onRange={noop}
      onRefresh={noop} onExport={noop} onNavigate={noop} />);
    expect(screen.getByTestId("tools-card")).toHaveTextContent("Read");
    expect(screen.getByTestId("tools-card")).toHaveTextContent("128");
  });

  it("耗时卡显示代理实测 P50/P95，缺失时给无数据文案", () => {
    const withTiming = { ...base, timing: { n: 10, p50: 1800, p95: 6400, ftt_n: 9, ftt_p50: 420, ftt_p95: 1500 } };
    const { unmount } = render(<InsightsView snap={withTiming} range="1d" refreshing={false}
      onRange={noop} onRefresh={noop} onExport={noop} onNavigate={noop} />);
    expect(screen.getByTestId("timing-card")).toHaveTextContent("1.80s");
    expect(screen.getByTestId("timing-card")).toHaveTextContent("0.42s");
    unmount();
    render(<InsightsView snap={{ ...base, timing: null }} range="1d" refreshing={false}
      onRange={noop} onRefresh={noop} onExport={noop} onNavigate={noop} />);
    expect(screen.getByText(/无耗时数据/)).toBeInTheDocument();
  });

  it("真实 0 值显示 0 而不是 —", () => {
    const zero = { ...emptySnap(), status: "ok" as const,
      kpis: { ...emptySnap().kpis, cost: 0, tokens: 0, credits: 0 } };
    render(<InsightsView snap={zero} range="1d" refreshing={false} onRange={noop}
      onRefresh={noop} onExport={noop} onNavigate={noop} />);
    expect(screen.getByText("$0.00")).toBeInTheDocument();
  });
});

describe("SessionsGrid", () => {
  it("按来源筛选、搜索与分页", async () => {
    render(<InsightsView snap={base} range="7d" refreshing={false} onRange={noop}
      onRefresh={noop} onExport={noop} onNavigate={noop} />);
    const grid = screen.getByTestId("sessions");
    expect(grid).toBeInTheDocument();
    const before = grid.querySelectorAll(".session-card").length;
    expect(before).toBe(12); // 每页 12

    const search = screen.getByLabelText("搜索会话");
    await userEvent.type(search, "claude");
    const filtered = grid.querySelectorAll(".session-card").length;
    expect(filtered).toBeLessThanOrEqual(before);
    expect(screen.getByText(/没有匹配|第 1\//)).toBeInTheDocument();

    await userEvent.clear(search);
    await userEvent.click(within(grid).getByRole("button", { name: "ccswitch" }));
    expect(grid.querySelectorAll(".session-card").length).toBeGreaterThan(0);
    await userEvent.click(within(grid).getByRole("button", { name: "全部" }));
    await userEvent.click(screen.getByRole("button", { name: "下一页" }));
    expect(screen.getByText(/第 2\//)).toBeInTheDocument();
  });
});

describe("DiagnosticsView", () => {
  it("显示守恒表与九路状态表", () => {
    render(<DiagnosticsView snap={base} settings={settings} range="7d" exportResult={null}
      onExport={noop} onNavigate={noop} />);
    expect(screen.getByTestId("conservation-table")).toBeInTheDocument();
    const rows = screen.getByTestId("sources-table").querySelectorAll("tbody tr");
    expect(rows).toHaveLength(base.sources.length);
  });
});

describe("SettingsView", () => {
  it("电源动作必须点两次才确认", async () => {
    const onPower = vi.fn().mockResolvedValue({ ok: true });
    render(<SettingsView settings={settings} onChange={noop} onExport={noop}
      onPower={onPower} onCancelPower={vi.fn()} onNavigate={noop} />);
    const btn = screen.getByRole("button", { name: "关机" });
    await userEvent.click(btn);
    expect(onPower).not.toHaveBeenCalled();
    expect(screen.getByTestId("power-msg")).toHaveTextContent("再次点击");
    await userEvent.click(btn);
    expect(onPower).toHaveBeenCalledWith("shutdown", true);
  });

  it("透明度选择即时回调", async () => {
    const onChange = vi.fn();
    render(<SettingsView settings={settings} onChange={onChange} onExport={noop}
      onPower={vi.fn()} onCancelPower={vi.fn()} onNavigate={noop} />);
    await userEvent.click(screen.getByRole("button", { name: "86%" }));
    expect(onChange).toHaveBeenCalledWith({ alpha: 0.86 });
  });
});

describe("CardView", () => {
  it("小卡显示范围胶囊与指标", () => {
    render(<CardView snap={base} range="7d" refreshing={false} onRange={noop}
      onExpand={noop} onSettings={noop} />);
    expect(screen.getByTestId("card-view")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "7 天" })).toHaveClass("on");
    expect(screen.getByText("cc-hud")).toBeInTheDocument();
  });
});
