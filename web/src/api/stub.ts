import type {
  AppRow, Bootstrap, DayRow, ModelRow, RangeKey, Snapshot, SourcePayload, Status
} from "../types";

const RANGE_DAYS: Record<RangeKey, number> = { "1d": 1, "7d": 7, "30d": 30, all: 90 };
const BASE = new Date("2026-11-07T12:00:00");

function dayKey(offset: number): string {
  const d = new Date(BASE);
  d.setDate(d.getDate() - offset);
  return d.toISOString().slice(0, 10);
}

function totalsOf(days: DayRow[]) {
  const t = { reqs: 0, credits: 0, fresh_in: 0, out: 0, cache_read: 0, cache_write: 0, cost: 0, tokens: 0 };
  for (const d of days) {
    t.reqs += d.reqs; t.fresh_in += d.fresh_in; t.out += d.out;
    t.cache_read += d.cache_read; t.cache_write += d.cache_write; t.cost += d.cost;
  }
  t.tokens = t.fresh_in + t.out + t.cache_read + t.cache_write;
  return t;
}

const DEFS: { key: string; name: string; kind: string; status: Status; reason: string | null; note: string; cost: boolean; credits: boolean; tokens: boolean }[] = [
  { key: "ccswitch", name: "CC Switch", kind: "proxy", status: "ok", reason: null, note: "代理日志 · 基准路", cost: true, credits: false, tokens: true },
  { key: "cchaha", name: "cc-haha", kind: "session", status: "ok", reason: null, note: "索引成本按本地日份额分摊", cost: true, credits: false, tokens: true },
  { key: "qoder", name: "Qoder", kind: "session", status: "ok", reason: null, note: "只有请求数与 credits", cost: false, credits: true, tokens: false },
  { key: "qoder_cn", name: "Qoder CN", kind: "session", status: "empty", reason: "本期无记录", note: "只有请求数与 credits", cost: false, credits: true, tokens: false },
  { key: "zcode", name: "ZCode", kind: "session", status: "ok", reason: null, note: "input 含缓存读(已减) · 本机不记钱", cost: false, credits: false, tokens: true },
  { key: "herdsman", name: "牧羊人", kind: "local", status: "ok", reason: null, note: "本地推理服务 · 无缓存分项", cost: false, credits: false, tokens: true },
  { key: "codex", name: "Codex 未回填", kind: "session", status: "ok", reason: null, note: "只补 CC Switch 零行的会话", cost: false, credits: false, tokens: true },
  { key: "workbuddy", name: "WorkBuddy 国内", kind: "session", status: "ok", reason: null, note: "prompt 含缓存读写（已拆出）", cost: false, credits: true, tokens: true },
  { key: "workbuddy_ai", name: "WorkBuddy 国外", kind: "session", status: "unsupported", reason: "积分两本账矛盾，不并", note: "本机不记钱", cost: false, credits: false, tokens: true },
  { key: "dsh", name: "DSH", kind: "session", status: "ok", reason: null, note: "会话累计 · 小时归属近似", cost: false, credits: false, tokens: true },
  { key: "dsh_v4", name: "DSH V4", kind: "session", status: "error", reason: "一个会话文件解压失败", note: "zstd JSONL", cost: false, credits: false, tokens: true }
];

function source(def: (typeof DEFS)[number], days: DayRow[]): SourcePayload {
  const share = def.status === "ok" ? 0.12 : 0;
  const own: DayRow[] = days.map((d) => ({
    ...d,
    reqs: Math.round(d.reqs * share),
    tokens: Math.round(d.tokens * share),
    fresh_in: Math.round(d.fresh_in * share),
    out: Math.round(d.out * share),
    cache_read: Math.round(d.cache_read * share),
    cache_write: Math.round(d.cache_write * share),
    cost: d.cost * share
  }));
  const t = totalsOf(own);
  return {
    key: def.key, name: def.name, kind: def.kind, status: def.status, reason: def.reason,
    note: def.note, supports_cost: def.cost, supports_credits: def.credits,
    supports_tokens: def.tokens,
    totals: { ...t, reqs: def.tokens ? t.reqs : Math.round(t.reqs / 3), credits: def.credits ? 12.5 : 0 },
    sessions: def.status === "ok" ? 3 : 0,
    last_seen: def.status === "ok" ? BASE.getTime() / 1000 : null,
    warnings: def.status === "error" ? ["session.v4.jsonl.zstd: 解压失败"] : [],
    suppressed: null
  };
}

export function stubSnapshot(range: RangeKey, seq = 0): Snapshot {
  const n = RANGE_DAYS[range];
  const days: DayRow[] = Array.from({ length: n }, (_, i) => {
    const wave = 0.55 + 0.45 * Math.sin((i / Math.max(1, n)) * Math.PI * 2);
    const tokens = Math.round((range === "1d" ? 1.85e6 : 1.1e6) * wave);
    return {
      date: dayKey(n - 1 - i),
      reqs: Math.round(180 * wave),
      tokens,
      cost: Number((3.2 * wave).toFixed(2)),
      fresh_in: Math.round(tokens * 0.18),
      out: Math.round(tokens * 0.07),
      cache_read: Math.round(tokens * 0.72),
      cache_write: Math.round(tokens * 0.03),
      credits: Number((1.1 * wave).toFixed(2))
    };
  });
  const totals = totalsOf(days);
  const denom = totals.cache_read + totals.fresh_in + totals.cache_write;
  const sources = DEFS.map((d) => source(d, days));
  const models: ModelRow[] = [
    { name: "claude-sonnet-4.5", reqs: 312, tokens: Math.round(totals.tokens * 0.34), cost: 12.4, sources: ["ccswitch", "cchaha"] },
    { name: "deepseek-v4", reqs: 268, tokens: Math.round(totals.tokens * 0.27), cost: 0, sources: ["dsh"] },
    { name: "gpt-5-codex", reqs: 154, tokens: Math.round(totals.tokens * 0.18), cost: 4.2, sources: ["ccswitch", "codex"] },
    { name: "glm-5", reqs: 96, tokens: Math.round(totals.tokens * 0.12), cost: 0, sources: ["zcode"] }
  ];
  const apps: AppRow[] = sources.filter((s) => s.status === "ok").map((s) => ({
    key: s.key, name: s.name, reqs: s.totals.reqs, tokens: s.totals.tokens, cost: s.totals.cost
  })).sort((a, b) => b.tokens - a.tokens);

  const sessionRows = Array.from({ length: 30 }, (_, i) => {
    const def = DEFS[i % DEFS.length];
    return {
      id: `${def.key}-session-${String(i + 1).padStart(3, "0")}`,
      source: def.key,
      reqs: 12 + ((i * 7) % 90),
      tokens: 120000 + ((i * 37000) % 900000),
      cost: Number(((i % 5) * 1.25).toFixed(2)),
      credits: def.credits ? Number((i % 4)) : 0,
      model: ["claude-sonnet-4.5", "deepseek-v4", "gpt-5-codex", "glm-5"][i % 4],
      last_seen: BASE.getTime() / 1000 - i * 3600
    };
  });

  return {
    schema: 1, revision: 7, seq, range, generated_at: BASE.getTime() / 1000, status: "ok",
    totals, kpis: {
      sessions: 23, active_days: days.length, cost: totals.cost, tokens: totals.tokens,
      cache_hit: denom ? (totals.cache_read / denom) * 100 : null, credits: 12.5
    },
    daily: days, hourly: Array.from({ length: 24 }, (_, h) => ({
      hour: h, reqs: Math.round(4 + 40 * Math.exp(-Math.pow(h - 14, 2) / 40)), tokens: 0, cost: 0
    })),
    models, apps, sources, session_rows: sessionRows, session_total: sessionRows.length,
    timing: { n: 240, p50: 1800, p95: 6400, ftt_n: 218, ftt_p50: 420, ftt_p95: 1500 },
    tools: [
      { name: "Read", n: 128, sessions: 21 },
      { name: "Bash", n: 96, sessions: 18 },
      { name: "Edit", n: 54, sessions: 12 },
      { name: "Grep", n: 31, sessions: 9 },
      { name: "Write", n: 22, sessions: 7 }
    ],
    conservation: [
      { name: "totals_eq_days", ok: true, detail: `tokens=${totals.tokens}` },
      { name: "tokens_eq_parts", ok: true, detail: "fresh+out+read+write" },
      ...sources.filter((s) => s.status === "ok").map((s) => ({
        name: `${s.key}.models_le_total`, ok: true, detail: s.key
      }))
    ],
    start_date: days[0]?.date ?? null,
    cache: { hits: 2, misses: 1, entries: 1, capacity: 8 }
  };
}

export function stubBootstrap(): Bootstrap {
  return {
    version: "0.1.0",
    ranges: [{ key: "1d", label: "今日" }, { key: "7d", label: "7 天" }, { key: "30d", label: "30 天" }, { key: "all", label: "全部" }],
    settings: { alpha: 0.96, topmost: true, peek: true, range: "7d", layout: "insights", theme: "dark", hollow: false },
    sources_meta: DEFS.map((d) => ({ key: d.key, name: d.name, kind: d.kind })),
    dpi: 1.25, platform: "windows", start_date: dayKey(0)
  };
}
