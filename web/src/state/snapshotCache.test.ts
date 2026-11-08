import { describe, expect, it } from "vitest";
import { SnapshotCache, acceptSnapshot } from "./snapshotCache";
import { stubSnapshot } from "../api/stub";

describe("latest-wins", () => {
  it("拒绝乱序旧响应与 stale", () => {
    expect(acceptSnapshot(5, { ...stubSnapshot("1d", 4) }).accepted).toBe(false);
    expect(acceptSnapshot(5, { ...stubSnapshot("1d", 5) }).accepted).toBe(true);
    expect(acceptSnapshot(5, { ...stubSnapshot("1d", 9), stale: true }).accepted).toBe(false);
    expect(acceptSnapshot(2, stubSnapshot("1d", 3), "7d").accepted).toBe(false);
  });
});

describe("SnapshotCache", () => {
  it("容量上限并淘汰最旧", () => {
    const cache = new SnapshotCache(2);
    cache.set("1d", { ...stubSnapshot("1d", 1), revision: 1 });
    cache.set("7d", { ...stubSnapshot("7d", 1), revision: 2 });
    cache.set("30d", { ...stubSnapshot("30d", 1), revision: 3 });
    expect(cache.size).toBe(2);
    expect(cache.get("1d", 1)).toBeUndefined();
    expect(cache.get("7d", 2)).toBeTruthy();
    expect(cache.hits).toBe(1);
  });

  it("同键覆盖不增长", () => {
    const cache = new SnapshotCache(2);
    cache.set("1d", { ...stubSnapshot("1d", 1), revision: 1 });
    cache.set("1d", { ...stubSnapshot("1d", 2), revision: 1 });
    expect(cache.size).toBe(1);
  });
});
