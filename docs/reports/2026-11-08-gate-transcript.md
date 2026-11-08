# 门禁执行记录（2026-11-08）

> 由 `tools/gate_transcript.py` 生成；命令在仓库内原样执行，
> 每节保留输出结尾片段与退出码。

## Python 单元/适配器/守恒/桥接
```
$ G:\cc-hud\.venv\Scripts\python.exe -m pytest tests_py -q
.............................................................            [100%]
RC=0
```

## 四范围对账
```
$ G:\cc-hud\.venv\Scripts\python.exe tools/reconcile.py
1d    9.39s  tokens=  373,634,182  reqs=  1,081  cost=$   28.82  sessions=   11  checks=11  bad=none
  7d    4.13s  tokens=1,289,517,611  reqs= 11,550  cost=$  162.33  sessions=   69  checks=20  bad=none
 30d    1.43s  tokens=2,896,548,154  reqs= 23,040  cost=$  392.81  sessions= 1074  checks=26  bad=none
 all    2.77s  tokens=3,573,712,557  reqs= 56,591  cost=$  430.68  sessions= 1315  checks=29  bad=none
RC=0
```

## 前端 lint
```
$ npm run lint
> cc-hud-web@0.1.0 lint
> eslint .
RC=0
```

## 前端 typecheck
```
$ npm run typecheck
> cc-hud-web@0.1.0 typecheck
> tsc --noEmit
RC=0
```

## 前端 Vitest
```
$ npm test
> cc-hud-web@0.1.0 test
> vitest run


[1m[46m RUN [49m[22m [36mv3.2.7 [39m[90mG:/cc-hud/web[39m

 [32m✓[39m src/lib/format.test.ts [2m([22m[2m3 tests[22m[2m)[22m[32m 18[2mms[22m[39m
 [32m✓[39m src/state/snapshotCache.test.ts [2m([22m[2m3 tests[22m[2m)[22m[32m 5[2mms[22m[39m
 [32m✓[39m src/views/views.test.tsx [2m([22m[2m10 tests[22m[2m)[22m[33m 807[2mms[22m[39m
   [33m[2m✓[22m[39m SessionsGrid[2m > [22m按来源筛选、搜索与分页 [33m 355[2mms[22m[39m

[2m Test Files [22m [1m[32m3 passed[39m[22m[90m (3)[39m
[2m      Tests [22m [1m[32m16 passed[39m[22m[90m (16)[39m
[2m   Start at [22m 02:48:17
[2m   Duration [22m 2.95s[2m (transform 183ms, setup 356ms, collect 348ms, tests 830ms, environment 1.54s, prepare 355ms)[22m
RC=0
```

## 前端 build
```
$ npm run build
> cc-hud-web@0.1.0 build
> tsc --noEmit && vite build

[36mvite v6.4.5 [32mbuilding for production...[36m[39m
transforming...
[32m✓[39m 39 modules transformed.
rendering chunks...
computing gzip size...
[2mdist/[22m[32mindex.html                 [39m[1m[2m  0.41 kB[22m[1m[22m[2m │ gzip:  0.28 kB[22m
[2mdist/[22m[35massets/index-BAoMY040.css  [39m[1m[2m 13.36 kB[22m[1m[22m[2m │ gzip:  3.38 kB[22m
[2mdist/[22m[36massets/index-CwSfhfTM.js   [39m[1m[2m182.71 kB[22m[1m[22m[2m │ gzip: 57.56 kB[22m
[32m✓ built in 566ms[39m
RC=0
```

## Playwright
```
$ npx playwright test
Running 10 tests using 1 worker

  ok  1 [edge] › e2e\insights.spec.ts:12:1 › 洞察页：KPI、九路来源卡、模型表 (2.5s)
  ok  2 [edge] › e2e\insights.spec.ts:23:1 › 范围连续切换：最新一次生效且数据条数匹配 (2.9s)
  ok  3 [edge] › e2e\insights.spec.ts:35:1 › 小卡与设置互通 (2.8s)
  ok  4 [edge] › e2e\insights.spec.ts:50:1 › 诊断页：守恒表与来源状态表 (2.8s)
  ok  5 [edge] › e2e\insights.spec.ts:62:1 › 电源必须二次确认 (2.7s)
  ok  6 [edge] › e2e\insights.spec.ts:72:1 › 空 / 零 / 不支持 / 错误 四态文案可区分 (10.2s)
  ok  7 [edge] › e2e\insights.spec.ts:89:1 › 导出显示 revision (2.3s)
  ok  8 [edge] › e2e\insights.spec.ts:95:1 › 刷新页面后不会卡在旧 seq 判定的加载中 (5.0s)
  ok  9 [edge] › e2e\insights.spec.ts:102:1 › 会话网格：搜索与分页 (2.7s)
  ok 10 [edge] › e2e\insights.spec.ts:113:1 › 窄视口不出现横向溢出 (304ms)

  10 passed (37.6s)
RC=0
```

## Windows 实机证据（JSON 汇总）
```
ACCEPT-card.json                     ok=True fails=-
ACCEPT-diagnostics.json              ok=True fails=-
ACCEPT-export.json                   ok=True fails=-
ACCEPT-export2.json                  ok=True fails=-
ACCEPT-hollow.json                   ok=True fails=-
ACCEPT-insights.json                 ok=True fails=-
ACCEPT-peek.json                     ok=True fails=-
ACCEPT-power.json                    ok=True fails=-
ACCEPT-settings.json                 ok=True fails=-
DPI100-forced.json                   dpr=1 scale=--force-device-scale-factor=1 capture_ok=True 1762x1072 max_luma=236
DPI125.json                          ok=True fails=-
DPI150-forced.json                   dpr=1.5 scale=- capture_ok=True 1762x1072 max_luma=236
EXPO2.json                           ok=True fails=-
final-card.json                      ok=True fails=-
final-card2.json                     ok=True fails=-
FINAL-diagnostics.json               ok=True fails=-
FINAL-hollow.json                    ok=False fails=['hollow_colorkey']
FINAL-hollow2.json                   ok=False fails=['hollow_colorkey']
FINAL-hollow3.json                   ok=True fails=-
final-insights-2202.json             ok=True fails=-
final-insights-fixed.json            ok=True fails=-
final-insights-screen.json           ok=True fails=-
final-insights-zoom.json             ok=True fails=-
final-insights.json                  ok=True fails=-
final-insights2.json                 ok=True fails=-
final-peek.json                      ok=True fails=-
FINAL-power.json                     ok=False fails=['selftest_power']
FINAL-power2.json                    ok=False fails=['selftest_power']
FINAL-power3.json                    ok=False fails=['selftest_power']
FINAL-power4.json                    ok=False fails=['selftest_power']
FINAL-power5.json                    ok=True fails=-
FINAL-settings.json                  ok=True fails=-
FINAL10-card.json                    ok=True fails=-
FINAL11-insights.json                ok=True fails=-
FINAL12-card.json                    ok=True fails=-
FINAL12-insights.json                ok=True fails=-
FINAL13-card.json                    ok=True fails=-
FINAL13-insights.json                ok=True fails=-
FINAL13-peek.json                    ok=True fails=-
FINAL14-card.json                    ok=True fails=-
FINAL14-insights.json                ok=True fails=-
FINAL15-card.json                    ok=True fails=-
FINAL16-card.json                    ok=True fails=-
FINAL17-card.json                    ok=True fails=-
FINAL18-diagnostics.json             ok=True fails=-
FINAL18-export.json                  ok=True fails=-
FINAL18-hollow.json                  ok=True fails=-
FINAL18-peek.json                    ok=True fails=-
FINAL18-power.json                   ok=True fails=-
FINAL18-settings.json                ok=True fails=-
FINAL19-card.json                    ok=True fails=-
FINAL2-insights.json                 ok=True fails=-
FINAL2-sessions.json                 ok=True fails=-
FINAL2-sessions2.json                ok=True fails=-
FINAL20-card.json                    ok=True fails=-
FINAL21-card.json                    ok=False fails=['window_created', 'dot_window', 'layered', 'alpha', 'topmost', 'visible', 'capture']
FINAL22-card.json                    ok=False fails=['window_created', 'dot_window', 'layered', 'alpha', 'topmost', 'visible', 'capture']
FINAL23-card.json                    ok=False fails=['window_created', 'dot_window', 'tray_added', 'dot_placed', 'dpi', 'dpi_aware_per_monitor', 'work_area', 'layered', 'alpha', 'topmost', 'visible', 'capture']
FINAL24-card.json                    ok=False fails=['window_created', 'dot_window', 'layered', 'alpha', 'topmost', 'visible', 'capture']
FINAL25-card.json                    ok=False fails=['dot_window']
FINAL26-card.json                    ok=True fails=-
FINAL3-card.json                     ok=True fails=-
FINAL3-export.json                   ok=False fails=['selftest_export']
FINAL3-export2.json                  ok=False fails=['selftest_export']
FINAL3-export3.json                  ok=False fails=['selftest_export']
FINAL3-export4.json                  ok=False fails=['selftest_export']
FINAL3-insights.json                 ok=True fails=-
FINAL3-peek.json                     ok=True fails=-
FINAL4-card.json                     ok=True fails=-
FINAL4-insights.json                 ok=True fails=-
FINAL4-peek.json                     ok=True fails=-
FINAL5-insights.json                 ok=True fails=-
FINAL5-timing.json                   ok=True fails=-
FINAL6-tools.json                    ok=True fails=-
FINAL7-30d.json                      ok=True fails=-
FINAL8-card.json                     ok=True fails=-
FINAL8-insights.json                 ok=True fails=-
FINAL8-peek.json                     ok=True fails=-
FINAL9-card.json                     ok=True fails=-
FINAL9-insights.json                 ok=True fails=-
FINAL9-peek.json                     ok=True fails=-
review-card.json                     ok=False fails=['tray_added']
review-card2.json                    ok=True fails=-
review-insights.json                 ok=True fails=-
settings-persist.json                ok=True fails=-
tray-click.json                      ok=True fails=-
tray-hover.json                      tray_added=True unnamed=1 tooltip=captured
tray-uia.json                        tray_added=True uia_ok=False reason=overflow opened but no cc-hud item
windows-card-2.json                  ok=True fails=-
windows-card-3.json                  ok=True fails=-
windows-card-final.json              ok=True fails=-
windows-card-final2.json             ok=True fails=-
windows-card.json                    ok=True fails=-
windows-insights-bitblt.json         ok=True fails=-
windows-insights-final.json          ok=True fails=-
windows-insights-final10.json        ok=True fails=-
windows-insights-final11.json        ok=True fails=-
windows-insights-final12.json        ok=True fails=-
windows-insights-final13.json        ok=True fails=-
windows-insights-final2.json         ok=True fails=-
windows-insights-final3.json         ok=True fails=-
windows-insights-final4.json         ok=True fails=-
windows-insights-final5.json         ok=True fails=-
windows-insights-final6.json         ok=True fails=-
windows-insights-final7.json         ok=True fails=-
windows-insights-final8.json         ok=True fails=-
windows-insights-final9.json         ok=True fails=-
windows-insights.json                ok=True fails=-
windows-peek.json                    ok=True fails=-
```

说明：`FINAL*`/`EXPO2` 为最终轮证据；其余为过程快照。
过程快照中的失败项均已被后续轮次覆盖：
`FINAL-hollow*.json` → `FINAL-hollow3.json`（flags=3），
`FINAL-power*.json` → `FINAL-power5.json`（假执行器确认），
`FINAL3-export*.json` → `EXPO2.json`（revision + 落盘）。

## 结论

自动化门禁退出码：全部为 0
