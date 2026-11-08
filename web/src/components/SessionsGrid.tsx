import { useMemo, useState } from "react";
import type { Snapshot } from "../types";
import { dateShort, fmtCount, fmtCost, fmtTokens } from "../lib/format";

const PER_PAGE = 12;

export function SessionsGrid({ snap }: { snap: Snapshot }) {
  const [q, setQ] = useState("");
  const [src, setSrc] = useState("all");
  const [page, setPage] = useState(0);

  const sources = useMemo(
    () => Array.from(new Set(snap.session_rows.map((r) => r.source))).sort(),
    [snap.session_rows]
  );

  const rows = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return snap.session_rows.filter((r) => {
      if (src !== "all" && r.source !== src) return false;
      if (!needle) return true;
      return `${r.id} ${r.model ?? ""} ${r.source}`.toLowerCase().includes(needle);
    });
  }, [snap.session_rows, q, src]);

  const pages = Math.max(1, Math.ceil(rows.length / PER_PAGE));
  const current = Math.min(page, pages - 1);
  const visible = rows.slice(current * PER_PAGE, current * PER_PAGE + PER_PAGE);
  const last = visible[0]?.last_seen;

  return (
    <section data-testid="sessions">
      <div className="section-head">
        <h2>会话</h2>
        <span className="dim">
          共 {fmtCount(snap.session_total)} 个 · 显示 {rows.length} 个
          {last ? " · 最近有记录" : ""}
        </span>
      </div>

      <div className="sess-toolbar">
        <input
          className="search"
          placeholder="搜索会话 id / 模型 / 来源"
          value={q}
          aria-label="搜索会话"
          onChange={(e) => { setQ(e.target.value); setPage(0); }}
        />
        <div className="chips" role="group" aria-label="按来源筛选">
          <button className={src === "all" ? "chip on" : "chip"} onClick={() => { setSrc("all"); setPage(0); }}>全部</button>
          {sources.map((s) => (
            <button key={s} className={src === s ? "chip on" : "chip"}
              onClick={() => { setSrc(s); setPage(0); }}>{s}</button>
          ))}
        </div>
        <span className="dim">第 {current + 1}/{pages} 页</span>
      </div>

      {visible.length === 0 ? (
        <div className="empty-note card">{snap.session_rows.length ? "没有匹配的会话" : "本期无会话记录"}</div>
      ) : (
        <div className="sessions-grid">
          {visible.map((r) => (
            <article className="session-card" key={`${r.source}:${r.id}`}>
              <header>
                <span className="mono sess-id" title={r.id}>{r.id}</span>
                <span className="pill pill-soft">{r.source}</span>
              </header>
              <div className="sess-model mono">{r.model ?? "—"}</div>
              <div className="sess-nums">
                <div><b>{fmtTokens(r.tokens)}</b><span>tokens</span></div>
                <div><b>{fmtCount(r.reqs)}</b><span>请求</span></div>
                <div><b>{r.cost > 0 ? fmtCost(r.cost) : r.credits > 0 ? r.credits.toFixed(1) : "—"}</b>
                  <span>{r.cost > 0 ? "成本" : r.credits > 0 ? "credits" : "无定价"}</span></div>
              </div>
              <footer>{r.last_seen ? `最后请求 ${dateShort(new Date(r.last_seen * 1000).toISOString().slice(0, 10))}` : "无时间"}</footer>
            </article>
          ))}
        </div>
      )}

      <div className="pager">
        <button className="ghost" disabled={current === 0} onClick={() => setPage(current - 1)}>上一页</button>
        <button className="ghost" disabled={current >= pages - 1} onClick={() => setPage(current + 1)}>下一页</button>
      </div>
    </section>
  );
}
