import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { stubBootstrap, stubSnapshot } from "./api/stub";
import type { HudApi, Settings } from "./types";

const cardSettings: Settings = {
  alpha: 0.96, topmost: true, peek: true, range: "7d", layout: "card", theme: "dark", hollow: false
};

function makeApi(failLayout: boolean): HudApi {
  let current = { ...cardSettings };
  const api = {
    bootstrap: async () => ({ ...stubBootstrap(), settings: current }),
    snapshot: async (rng: "1d" | "7d" | "30d" | "all", seq: number) => stubSnapshot(rng, seq),
    detail: async () => ({ source: null }),
    get_settings: async () => current,
    set_settings: async (patch: Partial<Settings>) => {
      if (failLayout && patch.layout) throw new Error("native resize failed");
      current = { ...current, ...patch };
      return current;
    },
    export_json: async () => ({ ok: true, path: "", bytes: 0, revision: 1 }),
    power: async () => ({ ok: true }),
    cancel_power: async () => ({ ok: true }),
    window: async () => ({ ok: true })
  } as unknown as HudApi;
  return api;
}

describe("布局切换", () => {
  it("真实点击展开洞察会调用 set_settings({layout:'insights'})", async () => {
    const api = makeApi(false);
    const spy = vi.spyOn(api, "set_settings");
    window.pywebview = { api: api as never };
    render(<App />);
    await screen.findByTestId("card-view");
    await waitFor(() => expect(screen.queryByTestId("loading")).not.toBeInTheDocument());
    await userEvent.click(await screen.findByTestId("expand-insights"));
    await waitFor(() => expect(spy).toHaveBeenCalledWith({ layout: "insights" }));
  });

  it("原生 resize 失败：保留小卡、提示可见、无 unhandled rejection", async () => {
    const api = makeApi(true);
    window.pywebview = { api: api as never };
    let unhandled = 0;
    const onReject = () => { unhandled += 1; };
    window.addEventListener("unhandledrejection", onReject);
    render(<App />);
    await screen.findByTestId("card-view");
    await waitFor(() => expect(screen.queryByTestId("loading")).not.toBeInTheDocument());
    await userEvent.click(await screen.findByTestId("expand-insights"));
    await screen.findByText(/设置失败/);
    expect(screen.getByTestId("card-view")).toBeInTheDocument();
    expect(screen.queryByTestId("insights")).not.toBeInTheDocument();
    await new Promise((r) => setTimeout(r, 60));
    expect(unhandled).toBe(0);
    window.removeEventListener("unhandledrejection", onReject);
  });
});
