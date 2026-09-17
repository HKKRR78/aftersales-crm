import type { LucideIcon } from "lucide-react"

export function MetricCard({
  label,
  value,
  note,
  tone = "neutral",
  icon: Icon,
}: {
  label: string
  value: string
  note: string
  tone?: "neutral" | "good" | "warning" | "critical"
  icon: LucideIcon
}) {
  return (
    <article className={`metric-card ${tone}`}>
      <span className="metric-icon"><Icon aria-hidden="true" size={19} /></span>
      <div className="metric-label">{label}</div>
      <div className="metric-value">{value}</div>
      <div className="metric-note">{note}</div>
    </article>
  )
}
