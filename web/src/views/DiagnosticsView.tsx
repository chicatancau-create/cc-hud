import type { ExportResult, RangeKey, Settings, Snapshot } from "../types";
import { fmtCost, fmtCount, fmtTokens, sourceStatusText } from "../lib/format";

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
            revision {snap.revision} · 快照缓存 {snap.cache.entries}/{snap.cache.capacity} ·
            命中 {snap.cache.hits} / 未命中 {snap.cache.misses} · 范围 {range}
          </p>
        </div>
        <div className="head-actions">
          <button className="ghost" onClick={onExport}>导出</button>
          <button className="ghost" data-testid="nav-settings" onClick={() => onNavigate("settings")}>设置</button>
          <button className="ghost" data-testid="nav-insights" onClick={() => onNavigate("insights")}>洞察</button>
          <button className="ghost" data-testid="nav-card" onClick={() => onNavigate("card")}>小卡</button>
        </div>
      </header>

      <section className="card">
        <div className="card-head">
          <h3>守恒校验</h3>
          <span className={failed.length ? "warn" : "ok-text"}>
            {failed.length ? `${failed.length} / ${snap.conservation.length} 项失败` : `${snap.conservation.length} 项全部通过`}
          </span>
        </div>
        <table className="table" data-testid="conservation-table">
          <colgroup>
            <col style={{ width: "58px" }} />
            <col style={{ width: "30%" }} />
            <col />
          </colgroup>
          <thead><tr><th>状态</th><th>检查</th><th>详情</th></tr></thead>
          <tbody>
            {snap.conservation.map((c) => (
              <tr key={c.name} className={c.ok ? "" : "row-bad"}>
                <td className={c.ok ? "ok-text" : "warn"}>{c.ok ? "✓" : "✕"}</td>
                <td className="mono" title={c.name}>{c.name}</td>
                <td className="dim" title={c.detail}>{c.detail}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="card">
        <div className="card-head"><h3>九路状态</h3><span className="dim">只读 · SQLite mode=ro</span></div>
        <table className="table" data-testid="sources-table">
          <colgroup>
            <col style={{ width: "116px" }} />
            <col style={{ width: "92px" }} />
            <col style={{ width: "76px" }} />
            <col style={{ width: "88px" }} />
            <col style={{ width: "78px" }} />
            <col style={{ width: "60px" }} />
            <col />
          </colgroup>
          <thead>
            <tr>
              <th>来源</th><th>状态</th>
              <th className="num">请求</th><th className="num">tokens</th><th className="num">成本</th>
              <th className="num">会话</th><th>说明</th>
            </tr>
          </thead>
          <tbody>
            {snap.sources.map((s) => {
              const note = s.reason ?? (s.suppressed ? `与 ${s.suppressed.by} 重叠 ${s.suppressed.clash} 个会话` : s.note);
              return (
                <tr key={s.key} data-key={s.key}>
                  <td title={s.name}>{s.name}</td>
                  <td>
                    <span className={`pill pill-${s.suppressed ? "suppressed" : s.status}`}>
                      {sourceStatusText(s.status, Boolean(s.suppressed))}
                    </span>
                  </td>
                  <td className="num">{fmtCount(s.totals.reqs)}</td>
                  <td className="num">{fmtTokens(s.totals.tokens)}</td>
                  <td className="num">{s.supports_cost ? fmtCost(s.totals.cost) : "—"}</td>
                  <td className="num">{s.sessions}</td>
                  <td className="dim" title={note}>{note}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </section>

      <section className="card">
        <div className="card-head"><h3>运行参数</h3><span className="dim">settings + 本次快照</span></div>
        <ul className="kv">
          <li><span>窗口透明度</span><b>{Math.round(settings.alpha * 100)}%</b></li>
          <li><span>置顶</span><b>{settings.topmost ? "开" : "关"}</b></li>
          <li><span>呼出圆点</span><b>{settings.peek ? "开" : "关"}</b></li>
          <li><span>背景镂空</span><b>{settings.hollow ? "开（圆角区域 + alpha）" : "关"}</b></li>
          <li><span>范围起点</span><b>{snap.start_date ?? "全部"}</b></li>
          <li><span>快照时间</span><b>{new Date(snap.generated_at * 1000).toLocaleString("zh-CN")}</b></li>
          <li><span>导出</span><b title={exportResult?.path}>{exportResult ? `${exportResult.path} · ${exportResult.bytes}B · rev ${exportResult.revision}` : "尚未导出"}</b></li>
        </ul>
      </section>
    </div>
  );
}
