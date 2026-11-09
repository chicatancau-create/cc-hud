import type { RangeKey, Snapshot } from "../types";
import { fmtCost, fmtCount, fmtPct, fmtTokens } from "../lib/format";
import { snapshotBanner } from "../lib/snapStatus";

interface Props {
  snap: Snapshot;
  range: RangeKey;
  refreshing: boolean;
  onRange: (r: RangeKey) => void;
  onExpand: () => void;
  onSettings: () => void;
}

const RANGES: { key: RangeKey; label: string }[] = [
  { key: "1d", label: "今日" }, { key: "7d", label: "7 天" },
  { key: "30d", label: "30 天" }, { key: "all", label: "全部" }
];

export function CardView({ snap, range, refreshing, onRange, onExpand, onSettings }: Props) {
  const t = snap.totals;
  const today = snap.daily.at(-1);
  const maxApp = Math.max(1, ...snap.apps.map((a) => a.tokens));
  const okCount = snap.sources.filter((s) => s.status === "ok" && !s.suppressed).length;
  const errCount = snap.sources.filter((s) => s.status === "error").length;
  const unsupported = snap.sources.filter((s) => s.status === "unsupported").length;
  // 与 InsightsView 同一口径（snap.status）：全错/空/不支持时小卡也必须说明数字不可信
  const banner = snapshotBanner(snap);
  return (
    <div className={banner ? "card-view has-status" : "card-view"} data-testid="card-view">
      <header className="card-head">
        <div className="brand">
          <span className="dot" data-alive={refreshing ? "busy" : "idle"} />
          <b>cc-hud</b>
          <span className="dim">rev {snap.revision}</span>
        </div>
        <div className="seg small">
          {RANGES.map((r) => (
            <button key={r.key} className={range === r.key ? "on" : ""} onClick={() => onRange(r.key)}>
              {r.label}
            </button>
          ))}
        </div>
        <div className="card-icons">
          <button className="icon" title="设置" aria-label="设置" onClick={onSettings}>⚙</button>
          <button className="icon" data-testid="expand-insights" title="展开洞察" aria-label="展开洞察" onClick={onExpand}>⤢</button>
        </div>
      </header>

      {banner ? (
        <div className="card-banner" data-testid="card-status" data-tone={banner.tone}
          role="status" title={banner.text}>
          {banner.short}
        </div>
      ) : null}

      <div className="hero">
        <div>
          <div className="hero-label">成本</div>
          <div className="hero-value">{fmtCost(snap.kpis.cost)}</div>
        </div>
        <div>
          <div className="hero-label">tokens</div>
          <div className="hero-value">{fmtTokens(t.tokens)}</div>
        </div>
        <div>
          <div className="hero-label">命中率</div>
          <div className="hero-value">{fmtPct(snap.kpis.cache_hit)}</div>
        </div>
      </div>

      <div className="mini-row">
        <div><span>今日请求</span><b>{today ? fmtCount(today.reqs) : "—"}</b></div>
        <div><span>新增输入</span><b>{fmtTokens(t.fresh_in)}</b></div>
        <div><span>输出</span><b>{fmtTokens(t.out)}</b></div>
        <div><span>缓存读</span><b>{fmtTokens(t.cache_read)}</b></div>
      </div>

      <div className="app-bars">
        {snap.apps.slice(0, 4).map((a) => (
          <div key={a.key} className="app-bar">
            <span>{a.name}</span>
            <i><b style={{ width: `${(a.tokens / maxApp) * 100}%` }} /></i>
            <em>{fmtTokens(a.tokens)}</em>
          </div>
        ))}
        {snap.apps.length === 0 ? <div className="empty-note">本期无记录</div> : null}
      </div>

      <footer className="card-foot">
        <span>{okCount}/{snap.sources.length} 路正常</span>
        {errCount > 0 ? <span className="warn">{errCount} 路读取异常</span> : null}
        {unsupported > 0 ? <span className="dim">{unsupported} 路不支持</span> : null}
        <span className="dim">缓存 {snap.cache.entries}/{snap.cache.capacity}</span>
      </footer>
    </div>
  );
}
