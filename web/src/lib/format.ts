export function fmtTokens(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  const v = Number(n);
  if (Math.abs(v) >= 1e8) return `${(v / 1e8).toFixed(2)}亿`;
  if (Math.abs(v) >= 1e4) return `${(v / 1e4).toFixed(1)}万`;
  return v.toLocaleString("zh-CN");
}

export function fmtCost(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return Math.abs(n) >= 100 ? `$${n.toFixed(0)}` : `$${n.toFixed(2)}`;
}

export function fmtPct(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return `${n.toFixed(2)}%`;
}

export function fmtCount(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return n.toLocaleString("zh-CN");
}

export const STATUS_TEXT: Record<string, string> = {
  ok: "正常",
  empty: "本期无记录",
  unsupported: "来源不支持",
  error: "读取失败",
  loading: "读取中",
  suppressed: "双计已拒绝"
};

export function sourceStatusText(status: string, suppressed: boolean): string {
  if (suppressed) return STATUS_TEXT.suppressed;
  return STATUS_TEXT[status] ?? status;
}

export function dateShort(iso: string): string {
  const [, m, d] = iso.split("-");
  return `${Number(m)}/${Number(d)}`;
}
