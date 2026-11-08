import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  fullyParallel: false,
  reporter: [["list"], ["html", { outputFolder: "playwright-report", open: "never" }]],
  use: {
    baseURL: "http://localhost:4179",
    viewport: { width: 1440, height: 900 },
    trace: "retain-on-failure"
  },
  projects: [
    { name: "edge", use: { ...devices["Desktop Chrome"], channel: "msedge" } }
  ],
  webServer: {
    command: "npx --yes vite preview --port 4179 --strictPort --host 127.0.0.1",
    url: "http://localhost:4179",
    reuseExistingServer: true,
    timeout: 60_000
  }
});
