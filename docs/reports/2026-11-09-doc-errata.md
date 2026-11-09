# 文档勘误（2026-11-09）

本文只记录**文档与代码/实机状态的偏差**，不改写已归档的历史报告（`2026-11-07-*`、`2026-11-08-*`）。
历史报告是当时的记录，保留原样；引用它们时以本文为准。

审计基线：`48ffe48` + 19 个未提交路径，实机 `runtime.json`（2026-11-09 11:04 起运行）。

---

## E1 · 「颜色键镂空」→ 实为「圆角窗口区域 + 整窗 alpha」

- **原文**：`README.md:32`「颜色键镂空」；`requirements-checklist.md:17`「镂空实机：`flags=3`（COLORKEY+ALPHA）、`colorkey=0x140E0B`、`bg_pixels=0/379555`」；`:70`「背景镂空实机门禁 已通过」。
- **实际**：`cchud_next/host.py:173` 明写 `self.status["colorkey"] = False   # 不再使用颜色键（见 hollow_mode）`；`:181-194` 的 `use_colorkey(settings)` 分支调的是 `set_round_region(...)`，成功记 `hollow_mode="region"`，否则 `"alpha"`。这一写法**在 HEAD 时刻就已存在**（`git show HEAD:cchud_next/host.py` 同样返回上述行），不是未提交改动引入的。
- **实机佐证**：`artifacts/runtime.json` → `"colorkey": false`、`"hollow_mode": "alpha"`、`"layered": {"flags": 2, "alpha": 244, "colorkey": 0}`（`flags=2` 即 `LWA_ALPHA`，不含 `LWA_COLORKEY`）。
- **`FINAL-hollow3.png` / `flags=3` 的出处**：那是 2026-11-08 00:05 的**颜色键切换前**快照，已过时。
- **现状**：`set_colorkey` 只剩 `host.py:493` 一处，用于镂空**圆点窗**（`_place_dot`），不作用于小卡。
- **已修**：`README.md:32` 改为「圆角窗口区域镂空（小卡）/ 颜色键镂空（仅圆点窗）」。

## E2 · 「五态」只在大面板实现，小卡缺失

- **原文**：`README.md:33`「五态区分」；`requirements-checklist.md:19`「`ok/empty/unsupported/error/loading`；四态文案 Playwright；真实 0 显示 0 ✅」；`:12` 称「卡片五态」已在第二轮前端审查修好。
- **实际**：`web/src/views/InsightsView.tsx:51-57` 有 empty/unsupported/error 三种横幅（含「全部来源读取失败：下列数字为 0，不代表真实用量」）；`web/src/views/CardView.tsx:46-59` 直接用 `kpis/totals` 画 hero，`:79-84` 只印 `{errCount} 路读取异常` 一行**不带状态语义**的文字。全错快照下小卡会把 0 当成真实值展示。
- **性质**：要么是回归，要么是当初的「卡片五态」只做了错误计数那一行。无论哪种，当前代码不支持该结论。
- **已修**：本次给 `CardView` 补状态横幅，判定口径与 `InsightsView` 对齐（详见该提交）。

## E3 · 测试/门禁数字过期（滞后，非虚报）

| 文档 | 当时的数字 | 当前实测 | 差异来源 |
|---|---|---|---|
| `README.md:44`、`requirements-checklist.md:31`、`delivery-index.md:10,72` | pytest **64 passed** | **72 passed** | 未提交的 `tests_py/test_layout_switch.py`（8 个用例） |
| `requirements-checklist.md:32`、`delivery-index.md:73` | Vitest **16 passed** | **19 passed** | `web/src/app.test.tsx`（2）+ `views.test.tsx`（+1） |
| `README.md:46`、`requirements-checklist.md:33`、`delivery-index.md:74` | Playwright **10 passed** | **11 passed** | `web/e2e/insights.spec.ts` 新增密度用例 |
| `final-audit.md:30`、`delivery-index.md:81` | **18/18 门禁** | **19 门禁** | `tools/final_acceptance.py` 新增 `verify_layout_switch` |

这四条都是「文档写于 HEAD 之前，代码在之后又长出用例」，方向是**低估**工作量。`2026-11-08-window-density-report.md` 是唯一数字全对的一份。

## E4 · 托盘图标「可见」未证实

- **原文**：`requirements-checklist.md:68`「托盘像素级 已通过…282 绿像素、ok=true」。
- **实际**：同一份文档自己承认「可见区截图仍无 cc-hud」；`artifacts/windows-verify-tray-uia.json`（见 `gate-transcript.md:187`）记录 `tray_added=True uia_ok=False reason=overflow opened but no cc-hud item`。
- **判据问题**：`ok=true` 来自 `tools/tray_click.py:129-131` 的七个键，而像素/命中类判定被列在 `:135` 的 `informational` 里——设计上就不参与判定。通过依据是固定裁剪框 `[2036,1538,2080,1602]` 内的色相计数，这只能证明**屏幕上那块区域有强调色像素**，不能证明 Shell 在通知区渲染了该图标。
- **结论**：托盘**注册**成立（`tray_added: true`、`tray_hwnd`、`tray_rect` 实机可读）；托盘图标**在通知区可见**属未证实，需换登录会话或人工在「任务栏设置 → 其他系统托盘图标」确认。

## E5 · 圆点「点击恢复」未证实

- **原文**：`final-audit.md:14`「ok=true（隐藏→圆点→恢复）」。
- **实际**：`artifacts/final-acceptance.json` 的 `tray_click` 里 `"cursor_on_dot": false`、`"shown_after_dot_click": false`，只是这两个键被归入 `informational` 才没拉低 `ok`。
- **成立的部分**：圆点窗**创建**成立（`dot_visible_when_hidden: true`、`dot_api: true`、实机 `dot_created: true`、`dot_hwnd: 6423998`）。
- **结论**：圆点存在可证，圆点点按时能恢复窗口**不可证**。

## E6 · `multi_monitor` 的 blocked 不是缺陷

`final_acceptance.py:110` `ok = not failed and not blocked`；本机单显示器触发 `blocked: ["multi_monitor: only 1 display(s)"]` → `ok: false` 并 `return 1`。
这是**工具拒绝把单屏运行当成通过**的诚实行为，不是产品缺陷，也不该被修掉。同理 README:70-71 的「已知环境阻塞」应保留。

---

## 复核命令（任何人都能重跑）

```bash
git show HEAD:cchud_next/host.py | findstr /n "colorkey hollow_mode"     # E1：HEAD 就是 alpha/region
python -c "import json;d=json.load(open('artifacts/runtime.json'));print(d['colorkey'],d['hollow_mode'],d['layered'])"
.venv/Scripts/python.exe -m pytest tests_py -q                            # E3：72
cd web && npm test                                                        # E3：19
python -c "import json;d=json.load(open('artifacts/final-acceptance.json'));print(len(d['gates']),d['failed_gates'],d['blocked'])"
```
