import type { RangeKey, Snapshot } from "../types";
import { fmtCost, fmtCount, fmtPct, fmtTokens } from "../lib/format";
import { snapshotBanner } from "../lib/snapStatus";
import { CacheHint, DailyBars, Heatmap, HourSpark, Kpi, ModelsTable, SourceCard, TimingCard, TokenDonut, ToolsCard } from "../components/pieces";
import { SessionsGrid } from "../components/SessionsGrid";

interface Props {
  snap: Snapshot;
  range: RangeKey;
  refreshing: boolean;
  onRange: (r: RangeKey) => void;
  onRefresh: () => void;
  onExport: () => void;
  onNavigate: (layout: "card" | "diagnostics" | "settings") => void;
}

const RANGES: { key: RangeKey; label: string }[] = [
  { key: "1d", label: "今日" }, { key: "7d", label: "7 天" },
  { key: "30d", label: "30 天" }, { key: "all", label: "全部" }
];

export function InsightsView({ snap, range, refreshing, onRange, onRefresh, onExport, onNavigate }: Props) {
  const k = snap.kpis;
  const okCount = snap.sources.filter((s) => s.status === "ok" && !s.suppressed).length;
  const badChecks = snap.conservation.filter((c) => !c.ok);
  const banner = snapshotBanner(snap);
  const span = snap.daily.length ? `${snap.daily[0].date} → ${snap.daily.at(-1)?.date}` : "无记录";
  return (
    <div className="page" data-testid="insights">
      <header className="page-head">
        <div>
          <h1>上下文洞察</h1>
          <p className="dim">
            {snap.start_date ? `${snap.start_date} 起` : "全部时间"} · {snap.daily.length} 个活跃日 ·{" "}
            <CacheHint snap={snap} />
          </p>
        </div>
        <div className="head-actions">
          <div className="seg" role="group" aria-label="时间范围">
            {RANGES.map((r) => (
              <button key={r.key} data-testid={`range-${r.key}`} className={range === r.key ? "on" : ""} onClick={() => onRange(r.key)}>
                {r.label}
              </button>
            ))}
          </div>
          <button className="ghost" onClick={onRefresh} disabled={refreshing}>
            {refreshing ? "刷新中" : "刷新"}
          </button>
          <button className="ghost" onClick={onExport}>导出</button>
          <button className="ghost" data-testid="nav-settings" onClick={() => onNavigate("settings")}>设置</button>
        </div>
      </header>

      {banner ? (
        <div className="banner" data-testid="snap-status" data-tone={banner.tone}>{banner.text}</div>
      ) : null}

      <section className="first">
        <div className="kpis">
          <Kpi label="会话" value={fmtCount(k.sessions)} sub={`${okCount}/${snap.sources.length} 路来源正常`} />
          <Kpi label="tokens" value={fmtTokens(k.tokens)} sub={`新增 ${fmtTokens(snap.totals.fresh_in)}`} />
          <Kpi label="成本" value={fmtCost(k.cost)} sub={k.cost === null ? "来源无定价" : "本机账"} tone="cost" />
          <Kpi label="缓存命中" value={fmtPct(k.cache_hit)} sub={k.cache_hit === null ? "无分母" : "读 / 总输入"} />
          <Kpi label="活跃日" value={fmtCount(k.active_days)} sub={`请求 ${fmtCount(snap.totals.reqs)}`} />
          <Kpi label="credits" value={k.credits === null ? "—" : k.credits.toFixed(1)} sub="仅 Qoder 系" />
        </div>
        <div className="card usage">
          <div className="card-head">
            <h3>每日 token</h3>
            <span className="dim">{span}</span>
          </div>
          <DailyBars snap={snap} />
          <HourSpark snap={snap} />
        </div>
      </section>

      <section className="stats">
        <div className="card">
          <div className="card-head"><h3>token 构成</h3><span className="dim">占总量</span></div>
          <TokenDonut snap={snap} />
        </div>
        <div className="card">
          <div className="card-head"><h3>按应用</h3><span className="dim">token 排序</span></div>
          {snap.apps.length === 0 ? <div className="empty-note">本期无记录</div> : (
            <ul className="app-list">
              {snap.apps.map((a) => {
                const max = Math.max(1, ...snap.apps.map((x) => x.tokens));
                return (
                  <li key={a.key}>
                    <span className="app-name" title={a.name}>{a.name}</span>
                    <span className="app-track"><i style={{ width: `${(a.tokens / max) * 100}%` }} /></span>
                    <b>{fmtTokens(a.tokens)}</b>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </section>

      <section className="tiles">
        <div className="card tile" data-testid="tile-heat">
          <div className="card-head"><h3>活跃热力图</h3><span className="dim">近 26 周</span></div>
          <Heatmap snap={snap} />
        </div>
        <div className="card tile" data-testid="tile-tools">
          <div className="card-head"><h3>工具调用</h3><span className="dim">cc-haha transcript</span></div>
          <ToolsCard snap={snap} />
        </div>
        <div className="card tile wide" data-testid="tile-models">
          <div className="card-head"><h3>模型</h3><span className="dim">按 token 降序</span></div>
          <ModelsTable snap={snap} />
        </div>
      </section>

      <SessionsGrid snap={snap} />

      <section>
        <div className="section-head">
          <h2>数据来源</h2>
          <span className="dim">{snap.sources.length} 路 · {badChecks.length ? `${badChecks.length} 项守恒异常` : "守恒全部通过"}</span>
        </div>
        <div className="sources-grid">
          {snap.sources.map((s) => <SourceCard key={s.key} source={s} />)}
        </div>
      </section>

      {/* 底部独立检测区：放在会话与数据来源之后、页脚之前，避免和并排卡片拼高度 */}
      <section className="checks-zone" data-testid="checks-zone">
        <div className="card tile wide timing-wide" data-testid="tile-timing">
          <div className="card-head"><h3>耗时</h3><span className="dim">代理日志实测</span></div>
          <TimingCard snap={snap} />
        </div>
        <div className="card" data-testid="tile-conservation">
          <div className="card-head">
            <h3>守恒校验</h3>
            <span className={badChecks.length ? "warn" : "ok-text"}>
              {badChecks.length ? `${badChecks.length} 项失败` : `${snap.conservation.length} 项全通过`}
            </span>
          </div>
          {snap.conservation.length === 0 ? <div className="empty-note">无校验项</div> : (
            <ul className="checks checks-2col">
              {snap.conservation.map((c) => (
                <li key={c.name} className={c.ok ? "ok" : "bad"} data-ok={c.ok ? "1" : "0"}>
                  <i>{c.ok ? "✓" : "✕"}</i>
                  <span className="mono">{c.name}</span>
                  <span className="dim" title={c.detail}>{c.detail}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </section>

      <footer className="page-foot">
        <button className="ghost" data-testid="nav-diagnostics" onClick={() => onNavigate("diagnostics")}>打开诊断</button>
        <button className="ghost" data-testid="collapse-card" onClick={() => onNavigate("card")}>收起为小卡</button>
      </footer>
    </div>
  );
}
