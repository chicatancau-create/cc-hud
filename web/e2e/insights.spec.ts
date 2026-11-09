import { expect, test } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

const SHOTS = path.resolve(process.cwd(), "..", "artifacts", "web");
fs.mkdirSync(SHOTS, { recursive: true });

async function shot(page: import("@playwright/test").Page, name: string) {
  await page.screenshot({ path: path.join(SHOTS, `${name}.png`), fullPage: true });
}

test("洞察页：KPI、九路来源卡、模型表", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "上下文洞察" })).toBeVisible();
  await expect(page.locator("article.source")).toHaveCount(11);
  await expect(page.getByTestId("models-table").locator("tbody tr").first()).toBeVisible();
  await expect(page.getByTestId("heatmap").locator("i")).toHaveCount(56);
  await expect(page.getByTestId("timing-card")).toContainText("P50");
  await expect(page.getByTestId("tools-card")).toContainText("Read");
  await shot(page, "insights");
});

test("范围连续切换：最新一次生效且数据条数匹配", async ({ page }) => {
  await page.goto("/");
  const ranges = page.locator(".seg").first();
  await ranges.getByRole("button", { name: "今日" }).click();
  await ranges.getByRole("button", { name: "30 天" }).click();
  await ranges.getByRole("button", { name: "全部" }).click();
  await ranges.getByRole("button", { name: "7 天" }).click();
  await expect(ranges.getByRole("button", { name: "7 天" })).toHaveClass(/on/);
  await expect(page.getByTestId("daily-bars").locator(".bar-col")).toHaveCount(7);
  expect(page.context().pages().length).toBeGreaterThanOrEqual(1);
});

test("小卡与设置互通", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "设置" }).click();
  await expect(page.getByTestId("settings")).toBeVisible();
  await page.getByRole("button", { name: "86%" }).click();
  await expect(page.getByRole("button", { name: "86%" })).toHaveClass(/on/);
  await shot(page, "settings");
  await page.getByRole("button", { name: "小卡" }).click();
  await expect(page.getByTestId("card-view")).toBeVisible();
  await expect(page.getByText("8/11 路正常")).toBeVisible({ timeout: 5000 });
  await shot(page, "card");
  await page.getByRole("button", { name: "展开洞察" }).click();
  await expect(page.getByTestId("insights")).toBeVisible();
});

test("诊断页：守恒表与来源状态表", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "设置" }).click();
  await page.getByRole("button", { name: "回洞察" }).click();
  await page.getByRole("button", { name: "打开诊断" }).click();
  await expect(page.getByTestId("diagnostics")).toBeVisible();
  await expect(page.getByTestId("sources-table").locator("tbody tr")).toHaveCount(11);
  const bad = await page.getByTestId("conservation-table").locator("tr.row-bad").count();
  expect(bad).toBe(0);
  await shot(page, "diagnostics");
});

test("电源必须二次确认", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "设置" }).click();
  const btn = page.getByRole("button", { name: "关机" });
  await btn.click();
  await expect(page.getByTestId("power-msg")).toContainText("再次点击");
  await btn.click();
  await expect(page.getByTestId("power-msg")).toContainText("已执行 shutdown");
});

test("空 / 零 / 不支持 / 错误 四态文案可区分", async ({ page }) => {
  await page.goto("/?scenario=empty");
  await expect(page.getByText("本期无记录").first()).toBeVisible();
  await expect(page.getByText("—").first()).toBeVisible();
  await shot(page, "empty");

  await page.goto("/?scenario=zero");
  await expect(page.getByText("$0.00").first()).toBeVisible();

  await page.goto("/?scenario=unsupported");
  await expect(page.getByText("来源不支持").first()).toBeVisible();
  await shot(page, "unsupported");

  await page.goto("/?scenario=error");
  await expect(page.getByText("读取失败").first()).toBeVisible();
});

test("导出显示 revision", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "导出" }).click();
  await expect(page.getByRole("status")).toContainText("rev");
});

test("刷新页面后不会卡在旧 seq 判定的加载中", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "上下文洞察" })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("heading", { name: "上下文洞察" })).toBeVisible({ timeout: 20000 });
});

test("会话网格：搜索与分页", async ({ page }) => {
  await page.goto("/");
  const grid = page.getByTestId("sessions");
  await expect(grid.locator(".session-card")).toHaveCount(12);
  await page.getByLabel("搜索会话").fill("claude");
  await expect(grid.locator(".session-card").first()).toBeVisible();
  await page.getByLabel("搜索会话").fill("");
  await page.getByRole("button", { name: "下一页" }).click();
  await expect(page.getByText(/第 2\//)).toBeVisible();
});

test("窄视口不出现横向溢出", async ({ page }) => {
  await page.setViewportSize({ width: 420, height: 860 });
  await page.goto("/");
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
  await shot(page, "narrow-420");
});

test("布局密度：KPI 3×2、tiles 顺序与跨列、无横向溢出", async ({ page }) => {
  await page.setViewportSize({ width: 1180, height: 800 });
  await page.goto("/");
  const kpis = page.locator(".kpi");
  await expect(kpis).toHaveCount(6);
  const kb = await kpis.evaluateAll((els) => els.map((e) => {
    const r = e.getBoundingClientRect();
    return { x: r.x, y: Math.round(r.y), w: r.width };
  }));
  expect(new Set(kb.slice(0, 3).map((b) => b.y)).size).toBe(1);
  expect(new Set(kb.slice(3).map((b) => b.y)).size).toBe(1);
  expect(kb[3].y).toBeGreaterThan(kb[0].y);

  const box = async (id: string) => {
    const b = await page.getByTestId(id).boundingBox();
    expect(b).not.toBeNull();
    return b!;
  };
  const heat = await box("tile-heat");
  const tools = await box("tile-tools");
  const models = await box("tile-models");
  const timing = await box("tile-timing");
  const cons = await box("tile-conservation");
  expect(Math.abs(heat.y - tools.y)).toBeLessThanOrEqual(2);
  expect(Math.abs(timing.y - cons.y)).toBeLessThanOrEqual(2);
  expect(timing.y).toBeGreaterThan(models.y);
  expect(Math.abs(models.x - heat.x)).toBeLessThanOrEqual(2);
  expect(models.width).toBeGreaterThanOrEqual(heat.width + tools.width - 4);
  expect(Math.abs(models.y - (heat.y + heat.height))).toBeLessThanOrEqual(16);

  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(0);
  await shot(page, "insights-density");
});
