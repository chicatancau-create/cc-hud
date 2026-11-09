import type { Snapshot } from "../types";
import { fmtCount, fmtTokens } from "../lib/format";

/* ────────────────────────────────────────────────────────────
   图表件：全部用「布局盒 + CSS」而不是 SVG 画，理由有两条
   1) SVG 里 text 会跟着 viewBox 缩放，字号无法和界面统一（旧版
      donut 中心写成 6px/3px 就是这个坑）；
   2) 柱宽要随 N 自适应：1 天不打成一根细线，60 天也不糊成一片。
   ──────────────────────────────────────────────────────────── */

const GRID_LINES = 4;   // 横向参考线条数（含顶线）

/** 每日 token：柱状 + 横向参考线 + 顶部数值（数据点少时才标） */
export function DailyBars({ snap }: { snap: Snapshot }) {
  const daily = snap.daily;
  const max = Math.max(1, ...daily.map((d) => d.tokens));
  const showValues = daily.length > 0 && daily.length <= 12;
  const step = daily.length > 14 ? Math.ceil(daily.length / 7) : 1;
  return (
    <div className="bars" data-testid="daily-bars">
      {daily.length === 0 ? (
        <div className="empty-note">本期无记录</div>
      ) : (
        <>
          <div className="bars-plot" style={{ ["--grid" as string]: String(GRID_LINES) }}>
            <div className="bars-grid" aria-hidden="true" />
            {daily.map((d) => (
              <div
                className="bar-col"
                key={d.date}
                title={`${d.date} · ${fmtTokens(d.tokens)} tok · ${d.reqs} 请求`}
              >
                {showValues ? <span className="bar-val">{fmtTokens(d.tokens)}</span> : null}
                {/* 高度按「列高 - 数值标签高度」算，标签才能紧贴柱顶而不是浮到顶栏 */}
                <div
                  className="bar"
                  style={{ height: d.tokens === 0 ? "3px" : `calc((100% - 14px) * ${(d.tokens / max).toFixed(4)})` }}
                  data-empty={d.tokens === 0 ? "1" : undefined}
                />
              </div>
            ))}
          </div>
          <div className="bars-axis">
            {daily.map((d, i) => (
              <span key={d.date} className="bar-lbl">
                {i % step === 0 || i === daily.length - 1 ? d.date.slice(5).replace("-", "/") : ""}
              </span>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

/** 24 小时请求分布：竖条 + 0/6/12/18/23 刻度 */
export function HourSpark({ snap }: { snap: Snapshot }) {
  const hours = snap.hourly;
  if (hours.length === 0) return <div className="empty-note">本期无记录</div>;
  const max = Math.max(1, ...hours.map((h) => h.reqs));
  return (
    <div className="hour-wrap" data-testid="hour-strip">
      <div className="hour-head">
        <span className="mini-title">按小时分布</span>
        <span className="dim">峰值 {fmtCount(max)} 请求/时</span>
      </div>
      <div className="hour-strip">
        {hours.map((h) => (
          <i
            key={h.hour}
            style={{ height: `${Math.max(2, (h.reqs / max) * 100)}%` }}
            data-peak={h.reqs === max && h.reqs > 0 ? "1" : undefined}
            title={`${h.hour} 时 · ${fmtCount(h.reqs)} 请求`}
          />
        ))}
      </div>
      <div className="hour-axis">
        <span>0</span><span>6</span><span>12</span><span>18</span><span>23</span>
      </div>
    </div>
  );
}

const LEVELS = 4;

/** 活跃热力图：近 26 周日历方格（7 行 × 26 列，列优先） */
export function Heatmap({ snap }: { snap: Snapshot }) {
  const byDate = new Map(snap.daily.map((d) => [d.date, d.tokens]));
  const max = Math.max(1, ...snap.daily.map((d) => d.tokens));
  const WEEKDAYS = ["一", "二", "三", "四", "五", "六", "日"];
  const today = new Date(snap.daily.at(-1)?.date ?? new Date().toISOString().slice(0, 10));
  // 对齐到本周一，回看 26 周 → 182 格
  const end = new Date(today);
  const dow = (end.getDay() + 6) % 7;
  end.setDate(end.getDate() + (6 - dow));
  const cells: { date: string; level: number; value: number }[] = [];
  for (let i = 181; i >= 0; i--) {
    const d = new Date(end);
    d.setDate(d.getDate() - i);
    const key = d.toISOString().slice(0, 10);
    const v = byDate.get(key) ?? 0;
    const level = v === 0 ? 0 : Math.max(1, Math.min(LEVELS, Math.ceil((v / max) * LEVELS)));
    cells.push({ date: key, level, value: v });
  }
  return (
    <div className="heat-wrap" data-testid="heatmap">
      <div className="heat-body">
        <ul className="heat-weekdays" aria-hidden="true">
          {WEEKDAYS.map((w, i) => <li key={w} data-show={i % 2 === 0 ? "1" : undefined}>{w}</li>)}
        </ul>
        <div className="heat" role="img" aria-label="近 26 周活跃度">
          {cells.map((c) => (
            <i
              key={c.date}
              className={`heat-cell heat-${c.level}`}
              title={`${c.date} · ${c.value ? fmtTokens(c.value) + " tok" : "无记录"}`}
            />
          ))}
        </div>
      </div>
      <div className="heat-legend">
        <span className="dim">少</span>
        {[0, 1, 2, 3, 4].map((l) => <i key={l} className={`heat-cell heat-${l}`} />)}
        <span className="dim">多</span>
      </div>
    </div>
  );
}

/** token 构成环：环用 SVG，中心文字用 HTML（字号才和界面一致） */
export function TokenDonut({ snap }: { snap: Snapshot }) {
  const total = snap.totals.tokens;
  const parts = [
    { key: "fresh_in", label: "新增输入", color: "var(--c-in)" },
    { key: "out", label: "输出", color: "var(--c-out)" },
    { key: "cache_read", label: "缓存读", color: "var(--c-read)" },
    { key: "cache_write", label: "缓存写", color: "var(--c-write)" }
  ] as const;
  const R = 52;
  const C = 2 * Math.PI * R;
  let offset = 0;
  return (
    <div className="donut-wrap">
      <div className="donut-box">
        <svg viewBox="0 0 120 120" className="donut" role="img" aria-label="token 构成">
          <circle cx="60" cy="60" r={R} fill="none" stroke="var(--track)" strokeWidth="12" />
          {total > 0 &&
            parts.map((p) => {
              const share = snap.totals[p.key] / total;
              const dash = share * C;
              const el = (
                <circle
                  key={p.key}
                  cx="60" cy="60" r={R} fill="none"
                  stroke={p.color} strokeWidth="12" strokeLinecap="butt"
                  strokeDasharray={`${Math.max(0, dash - 2)} ${C - Math.max(0, dash - 2)}`}
                  strokeDashoffset={-offset}
                  transform="rotate(-90 60 60)"
                  data-part={p.key}
                />
              );
              offset += dash;
              return el;
            })}
        </svg>
        <div className="donut-center">
          <b>{fmtTokens(total)}</b>
          <span>tokens</span>
        </div>
      </div>
      <ul className="legend">
        {parts.map((p) => (
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

/** 小卡里的一周走势：只给形状，不给数字，高度吃满剩余空间 */
export function CardSpark({ snap, days = 14, slots = 14 }: { snap: Snapshot; days?: number; slots?: number }) {
  const daily = snap.daily.slice(-days);
  if (daily.length === 0) return null;
  const max = Math.max(1, ...daily.map((d) => d.tokens));
  // 补空槽：范围只有 1 天时不能把整条渲染成一根占满全宽的柱子（看起来像个大色块）
  const ghosts = Math.max(0, slots - daily.length);
  return (
    <div className="card-spark" data-testid="card-spark" title={`近 ${daily.length} 天 token 走势`}>
      {Array.from({ length: ghosts }, (_, i) => (
        <i key={`ghost-${i}`} className="spark-ghost" aria-hidden="true" />
      ))}
      {daily.map((d) => (
        <i
          key={d.date}
          style={{ height: `${Math.max(6, (d.tokens / max) * 100)}%` }}
          title={`${d.date} · ${fmtTokens(d.tokens)} tok`}
        />
      ))}
    </div>
  );
}
