import type { Snapshot, SourcePayload } from "../types";
import { fmtCost, fmtCount, fmtTokens, fmtPct, sourceStatusText } from "../lib/format";
import { DailyBars, Heatmap, HourSpark, TokenDonut, CardSpark } from "./charts";

// 图表件放在 charts.tsx（布局盒画法），这里只做转发，调用方仍从 pieces 取
export { DailyBars, Heatmap, HourSpark, TokenDonut, CardSpark };

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

export function SourceCard({ source }: { source: SourcePayload }) {
  const t = source.totals;
  const note = source.suppressed
    ? `与 ${source.suppressed.by} 会话重叠 ${source.suppressed.clash} 个，整路拒绝并入`
    : source.reason ?? source.note;
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
      <p className="source-note" title={note}>{note}</p>
      <footer>
        <span>{source.sessions} 会话</span>
        <span>{source.supports_tokens ? "token 计入" : "仅请求/credits"}</span>
      </footer>
    </article>
  );
}

export function ModelsTable({ snap }: { snap: Snapshot }) {
  const total = Math.max(1, ...snap.models.map((m) => m.tokens));
  return (
    <table className="table models-table" data-testid="models-table">
      <colgroup>
        <col style={{ width: "32%" }} />
        <col style={{ width: "12%" }} />
        <col style={{ width: "20%" }} />
        <col style={{ width: "14%" }} />
        <col style={{ width: "22%" }} />
      </colgroup>
      <thead>
        <tr>
          <th>模型</th>
          <th className="num">请求</th>
          <th>tokens</th>
          <th className="num">成本</th>
          <th>来源</th>
        </tr>
      </thead>
      <tbody>
        {snap.models.length === 0 ? (
          <tr><td colSpan={5} className="empty-note">本期无记录</td></tr>
        ) : (
          snap.models.map((m) => (
            <tr key={m.name}>
              <td className="mono" title={m.name}>{m.name}</td>
              <td className="num">{fmtCount(m.reqs)}</td>
              <td className="tok-cell">
                <span className="tok-bar" aria-hidden="true">
                  <i style={{ width: `${(m.tokens / total) * 100}%` }} />
                </span>
                <span className="tok-text">{fmtTokens(m.tokens)}</span>
              </td>
              <td className="num">{m.cost > 0 ? fmtCost(m.cost) : "—"}</td>
              <td className="dim" title={m.sources.join(", ")}>{m.sources.join(", ")}</td>
            </tr>
          ))
        )}
      </tbody>
    </table>
  );
}

export function ToolsCard({ snap }: { snap: Snapshot }) {
  if (snap.tools.length === 0) {
    return (
      <div className="empty-state" data-testid="tools-card">
        <span className="empty-icon" aria-hidden="true">
          <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round">
            <path d="M2 12V7M6 12V4M10 12V8M14 12V6" />
          </svg>
        </span>
        <b>本期无工具调用记录</b>
        <p className="dim">来自 cc-haha transcript 的只读解析；该范围内没有工具调用，或对应会话尚未写入 transcript。</p>
      </div>
    );
  }
  const max = Math.max(1, ...snap.tools.map((t) => t.n));
  return (
    <ul className="app-list" data-testid="tools-card">
      {snap.tools.map((t) => (
        <li key={t.name}>
          <span className="app-name mono" title={t.name}>{t.name}</span>
          <span className="app-track accent"><i style={{ width: `${(t.n / max) * 100}%` }} /></span>
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
  const R = 42;
  const C = 2 * Math.PI * R;
  const dash = share === null ? 0 : (share / 100) * C;
  return (
    <div className="timing-wrap" data-testid="timing-card">
      <div className="donut-box small">
        <svg viewBox="0 0 100 100" className="donut" role="img" aria-label="首 token 占时">
          <circle cx="50" cy="50" r={R} fill="none" stroke="var(--track)" strokeWidth="10" />
          {share !== null && (
            <circle cx="50" cy="50" r={R} fill="none" stroke="var(--c-in)" strokeWidth="10"
              strokeDasharray={`${dash} ${C - dash}`} strokeDashoffset={0}
              transform="rotate(-90 50 50)" />
          )}
        </svg>
        <div className="donut-center">
          <b>{share === null ? "—" : `${share.toFixed(0)}%`}</b>
          <span>首 token</span>
        </div>
      </div>
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
      rev {snap.revision} · 快照缓存 {snap.cache.entries}/{snap.cache.capacity}（命中 {snap.cache.hits} / 未命中 {snap.cache.misses}）
      {snap.kpis.cache_hit === null ? "" : ` · 命中率 ${fmtPct(snap.kpis.cache_hit)}`}
    </span>
  );
}
