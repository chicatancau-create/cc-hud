import type { RangeKey, Snapshot } from "../types";

/** 客户端快照缓存：容量有上限，供诊断页展示命中/容量。 */
export class SnapshotCache {
  private map = new Map<string, Snapshot>();
  hits = 0;
  misses = 0;
  constructor(public capacity = 6) {}

  get(range: RangeKey, revision: number): Snapshot | undefined {
    const key = `${range}:${revision}`;
    const hit = this.map.get(key);
    if (hit) {
      this.hits++;
      this.map.delete(key);
      this.map.set(key, hit);
      return hit;
    }
    this.misses++;
    return undefined;
  }

  set(range: RangeKey, snap: Snapshot): void {
    const key = `${range}:${snap.revision}`;
    this.map.delete(key);
    this.map.set(key, snap);
    while (this.map.size > this.capacity) {
      const oldest = this.map.keys().next().value;
      if (oldest === undefined) break;
      this.map.delete(oldest);
    }
  }

  get size(): number {
    return this.map.size;
  }
}

/** latest-wins：只接受 seq 不小于已应用值的结果，乱序旧响应直接丢弃。 */
export function acceptSnapshot(
  currentSeq: number,
  incoming: Snapshot,
  expectedRange?: Snapshot["range"]
): { accepted: boolean; seq: number } {
  if (incoming.stale) return { accepted: false, seq: currentSeq };
  // 切范围时旧请求可能晚到；seq 全局单调，但范围必须匹配
  if (expectedRange && incoming.range !== expectedRange) return { accepted: false, seq: currentSeq };
  if (incoming.seq < currentSeq) return { accepted: false, seq: currentSeq };
  return { accepted: true, seq: incoming.seq };
}
