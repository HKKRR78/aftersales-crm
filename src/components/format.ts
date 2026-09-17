const countFormatter = new Intl.NumberFormat("zh-CN")
const percentFormatters = new Map<number, Intl.NumberFormat>()
const deltaFormatter = new Intl.NumberFormat("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2, signDisplay: "exceptZero" })
const dateTimeFormatter = new Intl.DateTimeFormat("zh-CN", {
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
})

export function formatCount(value: number | null | undefined) {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—"
  return countFormatter.format(Math.round(value))
}

export function formatPercent(value: number | null, digits = 2) {
  if (value === null || !Number.isFinite(value)) return "—"
  const formatter = percentFormatters.get(digits) ?? new Intl.NumberFormat("zh-CN", {
    style: "percent",
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })
  percentFormatters.set(digits, formatter)
  return formatter.format(value / 100)
}

export function formatDelta(value: number | null) {
  if (value === null || !Number.isFinite(value)) return "—"
  return `${deltaFormatter.format(value)}%`
}

export function formatDateTime(value: string) {
  if (!value) return "待同步"
  const date = new Date(value.replace(" ", "T"))
  return Number.isNaN(date.getTime()) ? "待同步" : dateTimeFormatter.format(date)
}

export function formatSourceSystem(value: string) {
  return value.split("+").filter(Boolean).map((source) => {
    if (source === "ticket_service") return "新工单"
    if (source === "banniu") return "班牛历史"
    return source
  }).join(" + ")
}
