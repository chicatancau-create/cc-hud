import { useCallback, useEffect, useRef, useState } from "react";
import type { HudApi, RangeKey, Snapshot } from "../types";
import { SnapshotCache, acceptSnapshot } from "./snapshotCache";

export interface SnapshotState {
  snap: Snapshot | null;
  loading: boolean;
  refreshing: boolean;
  error: string | null;
  reload: () => void;
  cache: SnapshotCache;
}

export function useSnapshot(api: HudApi, range: RangeKey): SnapshotState {
  const [snap, setSnap] = useState<Snapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const seqRef = useRef<number>(Date.now());  // 跨页面重载仍单调，避免宿主 last_seq 判定为旧请求
  const applied = useRef(0);
  const cacheRef = useRef(new SnapshotCache(6));
  const lastRev = useRef<Partial<Record<RangeKey, number>>>({});

  const load = useCallback(async () => {
    const my = ++seqRef.current;
    setRefreshing(true);
    try {
      const incoming = await api.snapshot(range, my);
      const verdict = acceptSnapshot(applied.current, incoming, range);
      if (!verdict.accepted) {
        if (my === seqRef.current) {
          setRefreshing(false);
          setLoading(false);
        }
        return;
      }
      applied.current = verdict.seq;
      lastRev.current[range] = incoming.revision;
      cacheRef.current.set(range, incoming);
      setSnap(incoming);
      setError(null);
      setLoading(false);
    } catch (e) {
      if (my === seqRef.current) {
        setError(e instanceof Error ? e.message : String(e));
        setLoading(false);
      }
    } finally {
      if (my === seqRef.current) setRefreshing(false);
    }
  }, [api, range]);

  useEffect(() => {
    // seq 必须全局单调：桥接按全局 last_seq 判 stale，切范围把 seq 归零会被误判为旧响应
    setLoading(true);
    setError(null);
    const rev = lastRev.current[range];
    const cached = rev === undefined ? undefined : cacheRef.current.get(range, rev);
    if (cached) {
      setSnap(cached);
      setLoading(false);
    } else {
      setSnap(null);
    }
    void load();
    const timer = window.setInterval(() => void load(), 30_000);
    return () => window.clearInterval(timer);
  }, [range, load]);

  return { snap, loading, refreshing, error, reload: () => void load(), cache: cacheRef.current };
}
