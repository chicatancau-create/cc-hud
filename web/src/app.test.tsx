import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { stubBootstrap, stubSnapshot } from "./api/stub";
import type { HudApi, RangeKey, Settings } from "./types";

const cardSettings: Settings = {
  alpha: 0.96, topmost: true, peek: true, range: "7d", layout: "card", theme: "dark", hollow: false
};

interface PendingCall {
  patch: Partial<Settings>;
  resolve: (s: Settings) => void;
  reject: (e: unknown) => void;
}

interface BridgeOpts {
  layout?: Settings["layout"];
  bootRange?: RangeKey;
  /** 任何 layout 写入都失败（原生 resize 失败） */
  failLayout?: boolean;
  /** 这些 range 的写入失败 */
  failRanges?: RangeKey[];
  /** 手动模式：set_settings 返回挂起的 promise，由测试决定成败与回包内容（竞态用例） */
  manual?: boolean;
}

function makeApi(opts: BridgeOpts = {}) {
  let current: Settings = {
    ...cardSettings,
    layout: opts.layout ?? "card",
    range: opts.bootRange ?? "7d"
  };
  const pending: PendingCall[] = [];
  const calls: Partial<Settings>[] = [];
  const resolveSettings = (patch: Partial<Settings>) => {
    current = { ...current, ...patch };
    return current;
  };
  const api = {
    bootstrap: async () => ({ ...stubBootstrap(), settings: current }),
    snapshot: async (rng: RangeKey, seq: number) => stubSnapshot(rng, seq),
    detail: async () => ({ source: null }),
    get_settings: async () => current,
    set_settings: (patch: Partial<Settings>) => {
      calls.push(patch);
      if (opts.manual) {
        return new Promise<Settings>((resolve, reject) => { pending.push({ patch, resolve, reject }); });
      }
      if (opts.failLayout && patch.layout) return Promise.reject(new Error("native resize failed"));
      if (patch.range && opts.failRanges?.includes(patch.range)) {
        return Promise.reject(new Error(`range ${patch.range} 写入失败`));
      }
      return Promise.resolve(resolveSettings(patch));
    },
    export_json: async () => ({ ok: true, path: "", bytes: 0, revision: 1 }),
    power: async () => ({ ok: true }),
    cancel_power: async () => ({ ok: true }),
    window: async () => ({ ok: true })
  } as unknown as HudApi;
  return { api, pending, calls, current: () => current };
}

/**
 * 未处理拒绝探测器。jsdom 里 window 的 `unhandledrejection` 不会触发（实测），
 * 真正能观测到的是宿主 Node 的 `unhandledRejection`；vitest 自己也会把它算成
 * run 级 error 并以非零码退出。所以两者都断言，保证这个用例能真红。
 */
function watchUnhandled() {
  const seen: unknown[] = [];
  const onReject = (reason: unknown) => { seen.push(reason); };
  process.on("unhandledRejection", onReject);
  return {
    count: () => seen.length,
    stop: () => { process.off("unhandledRejection", onReject); }
  };
}

const settle = (ms = 60) => new Promise((r) => setTimeout(r, ms));

async function bootCard(api: HudApi) {
  window.pywebview = { api: api as never };
  render(<App />);
  await screen.findByTestId("card-view");
  await waitFor(() => expect(screen.queryByTestId("loading")).not.toBeInTheDocument());
}

describe("布局切换", () => {
  it("真实点击展开洞察会调用 set_settings({layout:'insights'})", async () => {
    const { api } = makeApi({ layout: "card" });
    const spy = vi.spyOn(api, "set_settings");
    window.pywebview = { api: api as never };
    render(<App />);
    await screen.findByTestId("card-view");
    await waitFor(() => expect(screen.queryByTestId("loading")).not.toBeInTheDocument());
    await userEvent.click(await screen.findByTestId("expand-insights"));
    await waitFor(() => expect(spy).toHaveBeenCalledWith({ layout: "insights" }));
  });

  it("原生 resize 失败：保留小卡、提示可见、无 unhandled rejection", async () => {
    const { api } = makeApi({ layout: "card", failLayout: true });
    window.pywebview = { api: api as never };
    const watch = watchUnhandled();
    try {
      render(<App />);
      await screen.findByTestId("card-view");
      await waitFor(() => expect(screen.queryByTestId("loading")).not.toBeInTheDocument());
      await userEvent.click(await screen.findByTestId("expand-insights"));
      await screen.findByText(/设置失败/);
      expect(screen.getByTestId("card-view")).toBeInTheDocument();
      expect(screen.queryByTestId("insights")).not.toBeInTheDocument();
      await settle();
      expect(watch.count()).toBe(0);
    } finally {
      watch.stop();
    }
  });
});

describe("设置失败的调用点", () => {
  it("Esc 与小卡切范围失败：提示可见、布局不动、无 unhandled rejection", async () => {
    const { api } = makeApi({ layout: "card", bootRange: "1d", failLayout: true, failRanges: ["7d"] });
    const spy = vi.spyOn(api, "set_settings");
    const watch = watchUnhandled();
    try {
      await bootCard(api);

      // App.tsx:190 —— Esc 收成小卡（resize 失败）
      fireEvent.keyDown(window, { key: "Escape" });
      await screen.findByText(/设置失败/);
      await waitFor(() => expect(spy).toHaveBeenCalledWith({ layout: "card" }));
      expect(screen.getByTestId("card-view")).toBeInTheDocument();

      // App.tsx:243 —— 小卡范围胶囊（写入失败 → 回滚到已确认范围）
      await userEvent.click(screen.getByRole("button", { name: "7 天" }));
      await waitFor(() => expect(spy).toHaveBeenCalledWith({ range: "7d" }));
      await waitFor(() => expect(screen.getByRole("button", { name: "今日" })).toHaveClass("on"));
      expect(screen.getByRole("button", { name: "7 天" })).not.toHaveClass("on");

      await settle();
      expect(watch.count()).toBe(0);
    } finally {
      watch.stop();
    }
  });

  it("大面板切范围失败：提示可见、范围回滚、无 unhandled rejection", async () => {
    const { api } = makeApi({ layout: "insights", bootRange: "1d", failRanges: ["7d"] });
    const spy = vi.spyOn(api, "set_settings");
    const watch = watchUnhandled();
    try {
      window.pywebview = { api: api as never };
      render(<App />);
      await screen.findByTestId("insights");

      // App.tsx:249 —— 大面板范围胶囊
      await userEvent.click(screen.getByTestId("range-7d"));
      await waitFor(() => expect(spy).toHaveBeenCalledWith({ range: "7d" }));
      await screen.findByText(/设置失败/);
      await waitFor(() => expect(screen.getByTestId("range-1d")).toHaveClass("on"));
      expect(screen.getByTestId("range-7d")).not.toHaveClass("on");

      await settle();
      expect(watch.count()).toBe(0);
    } finally {
      watch.stop();
    }
  });
});

describe("范围切换竞态", () => {
  it("先发的请求失败且已过时：range 不回滚到旧值，最终以最新一次的服务端回包为准", async () => {
    const { api, pending } = makeApi({ layout: "card", bootRange: "1d", manual: true });
    await bootCard(api);
    expect(screen.getByRole("button", { name: "今日" })).toHaveClass("on");

    // 两次快速切换：7 天 先发、30 天 后发（写请求串行，第二次排在第一次之后）
    await userEvent.click(screen.getByRole("button", { name: "7 天" }));
    await userEvent.click(screen.getByRole("button", { name: "30 天" }));
    await waitFor(() => expect(pending).toHaveLength(1));
    expect(pending[0].patch).toEqual({ range: "7d" });

    // 先发的那次失败（此时它已经不是最新的请求）
    await act(async () => {
      pending[0].reject(new Error("7d 写入失败"));
      await settle(0);
    });
    await waitFor(() => expect(pending).toHaveLength(2));
    expect(pending[1].patch).toEqual({ range: "30d" });

    // 最新一次成功，服务端权威范围 30d
    await act(async () => {
      pending[1].resolve({ ...cardSettings, layout: "card", range: "30d" });
      await settle(0);
    });

    await waitFor(() => expect(screen.getByRole("button", { name: "30 天" })).toHaveClass("on"));
    expect(screen.getByRole("button", { name: "7 天" })).not.toHaveClass("on");
    expect(screen.getByRole("button", { name: "今日" })).not.toHaveClass("on");
    // 过时的失败不该打扰用户
    expect(screen.queryByText(/设置失败/)).not.toBeInTheDocument();
  });
});
