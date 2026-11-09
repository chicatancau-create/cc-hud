import { useEffect, useState } from "react";
import type { Settings } from "../types";

interface Props {
  settings: Settings;
  onChange: (patch: Partial<Settings>) => void;
  onExport: () => void;
  onPower: (action: string, confirmed: boolean) => Promise<{ ok: boolean; reason?: string }>;
  onCancelPower: () => Promise<{ ok: boolean }>;
  onNavigate: (layout: "card" | "insights" | "diagnostics") => void;
}

const ALPHAS = [1, 0.96, 0.92, 0.86, 0.78];
const POWERS: { action: string; label: string }[] = [
  { action: "lock", label: "锁定" },
  { action: "sleep", label: "睡眠" },
  { action: "hibernate", label: "休眠" },
  { action: "shutdown", label: "关机" },
  { action: "restart", label: "重启" },
  { action: "logoff", label: "注销" }
];

export function SettingsView({ settings, onChange, onExport, onPower, onCancelPower, onNavigate }: Props) {
  const [pending, setPending] = useState<string | null>(null);
  const [msg, setMsg] = useState<string>("");

  useEffect(() => {
    if (!pending) return;
    const t = window.setTimeout(() => {
      setPending(null);
      setMsg("确认超时，已取消");
      void onCancelPower();
    }, 15000);
    return () => window.clearTimeout(t);
  }, [pending, onCancelPower]);

  const fire = async (action: string) => {
    if (pending !== action) {
      setPending(action);
      setMsg(`再次点击「${POWERS.find((p) => p.action === action)?.label}」确认（15 秒倒计时）`);
      return;
    }
    const r = await onPower(action, true);
    setPending(null);
    setMsg(r.ok ? `已执行 ${action}` : r.reason ?? "失败");
  };

  return (
    <div className="page" data-testid="settings">
      <header className="page-head">
        <div><h1>设置</h1><p className="dim">改动立即生效并写入 hud-next-state.json</p></div>
        <div className="head-actions">
          <button className="ghost" data-testid="nav-insights" onClick={() => onNavigate("insights")}>回洞察</button>
          <button className="ghost" data-testid="nav-card" onClick={() => onNavigate("card")}>小卡</button>
        </div>
      </header>

      <section className="card">
        <div className="card-head"><h3>外观</h3></div>
        <div className="field">
          <span>整窗透明度（Win32）</span>
          <div className="seg">
            {ALPHAS.map((a) => (
              <button key={a} className={Math.abs(settings.alpha - a) < 1e-6 ? "on" : ""}
                onClick={() => onChange({ alpha: a })}>{Math.round(a * 100)}%</button>
            ))}
          </div>
        </div>
        <label className="switch">
          <input type="checkbox" checked={settings.topmost} onChange={(e) => onChange({ topmost: e.target.checked })} />
          <span>窗口置顶</span>
        </label>
        <label className="switch">
          <input type="checkbox" checked={settings.peek} onChange={(e) => onChange({ peek: e.target.checked })} />
          <span>隐藏后保留呼出圆点</span>
        </label>
        <label className="switch">
          <input type="checkbox" checked={settings.hollow} onChange={(e) => onChange({ hollow: e.target.checked })} />
          <span>小卡圆角镂空</span>
        </label>
        <div className="field">
          <span>主题</span>
          <div className="seg">
            <button className={settings.theme === "dark" ? "on" : ""} onClick={() => onChange({ theme: "dark" })}>深色</button>
            <button className={settings.theme === "light" ? "on" : ""} onClick={() => onChange({ theme: "light" })}>浅色</button>
          </div>
        </div>
      </section>

      <section className="card">
        <div className="card-head"><h3>数据</h3></div>
        <p className="dim">导出当前范围快照（含 revision，URL/凭据已脱敏）。</p>
        <button className="ghost" onClick={onExport}>导出 JSON</button>
      </section>

      <section className="card">
        <div className="card-head"><h3>电源</h3><span className="dim">两次确认 · 测试注入假执行器</span></div>
        <div className="power-grid">
          {POWERS.map((p) => (
            <button key={p.action} className={pending === p.action ? "danger" : "ghost"} onClick={() => void fire(p.action)}>
              {p.label}
            </button>
          ))}
        </div>
        {msg ? <p className="dim" data-testid="power-msg">{msg}</p> : null}
        {pending ? <button className="ghost" onClick={() => { setPending(null); void onCancelPower(); setMsg("已取消"); }}>取消倒计时</button> : null}
      </section>
    </div>
  );
}
