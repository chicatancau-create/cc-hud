export type RangeKey = "1d" | "7d" | "30d" | "all";
export type Status = "ok" | "empty" | "unsupported" | "error" | "loading" | "suppressed";

export interface Totals {
  reqs: number;
  credits: number;
  fresh_in: number;
  out: number;
  cache_read: number;
  cache_write: number;
  cost: number;
  tokens: number;
}

export interface DayRow {
  date: string;
  reqs: number;
  tokens: number;
  cost: number;
  fresh_in: number;
  out: number;
  cache_read: number;
  cache_write: number;
  credits?: number;
}

export interface HourRow {
  hour: number;
  reqs: number;
  tokens: number;
  cost: number;
}

export interface ModelRow {
  name: string;
  reqs: number;
  tokens: number;
  cost: number;
  sources: string[];
}

export interface AppRow {
  key: string;
  name: string;
  reqs: number;
  tokens: number;
  cost: number;
}

export interface Timing {
  n: number;
  p50: number | null;
  p95: number | null;
  ftt_n: number;
  ftt_p50: number | null;
  ftt_p95: number | null;
}

export interface ToolRow {
  name: string;
  n: number;
  sessions: number;
}

export interface SessionRow {
  id: string;
  source: string;
  reqs: number;
  tokens: number;
  cost: number;
  credits: number;
  model: string | null;
  last_seen: number | null;
}

export interface Kpis {
  sessions: number;
  active_days: number;
  cost: number | null;
  tokens: number;
  cache_hit: number | null;
  credits: number | null;
}

export interface SourceTotal extends Totals {
  tokens: number;
}

export interface SourcePayload {
  key: string;
  name: string;
  kind: string;
  status: Status;
  reason: string | null;
  note: string;
  supports_cost: boolean;
  supports_credits: boolean;
  supports_tokens: boolean;
  totals: SourceTotal;
  sessions: number;
  last_seen: number | null;
  warnings: string[];
  suppressed: { by: string; clash: number } | null;
}

export interface ConservationCheck {
  name: string;
  ok: boolean;
  detail: string;
}

export interface Snapshot {
  schema: number;
  revision: number;
  seq: number;
  range: RangeKey;
  generated_at: number;
  status: Status;
  totals: Totals;
  kpis: Kpis;
  daily: DayRow[];
  hourly: HourRow[];
  models: ModelRow[];
  apps: AppRow[];
  timing: Timing | null;
  tools: ToolRow[];
  session_rows: SessionRow[];
  session_total: number;
  sources: SourcePayload[];
  conservation: ConservationCheck[];
  start_date: string | null;
  cache: { hits: number; misses: number; entries: number; capacity: number };
  stale?: boolean;
}

export interface Settings {
  alpha: number;
  topmost: boolean;
  peek: boolean;
  range: RangeKey;
  layout: "card" | "insights" | "diagnostics" | "settings";
  theme: "dark" | "light";
  hollow: boolean;
}

export interface SourceMeta {
  key: string;
  name: string;
  kind: string;
}

export interface Bootstrap {
  version: string;
  ranges: { key: RangeKey; label: string }[];
  settings: Settings;
  sources_meta: SourceMeta[];
  dpi: number | null;
  platform: string;
  fake_power?: boolean;
  start_date: string | null;
}

export interface ExportResult {
  path: string;
  bytes: number;
  revision: number;
}

export interface HudApi {
  bootstrap(): Promise<Bootstrap>;
  snapshot(range: RangeKey, seq: number): Promise<Snapshot>;
  detail(key: string, range: RangeKey): Promise<{ source: SourcePayload | null; range: RangeKey }>;
  get_settings(): Promise<Settings>;
  set_settings(patch: Partial<Settings>): Promise<Settings>;
  export_json(range: RangeKey): Promise<ExportResult>;
  power(action: string, confirmed: boolean): Promise<{ ok: boolean; reason?: string }>;
  cancel_power(): Promise<{ ok: boolean }>;
  window(action: string, value?: unknown): Promise<{ ok: boolean; reason?: string }>;
}
