import { useCallback, useEffect, useRef, useState } from "react";
import { createNativeApi, createStubApi } from "./api/bridge";
import { useSnapshot } from "./state/useSnapshot";
import type { Bootstrap, ExportResult, HudApi, RangeKey, Settings } from "./types";
import { CardView } from "./views/CardView";
import { InsightsView } from "./views/InsightsView";
import { DiagnosticsView } from "./views/DiagnosticsView";
import { SettingsView } from "./views/SettingsView";

type NavLayout = Settings["layout"];

export function App() {
  const [ready, setReady] = useState<{ api: HudApi; mode: "native" | "stub" } | null>(null);
  const [fatal, setFatal] = useState("");

  useEffect(() => {
    let alive = true;
    (async () => {
      // WebView2 注入 pywebview.api 可能晚于 React 首次渲染
      const isFile = window.location.protocol === "file:";
      const attempts = isFile ? 120 : 30;
      for (let i = 0; i < attempts && alive; i++) {
        const native = createNativeApi();
        if (native) {
          setReady({ api: native, mode: "native" });
          return;
        }
        await new Promise((r) => setTimeout(r, 50));
      }
      if (!alive) return;
      if (window.location.protocol === "file:") {
        setFatal("宿主 API 未就绪（pywebview 注入失败），已停止以免用假数据冒充本机统计。");
      } else {
        setReady({ api: createStubApi(), mode: "stub" });
      }
    })();
    return () => { alive = false; };
  }, []);

  if (fatal) {
    return <div className="boot"><div className="fatal"><p>读取失败：{fatal}</p></div></div>;
  }
  if (!ready) return <div className="boot" data-testid="boot">连接宿主…</div>;
  return <AppInner api={ready.api} mode={ready.mode} />;
}

function AppInner({ api, mode }: { api: HudApi; mode: "native" | "stub" }) {
  const [boot, setBoot] = useState<Bootstrap | null>(null);
  const [bootError, setBootError] = useState("");
  const [settings, setSettings] = useState<Settings | null>(null);
  const [range, setRange] = useState<RangeKey>("1d");
  const [exportResult, setExportResult] = useState<ExportResult | null>(null);
  const [notice, setNotice] = useState("");
  const settingsSeq = useRef(0);
  const settingsChain = useRef<Promise<unknown>>(Promise.resolve());
  /** 服务端已确认的范围：只有「最新一次」请求失败时才允许回滚到它 */
  const committedRange = useRef<RangeKey>(range);
  const { snap, loading, refreshing, error, reload } = useSnapshot(api, range);

  useEffect(() => {
    let alive = true;
    api.bootstrap().then((b) => {
      if (!alive) return;
      setBoot(b);
      setSettings(b.settings);
      setRange(b.settings.range);
      committedRange.current = b.settings.range;
    }).catch((e: unknown) => {
      if (!alive) return;
      setBootError(String(e));
    });
    return () => { alive = false; };
  }, [api]);

  useEffect(() => {
    if (!settings) return;
    document.body.dataset.theme = settings.theme;
    document.body.classList.toggle("mode-card", settings.layout === "card");
    document.body.dataset.layout = settings.layout;
  }, [settings]);

  const change = useCallback(async (patch: Partial<Settings>) => {
    const id = ++settingsSeq.current;
    if (patch.range) setRange(patch.range);   // 先切范围，再等设置回包
    const run = settingsChain.current.then(() => api.set_settings(patch));
    settingsChain.current = run.catch(() => undefined);   // 串行写，服务端顺序=点击顺序
    try {
      const next = await run;
      // 串行写在前面已排空，这条回包就是「此刻的服务端真值」，与是否过时无关
      committedRange.current = next.range;
      if (id === settingsSeq.current) {
        setSettings(next);                    // 只认最后一次设置回包
        if (patch.range) setRange(next.range);  // 用服务端权威值重同步乐观范围
      }
      return next;
    } catch (e) {
      // 只有最新一次请求可以改 range：被取代的请求失败时既不回滚、也不打扰用户，
      // 否则两次快速切范围时先发的那次会把 range 滚回旧值且再没人把它同步回来。
      if (id === settingsSeq.current) {
        if (patch.range) setRange(committedRange.current);   // 回滚到服务端最后确认的范围
        setNotice(`设置失败：${e instanceof Error ? e.message : String(e)}`);
      }
      throw e;
    }
  }, [api]);

  /** change() 失败已由 notice 提示，调用点只负责别让 rejection 逃出去（unhandled rejection） */
  const applyQuiet = useCallback((patch: Partial<Settings>) => {
    void change(patch).catch(() => undefined);
  }, [change]);

  const navigate = useCallback((layout: NavLayout) => applyQuiet({ layout }), [applyQuiet]);

  useEffect(() => {
    const m = window.location.hash.match(/scroll=(\d+)/);
    if (!m) return;
    const y = Number(m[1]);
    const t = window.setInterval(() => {
      const node = document.querySelector(".page") as HTMLElement | null;
      if (node) node.scrollTop = y;
      window.scrollTo(0, y);
      document.documentElement.scrollTop = y;
      document.body.scrollTop = y;
    }, 600);
    return () => window.clearInterval(t);
  }, []);

  useEffect(() => {
    if (!boot?.selftest_layout || !snap || !settings) return;
    const map: Record<string, string> = {
      expand: "expand-insights", range7: "range-7d", collapse: "collapse-card",
      diagnostics: "nav-diagnostics", settings: "nav-settings", insights: "nav-insights", card: "nav-card"
    };
    let raf = 0;
    let last = "";
    const send = () => {
      const out: Record<string, [number, number]> = {};
      for (const [key, id] of Object.entries(map)) {
        const el = document.querySelector(`[data-testid="${id}"]`);
        if (el) {
          const r = el.getBoundingClientRect();
          out[key] = [r.left + r.width / 2, r.top + r.height / 2];
        }
      }
      const payload = JSON.stringify(out);
      if (Object.keys(out).length && payload !== last) {
        last = payload;
        void api.window("layout_targets", payload).catch(() => undefined);
      }
    };
    const schedule = () => {
      if (raf) return;
      raf = window.requestAnimationFrame(() => { raf = 0; send(); });
    };
    send();
    // 页内滚动后目标矩形会变，实机验收按真实滚动后重新上报
    document.addEventListener("scroll", schedule, true);
    window.addEventListener("resize", schedule);
    return () => {
      document.removeEventListener("scroll", schedule, true);
      window.removeEventListener("resize", schedule);
      if (raf) window.cancelAnimationFrame(raf);
    };
  }, [api, boot, snap, settings]);

  useEffect(() => {
    if (!window.location.hash.includes("selftest=power")) return;
    if (!boot?.fake_power) return;   // 只有假执行器才允许自动自测
    const t = window.setTimeout(async () => {
      try {
        const unconfirmed = await api.power("shutdown", false);
        const confirmed = await api.power("shutdown", true);
        await api.window("selftest_result", JSON.stringify({ unconfirmed, confirmed }));
      } catch (e) {
        await api.window("selftest_result", "ERR " + String(e));
      }
    }, 3500);
    return () => window.clearTimeout(t);
  }, [api, boot]);

  useEffect(() => {
    if (!window.location.hash.includes("selftest=export")) return;
    const t = window.setTimeout(async () => {
      try {
        const r = await api.export_json(range);
        await api.window("selftest_result", JSON.stringify(r));
      } catch (e) {
        await api.window("selftest_result", "ERR " + String(e));
      }
    }, 4000);
    return () => window.clearTimeout(t);
  }, [api, range]);

  useEffect(() => {
    if (!window.location.hash.includes("selftest=hide")) return;
    const t = window.setTimeout(() => void api.window("hide"), 1500);
    return () => window.clearTimeout(t);
  }, [api]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") applyQuiet({ layout: "card" });
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [applyQuiet]);

  const doExport = useCallback(async () => {
    try {
      const r = await api.export_json(range);
      setExportResult(r);
      setNotice(`已导出 ${r.path}（${r.bytes} B，rev ${r.revision}）`);
    } catch (e) {
      setNotice(`导出失败：${e instanceof Error ? e.message : String(e)}`);
    }
  }, [api, range]);

  if (bootError && !boot) {
    return (
      <div className="boot" data-testid="boot-error">
        <div className="fatal">
          <p>读取失败：{bootError}</p>
          <button className="ghost" onClick={() => window.location.reload()}>重试</button>
        </div>
      </div>
    );
  }
  if (!boot || !settings) {
    return <div className="boot" data-testid="boot">正在读取本地用量…</div>;
  }

  if (!snap) {
    return (
      <div className="boot" data-testid="loading">
        {error ? (
          <div className="fatal">
            <p>读取失败：{error}</p>
            <button className="ghost" onClick={reload}>重试</button>
          </div>
        ) : ("读取中…")}
        <span className="dim">宿主：{mode === "native" ? "WebView2" : "浏览器桩"}</span>
      </div>
    );
  }

  const layout = settings.layout;
  return (
    <div className={`app layout-${layout}`} data-mode={mode}>
      {notice ? <div className="toast" role="status" onClick={() => setNotice("")}>{notice}</div> : null}
      {error ? <div className="banner" data-tone="error" role="status">刷新失败：{error}</div> : null}
      {loading ? <div className="banner" role="status">加载中…</div> : null}

      {layout === "card" && (
        <CardView snap={snap} range={range} refreshing={refreshing}
          onRange={(r) => applyQuiet({ range: r })}
          onExpand={() => navigate("insights")}
          onSettings={() => navigate("settings")} />
      )}
      {layout === "insights" && (
        <InsightsView snap={snap} range={range} refreshing={refreshing}
          onRange={(r) => applyQuiet({ range: r })}
          onRefresh={reload} onExport={() => void doExport()}
          onNavigate={(l) => navigate(l as NavLayout)} />
      )}
      {layout === "diagnostics" && (
        <DiagnosticsView snap={snap} settings={settings} range={range}
          exportResult={exportResult} onExport={() => void doExport()}
          onNavigate={(l) => navigate(l as NavLayout)} />
      )}
      {layout === "settings" && (
        <SettingsView settings={settings} version={boot.version} onChange={(p) => applyQuiet(p)}
          onExport={() => void doExport()}
          onPower={(action, confirmed) => api.power(action, confirmed)}
          onCancelPower={() => api.cancel_power()}
          onNavigate={(l) => navigate(l as NavLayout)} />
      )}
    </div>
  );
}
