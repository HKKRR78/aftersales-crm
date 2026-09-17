import Link from "next/link"

import type { PeriodMode } from "@/src/modules/analytics/types"

export function PeriodSwitcher({ mode, path = "/", entries = [] }: { mode: PeriodMode; path?: string; entries?: Array<[string, string]> }) {
  const href = (period: PeriodMode) => {
    const params = new URLSearchParams({ period })
    entries.forEach(([key, value]) => { if (value) params.set(key, value) })
    return `${path}?${params.toString()}`
  }
  return (
    <div className="period-control">
      <div className="segmented" aria-label="分析周期">
        <Link aria-current={mode === "closed" ? "page" : undefined} className={mode === "closed" ? "selected" : ""} href={href("closed")} title="比较最近 5 个已经完整结束的自然周">完整周趋势</Link>
        <Link aria-current={mode === "progress" ? "page" : undefined} className={mode === "progress" ? "selected" : ""} href={href("progress")} title="本周与上周截取相同已结束自然日进行比较">本周同进度</Link>
      </div>
      <small>{mode === "closed" ? "最近 5 个已结束自然周" : "本周与上周按相同已结束天数比较"}</small>
    </div>
  )
}
