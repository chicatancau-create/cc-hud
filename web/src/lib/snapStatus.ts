import type { Snapshot } from "../types";

export type SnapBannerTone = "info" | "warn" | "error";

export interface SnapBanner {
  tone: SnapBannerTone;
  /** 大面板文案：与 InsightsView 原有横幅逐字一致 */
  text: string;
  /** 小卡文案：语义相同、字数更少，保证 424x330 里只占一行 */
  short: string;
}

/**
 * 快照整体状态 → 状态横幅。判定口径全项目只有这一处：只看 snap.status。
 *
 * snap.status 由后端 accounting.overall_status() 从各路来源 status 分布汇总
 * （有 error → error；有 ok → ok；有 empty → empty；否则 unsupported），
 * 前端不重新定义状态。因此：
 * - status === "ok" 的真实零值（全 0 但来源正常）不出横幅，数字照原样显示 0；
 * - empty / unsupported / error 才出横幅，说明「数字为 0 不代表真实用量」。
 */
export function snapshotBanner(snap: Pick<Snapshot, "status">): SnapBanner | null {
  switch (snap.status) {
    case "empty":
      return { tone: "info", text: "本期无记录", short: "本期无记录" };
    case "unsupported":
      return { tone: "warn", text: "没有可用来源（不支持）", short: "无可用来源（不支持）" };
    case "error":
      return {
        tone: "error",
        text: "全部来源读取失败：下列数字为 0，不代表真实用量",
        short: "来源读取失败：数字可能为 0，不代表真实用量"
      };
    default:
      return null;
  }
}
