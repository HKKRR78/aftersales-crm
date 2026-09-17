import type { WeekMetric } from "@/src/modules/analytics/types"

export function TrendBars({ weeks }: { weeks: WeekMetric[] }) {
  const max = Math.max(...weeks.map((week) => week.rate || 0), 0.01)
  return (
    <span className="trend-bars" aria-label={weeks.map((week) => week.rate?.toFixed(2) || "无").join("、")}>
      {weeks.map((week, index) => (
        <i
          className={index === weeks.length - 1 ? "latest" : ""}
          key={index}
          style={{ height: `${Math.max(10, ((week.rate || 0) / max) * 100)}%` }}
        />
      ))}
    </span>
  )
}
