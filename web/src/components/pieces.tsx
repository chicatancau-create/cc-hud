import type { Snapshot, SourcePayload } from "../types";
import { fmtCost, fmtCount, fmtTokens, fmtPct, sourceStatusText } from "../lib/format";

export function StatusPill({ source }: { source: SourcePayload }) {
  const kind = source.suppressed ? "suppressed" : source.status;
  return (
    <span className={`pill pill-${kind}`} data-status={kind} title={source.reason ?? ""}>
      {sourceStatusText(source.status, Boolean(source.suppressed))}
    </span>
  );
}

export function Kpi({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: string }) {
  return (
    <div className={`kpi${tone ? ` tone-${tone}` : ""}`}>
      <div className="kpi-label">{label}</div>
      <div className="kpi-value">{value}</div>
      {sub ? <div className="kpi-sub">{sub}</div> : null}
    </div>
  );
}

const PARTS = [
  { key: "fresh_in", label: "新增输入", color: "var(--c-in)" },
  { key: "out", label: "输出", color: "var(--c-out)" },
  { key: "cache_read", label: "缓存读", color: "var(--c-read)" },
  { key: "cache_write", label: "缓存写", color: "var(--c-write)" }
] as const;

export function TokenDonut({ snap }: { snap: Snapshot }) {
  const total = snap.totals.tokens;
  let offset = 0;
  const circumference = 2 * Math.PI * 15.9155;
  return (
    <div className="donut-wrap">
      <svg viewBox="0 0 42 42" className="donut" role="img" aria-label="token 构成">
        <circle cx="21" cy="21" r="15.9155" fill="none" stroke="var(--track)" strokeWidth="4" />
        {total > 0 &&
          PARTS.map((p) => {
            const value = snap.totals[p.key];
            const share = (value / total) * 100;
            const dash = (share / 100) * circumference;
            const el = (
              <circle
                key={p.key}
                cx="21"
                cy="21"
                r="15.9155"
                fill="none"
                stroke={p.color}
                strokeWidth="4"
                strokeDasharray={`${dash} ${circumference - dash}`}
                strokeDashoffset={-((offset / 100) * circumference)}
                transform="rotate(-90 21 21)"
                data-part={p.key}
              />
            );
            offset += share;
            return el;
          })}
        <text x="21" y="20" textAnchor="middle" className="donut-num">
          {total >= 1e4 ? `${(total / 1e4).toFixed(1)}万` : total}
        </text>
        <text x="21" y="25" textAnchor="middle" className="donut-cap">
          tokens
        </text>
      </svg>
      <ul className="legend">
        {PARTS.map((p) => (
          <li key={p.key}>
            <i style={{ background: p.color }} />
            <span>{p.label}</span>
            <b>{fmtTokens(snap.totals[p.key])}</b>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function DailyBars({ snap }: { snap: Snapshot }) {
  const max = Math.max(1, ...snap.daily.map((d) => d.tokens));
  return (
    <div className="bars" data-testid="daily-bars">
      {snap.daily.length === 0 ? (
        <div className="empty-note">本期无记录</div>
      ) : (
        snap.daily.map((d) => (
          <div className="bar-col" key={d.date} title={`${d.date} · ${fmtTokens(d.tokens)} tok · ${fmtCost(d.cost)}`}>
            <div className="bar" style={{ height: `${Math.max(2, (d.tokens / max) * 100)}%` }} />
            <span className="bar-lbl">{d.date.slice(5)}</span>
          </div>
        ))
      )}
    </div>
  );
}

export function Heatmap({ snap }: { snap: Snapshot }) {
  const byDate = new Map(snap.daily.map((d) => [d.date, d.tokens]));
  const max = Math.max(1, ...snap.daily.map((d) => d.tokens));
  const cells: { date: string; level: number }[] = [];
  const today = new Date(snap.daily.at(-1)?.date ?? "2026-11-07");
  for (let i = 55; i >= 0; i--) {
    const d = new Date(today);
    d.setDate(d.getDate() - i);
    const key = d.toISOString().slice(0, 10);
    const v = byDate.get(key) ?? 0;
    cells.push({ date: key, level: v === 0 ? 0 : Math.min(4, Math.ceil((v / max) * 4)) });
  }
  return (
    <div className="heat" data-testid="heatmap">
      {cells.map((c) => (
        <i key={c.date} className={`heat-cell heat-${c.level}`} title={`${c.date} · ${byDate.get(c.date) ? "有记录" : "无记录"}`} />
      ))}
    </div>
  );
}

export function SourceCard({ source }: { source: SourcePayload }) {
  const t = source.totals;
  return (
    <article className={`source source-${source.status}`} data-key={source.key}>
      <header>
        <h4>{source.name}</h4>
        <StatusPill source={source} />
      </header>
      <div className="source-nums">
        <div><b>{fmtCount(t.reqs)}</b><span>请求</span></div>
        <div><b>{fmtTokens(t.tokens)}</b><span>tokens</span></div>
        <div><b>{source.supports_cost ? fmtCost(t.cost) : "—"}</b><span>成本</span></div>
      </div>
      <p className="source-note">
        {source.suppressed
          ? `与 ${source.suppressed.by} 会话重叠 ${source.suppressed.clash} 个，整路拒绝并入`
          : source.reason ?? source.note}
      </p>
      <footer>
        <span>{source.sessions} 会话</span>
        <span>{source.supports_tokens ? "token 计入" : "仅请求/credits"}</span>
      </footer>
    </article>
  );
}

export function ModelsTable({ snap }: { snap: Snapshot }) {
  return (
    <table className="table" data-testid="models-table">
      <thead>
        <tr><th>模型</th><th>请求</th><th>tokens</th><th>成本</th><th>来源</th></tr>
      </thead>
      <tbody>
        {snap.models.length === 0 ? (
          <tr><td colSpan={5} className="empty-note">本期无记录</td></tr>
        ) : (
          snap.models.map((m) => (
            <tr key={m.name}>
              <td className="mono">{m.name}</td>
              <td>{fmtCount(m.reqs)}</td>
              <td>{fmtTokens(m.tokens)}</td>
              <td>{m.cost > 0 ? fmtCost(m.cost) : "—"}</td>
              <td className="dim">{m.sources.join(", ")}</td>
            </tr>
          ))
        )}
      </tbody>
    </table>
  );
}

export function ToolsCard({ snap }: { snap: Snapshot }) {
  if (snap.tools.length === 0) return <div className="empty-note">本期无工具调用记录</div>;
  const max = Math.max(1, ...snap.tools.map((t) => t.n));
  return (
    <ul className="app-list" data-testid="tools-card">
      {snap.tools.map((t) => (
        <li key={t.name}>
          <span className="app-name mono">{t.name}</span>
          <span className="app-track"><i style={{ width: `${(t.n / max) * 100}%` }} /></span>
          <b>{fmtCount(t.n)}</b>
        </li>
      ))}
    </ul>
  );
}

export function TimingCard({ snap }: { snap: Snapshot }) {
  const t = snap.timing;
  if (!t) return <div className="empty-note">无耗时数据（代理日志缺少 latency 列）</div>;
  const share = t.p50 && t.ftt_p50 ? Math.min(100, (t.ftt_p50 / t.p50) * 100) : null;
  const circumference = 2 * Math.PI * 15.9155;
  const dash = share === null ? 0 : (share / 100) * circumference;
  return (
    <div className="timing-wrap" data-testid="timing-card">
      <svg viewBox="0 0 42 42" className="donut small" role="img" aria-label="首 token 占时">
        <circle cx="21" cy="21" r="15.9155" fill="none" stroke="var(--track)" strokeWidth="4" />
        {share !== null && (
          <circle cx="21" cy="21" r="15.9155" fill="none" stroke="var(--c-in)" strokeWidth="4"
            strokeDasharray={`${dash} ${circumference - dash}`} transform="rotate(-90 21 21)" />
        )}
        <text x="21" y="21" textAnchor="middle" className="donut-num">
          {share === null ? "—" : `${share.toFixed(0)}%`}
        </text>
        <text x="21" y="25.5" textAnchor="middle" className="donut-cap">首token</text>
      </svg>
      <ul className="timing-rows">
        <li><span>请求 P50</span><b>{t.p50 === null ? "—" : `${(t.p50 / 1000).toFixed(2)}s`}</b></li>
        <li><span>请求 P95</span><b>{t.p95 === null ? "—" : `${(t.p95 / 1000).toFixed(2)}s`}</b></li>
        <li><span>首 token P50</span><b>{t.ftt_p50 === null ? "—" : `${(t.ftt_p50 / 1000).toFixed(2)}s`}</b></li>
        <li><span>样本</span><b>{fmtCount(t.n)} / {fmtCount(t.ftt_n)}</b></li>
      </ul>
    </div>
  );
}

export function CacheHint({ snap }: { snap: Snapshot }) {
  return (
    <span className="dim cache-hint" data-testid="cache-hint">
      rev {snap.revision} · 缓存 {snap.cache.entries}/{snap.cache.capacity} · 命中 {snap.cache.hits}
      {snap.kpis.cache_hit === null ? "" : ` · 命中率 ${fmtPct(snap.kpis.cache_hit)}`}
    </span>
  );
}
