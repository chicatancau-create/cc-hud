import type { ExportResult, RangeKey, Settings, Snapshot } from "../types";
import { fmtCost, fmtTokens, sourceStatusText } from "../lib/format";

interface Props {
  snap: Snapshot;
  settings: Settings;
  range: RangeKey;
  exportResult: ExportResult | null;
  onExport: () => void;
  onNavigate: (layout: "card" | "insights" | "settings") => void;
}

export function DiagnosticsView({ snap, settings, range, exportResult, onExport, onNavigate }: Props) {
  const failed = snap.conservation.filter((c) => !c.ok);
  return (
    <div className="page" data-testid="diagnostics">
      <header className="page-head">
        <div>
          <h1>诊断</h1>
          <p className="dim">
            revision {snap.revision} · 缓存 {snap.cache.entries}/{snap.cache.capacity} ·
            命中 {snap.cache.hits} / 未命中 {snap.cache.misses} · 范围 {range}
          </p>
        </div>
        <div className="head-actions">
          <button className="ghost" onClick={onExport}>导出</button>
          <button className="ghost" onClick={() => onNavigate("insights")}>回洞察</button>
          <button className="ghost" onClick={() => onNavigate("card")}>小卡</button>
        </div>
      </header>

      <section className="card">
        <div className="card-head"><h3>守恒校验</h3>
          <span className={failed.length ? "warn" : "ok-text"}>
            {failed.length ? `${failed.length} 项失败` : "全部通过"}
          </span>
        </div>
        <table className="table" data-testid="conservation-table">
          <thead><tr><th>状态</th><th>检查</th><th>详情</th></tr></thead>
          <tbody>
            {snap.conservation.map((c) => (
              <tr key={c.name} className={c.ok ? "" : "row-bad"}>
                <td>{c.ok ? "✓" : "✕"}</td>
                <td className="mono">{c.name}</td>
                <td className="dim">{c.detail}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="card">
        <div className="card-head"><h3>九路状态</h3><span className="dim">只读 · SQLite mode=ro</span></div>
        <table className="table" data-testid="sources-table">
          <thead>
            <tr><th>来源</th><th>状态</th><th>请求</th><th>tokens</th><th>成本</th><th>会话</th><th>说明</th></tr>
          </thead>
          <tbody>
            {snap.sources.map((s) => (
              <tr key={s.key} data-key={s.key}>
                <td>{s.name}</td>
                <td>
                  <span className={`pill pill-${s.suppressed ? "suppressed" : s.status}`}>
                    {sourceStatusText(s.status, Boolean(s.suppressed))}
                  </span>
                </td>
                <td>{s.totals.reqs}</td>
                <td>{fmtTokens(s.totals.tokens)}</td>
                <td>{s.supports_cost ? fmtCost(s.totals.cost) : "—"}</td>
                <td>{s.sessions}</td>
                <td className="dim">{s.reason ?? (s.suppressed ? `与 ${s.suppressed.by} 重叠 ${s.suppressed.clash}` : s.note)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="card">
        <div className="card-head"><h3>运行参数</h3></div>
        <ul className="kv">
          <li><span>窗口透明度</span><b>{settings.alpha}</b></li>
          <li><span>置顶</span><b>{settings.topmost ? "开" : "关"}</b></li>
          <li><span>呼出圆点</span><b>{settings.peek ? "开" : "关"}</b></li>
          <li><span>背景镂空</span><b>{settings.hollow ? "开（需实机门禁）" : "关"}</b></li>
          <li><span>导出</span><b>{exportResult ? `${exportResult.path} · ${exportResult.bytes}B · rev ${exportResult.revision}` : "尚未导出"}</b></li>
          <li><span>范围起点</span><b>{snap.start_date ?? "全部"}</b></li>
        </ul>
      </section>
    </div>
  );
}
