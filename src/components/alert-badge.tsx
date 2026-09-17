import type { AlertLevel } from "@/src/modules/analytics/types"

const labels: Record<AlertLevel, string> = {
  critical: "重点预警",
  warning: "正在上升",
  improving: "有所改善",
  neutral: "平稳/待观察",
}

export function AlertBadge({ level }: { level: AlertLevel }) {
  return <span className={`alert-badge ${level}`}><i aria-hidden="true" />{labels[level]}</span>
}
