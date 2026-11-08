import type { Bootstrap, ExportResult, HudApi, RangeKey, Settings, Snapshot } from "../types";
import { stubBootstrap, stubSnapshot } from "./stub";

declare global {
  interface Window {
    pywebview?: { api: Partial<HudApi> };
  }
}

const delay = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** 场景桩：?scenario=empty|zero|unsupported|error 用于 Playwright 断言四种状态。 */
function applyScenario(snap: Snapshot): Snapshot {
  const scenario = new URLSearchParams(window.location.search).get("scenario");
  if (!scenario) return snap;
  const ZERO_T = { reqs: 0, credits: 0, fresh_in: 0, out: 0, cache_read: 0, cache_write: 0, cost: 0, tokens: 0 };
  const zeroSrc = (s: Snapshot["sources"][number]): Snapshot["sources"][number] => ({
    ...s, totals: { ...ZERO_T }, sessions: 0, last_seen: null
  });
  if (scenario === "empty") {
    return {
      ...snap, status: "empty", daily: [], models: [], apps: [],
      totals: { ...ZERO_T },
      kpis: { sessions: 0, active_days: 0, cost: null, tokens: 0, cache_hit: null, credits: null },
      sources: snap.sources.map((s) => zeroSrc({ ...s, status: "empty" as const, reason: "本期无记录" }))
    };
  }
  if (scenario === "zero") {
    return {
      ...snap, status: "ok", daily: [], models: [], apps: [],
      totals: { ...ZERO_T },
      kpis: { sessions: 0, active_days: 0, cost: 0, tokens: 0, cache_hit: null, credits: 0 },
      sources: snap.sources.map((s) => zeroSrc({ ...s, status: "ok" as const, reason: null }))
    };
  }
  if (scenario === "unsupported") {
    return {
      ...snap, status: "unsupported", daily: [], models: [], apps: [], totals: { ...ZERO_T },
      kpis: { sessions: 0, active_days: 0, cost: null, tokens: 0, cache_hit: null, credits: null },
      sources: snap.sources.map((s) => zeroSrc({
        ...s, status: "unsupported" as const, reason: "来源不支持该维度"
      }))
    };
  }
  return {
    ...snap, status: "error", daily: [], models: [], apps: [], totals: { ...ZERO_T },
    kpis: { sessions: 0, active_days: 0, cost: null, tokens: 0, cache_hit: null, credits: null },
    sources: snap.sources.map((s) => zeroSrc({
      ...s, status: "error" as const, reason: "读取失败：权限被拒绝"
    }))
  };
}

export function createStubApi(): HudApi {
  let settings: Settings = stubBootstrap().settings;
  let revision = 7;
  const api: HudApi = {
    async bootstrap(): Promise<Bootstrap> {
      await delay(5);
      return stubBootstrap();
    },
    async snapshot(range: RangeKey, seq: number): Promise<Snapshot> {
      await delay(30);
      const snap = applyScenario(stubSnapshot(range, seq));
      return { ...snap, revision: revision++, seq };
    },
    async detail(key: string, range: RangeKey) {
      const snap = applyScenario(stubSnapshot(range, 0));
      return { source: snap.sources.find((s) => s.key === key) ?? null, range };
    },
    async get_settings() {
      return settings;
    },
    async set_settings(patch: Partial<Settings>) {
      settings = { ...settings, ...patch };
      return settings;
    },
    async export_json(): Promise<ExportResult> {
      return { path: "cc-hud-usage-7d.json", bytes: 4096, revision };
    },
    async power(action: string, confirmed: boolean) {
      return confirmed ? { ok: true, action } : { ok: false, reason: "需要二次确认" };
    },
    async cancel_power() {
      return { ok: true };
    },
    async window() {
      return { ok: true };
    }
  };
  return api;
}

export function createNativeApi(): HudApi | null {
  const py = window.pywebview?.api;
  if (!py) return null;
  const must = <T>(fn: (() => Promise<T>) | undefined, name: string): (() => Promise<T>) => {
    if (!fn) throw new Error(`pywebview api 缺少 ${name}`);
    return fn.bind(py);
  };
  return {
    bootstrap: must(py.bootstrap as () => Promise<Bootstrap>, "bootstrap"),
    snapshot: (range, seq) => (py.snapshot as HudApi["snapshot"])(range, seq),
    detail: (key, range) => (py.detail as HudApi["detail"])(key, range),
    get_settings: must(py.get_settings as () => Promise<Settings>, "get_settings"),
    set_settings: (patch) => (py.set_settings as HudApi["set_settings"])(patch),
    export_json: (range) => (py.export_json as HudApi["export_json"])(range),
    power: (action, confirmed) => (py.power as HudApi["power"])(action, confirmed),
    cancel_power: must(py.cancel_power as () => Promise<{ ok: boolean }>, "cancel_power"),
    window: (action, value) => (py.window as HudApi["window"])(action, value)
  };
}


