import type {
  AlertLevel,
  ComparisonFields,
  IssueRow,
  SummaryRow,
  WeekMetric,
} from "./types"

export interface AlertThresholds {
  minExcess: number
  minDeltaPp: number
}

export const DEFAULT_ALERT_THRESHOLDS: AlertThresholds = {
  minExcess: 3,
  minDeltaPp: 0.3,
}

export function buildWeekMetrics(
  issueCounts: number[],
  orderCounts: Array<number | null | undefined>,
  salesCounts: Array<number | null | undefined> = issueCounts.map(() => null),
): WeekMetric[] {
  let previousRate: number | null = null
  return issueCounts.map((issues, index) => {
    const orders = orderCounts[index] ?? null
    const sales = salesCounts[index] ?? null
    const rate = orders !== null && orders > 0 ? (issues / orders) * 100 : null
    let wow: number | null = null
    if (rate !== null && previousRate !== null) {
      wow = previousRate === 0 ? (rate > 0 ? Number.POSITIVE_INFINITY : 0) : ((rate - previousRate) / previousRate) * 100
    }
    previousRate = rate
    return { issues, orders, sales, rate, wow }
  })
}

export function comparisonFields(
  weeks: WeekMetric[],
  thresholds: AlertThresholds = DEFAULT_ALERT_THRESHOLDS,
): ComparisonFields {
  const previous = weeks.at(-2)
  const current = weeks.at(-1)
  const previousRate = previous?.rate ?? null
  const currentRate = current?.rate ?? null
  const rateDeltaPp = previousRate !== null && currentRate !== null ? currentRate - previousRate : null
  const expectedIssues = previousRate !== null && current && current.orders !== null ? (previousRate / 100) * current.orders : null
  const excessIssues = expectedIssues !== null && current ? current.issues - expectedIssues : null

  let alertLevel: AlertLevel = "neutral"
  let alertRank = 0
  if (
    rateDeltaPp !== null &&
    excessIssues !== null &&
    excessIssues >= thresholds.minExcess &&
    rateDeltaPp >= thresholds.minDeltaPp
  ) {
    alertLevel = "critical"
    alertRank = 3
  } else if (rateDeltaPp !== null && rateDeltaPp > 0) {
    alertLevel = "warning"
    alertRank = 2
  } else if (rateDeltaPp !== null && rateDeltaPp < 0) {
    alertLevel = "improving"
    alertRank = 1
  }

  return {
    latestIssues: current?.issues ?? 0,
    latestRate: currentRate,
    latestWow: current?.wow ?? null,
    totalIssues: weeks.reduce((sum, week) => sum + week.issues, 0),
    previousIssues: previous?.issues ?? 0,
    previousOrders: previous?.orders ?? null,
    previousSales: previous?.sales ?? null,
    previousRate,
    currentIssues: current?.issues ?? 0,
    currentOrders: current?.orders ?? null,
    currentSales: current?.sales ?? null,
    currentRate,
    rateDeltaPp,
    expectedIssues,
    excessIssues,
    alertLevel,
    alertRank,
  }
}

export function aggregateIssueRows(
  rows: IssueRow[],
  group: (row: IssueRow) => { key: string; label: string; secondary?: string; productId?: string; doudianProductId?: string; detailHref?: string },
  thresholds: AlertThresholds = DEFAULT_ALERT_THRESHOLDS,
): SummaryRow[] {
  const groups = new Map<string, { meta: ReturnType<typeof group>; issues: number[]; orders: Array<number | null>; sales: Array<number | null> }>()

  for (const row of rows) {
    const meta = group(row)
    const existing = groups.get(meta.key) ?? {
      meta,
      issues: Array.from({ length: row.weeks.length }, () => 0),
      orders: Array.from({ length: row.weeks.length }, () => null),
      sales: Array.from({ length: row.weeks.length }, () => null),
    }
    row.weeks.forEach((week, index) => {
      existing.issues[index] += week.issues
      if (week.orders !== null) existing.orders[index] = Math.max(existing.orders[index] ?? 0, week.orders)
      if (week.sales !== null) existing.sales[index] = Math.max(existing.sales[index] ?? 0, week.sales)
    })
    groups.set(meta.key, existing)
  }

  return [...groups.values()]
    .map(({ meta, issues, orders, sales }) => {
      const weeks = buildWeekMetrics(issues, orders, sales)
      return { ...meta, weeks, ...comparisonFields(weeks, thresholds) }
    })
    .sort((a, b) =>
      b.alertRank - a.alertRank ||
      b.latestIssues - a.latestIssues ||
      b.totalIssues - a.totalIssues ||
      a.label.localeCompare(b.label, "zh-CN"),
    )
}

export function sumMetrics(
  rows: IssueRow[],
  orderCounts: Array<number | null>,
  salesCounts: Array<number | null>,
  thresholds = DEFAULT_ALERT_THRESHOLDS,
) {
  const issues = orderCounts.map((_, index) => rows.reduce((sum, row) => sum + (row.weeks[index]?.issues ?? 0), 0))
  return comparisonFields(buildWeekMetrics(issues, orderCounts, salesCounts), thresholds)
}
