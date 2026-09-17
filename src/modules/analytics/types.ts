export type PeriodMode = "closed" | "progress"

export interface DateWindow {
  start: string
  end: string
  label: string
  observeEnd?: string
}

export interface WeekMetric {
  issues: number
  orders: number | null
  sales: number | null
  rate: number | null
  wow: number | null
}

export type AlertLevel = "critical" | "warning" | "improving" | "neutral"

export interface ComparisonFields {
  latestIssues: number
  latestRate: number | null
  latestWow: number | null
  totalIssues: number
  previousIssues: number
  previousOrders: number | null
  previousSales: number | null
  previousRate: number | null
  currentIssues: number
  currentOrders: number | null
  currentSales: number | null
  currentRate: number | null
  rateDeltaPp: number | null
  expectedIssues: number | null
  excessIssues: number | null
  alertLevel: AlertLevel
  alertRank: number
}

export interface IssueRow extends ComparisonFields {
  denominatorKey?: string
  sourceSystem: string
  code: string
  name: string
  productId: string
  doudianProductId: string
  p1: string
  p2: string
  p3: string
  category: "快递问题" | "库房问题" | "买家问题" | "产品问题" | "运营问题" | null
  classificationStatus: "included" | "excluded" | "unclassified"
  includedInOperating: boolean
  weeks: WeekMetric[]
}

export interface IssueAuditCounts {
  totalIssues: number
  operatingIssues: number
  excludedIssues: number
  unclassifiedIssues: number
  matchedOperatingIssues: number
  unmatchedOperatingIssues: number
  sourceInputs: Array<{ sourceSystem: string; issues: number }>
}

export interface IssueAuditSummary extends IssueAuditCounts {
  previous: IssueAuditCounts
}

export interface WarehouseRow extends ComparisonFields {
  warehouse: string
  warehouseCode: string
  warehouseName: string
  weeks: WeekMetric[]
}

export interface SummaryRow extends ComparisonFields {
  key: string
  label: string
  secondary?: string
  productId?: string
  doudianProductId?: string
  detailHref?: string
  weeks: WeekMetric[]
}

export interface DashboardKpis extends ComparisonFields {
  latestAllIssues: number
  unclassifiedIssues: number
  rowCount: number
  redAlerts: number
  deteriorated: number
}

export interface DashboardSource {
  sourceType: "mysql" | "fixture"
  currentPeriod: string
  syncedAt: string
  apiRows: number
  completedDays: number
  periodMode: PeriodMode
  orderThrough?: string
  productOrderThrough?: string
  productOrderState: "fresh" | "partial" | "unavailable"
  productOrderFallbackRows: number
  productOrderUnavailableRows: number
  coverageStart?: string
  coverageEnd?: string
  batchId?: string
  reconciliationStatus?: "pending" | "approved"
}

export interface DashboardData {
  mode: PeriodMode
  windows: DateWindow[]
  weeks: string[]
  kpis: DashboardKpis
  weeklyTotals: WeekMetric[]
  categoryRows: SummaryRow[]
  productRows: SummaryRow[]
  issueRows: IssueRow[]
  warehouseRows: WarehouseRow[]
  source: DashboardSource
}

export interface RawIssueRow {
  denominatorKey?: string
  sourceSystem: string
  code: string
  name: string
  productId: string
  p1: string
  p2: string
  p3: string
  counts: number[]
}

export interface RawWarehouseRow {
  warehouseCode: string
  warehouseName: string
  counts: number[]
}

export interface SourceSnapshot {
  syncedAt: string
  apiRows: number
  coverageStart: string
  coverageEnd: string
  batchId: string
  reconciliationStatus: "pending" | "approved"
}

export interface OrderWatermark {
  statDate: string
  refreshedAt: string
}

export interface ProductWeeklyRow {
  key: string
  code: string
  label: string
  secondary: string
  linkCount: number
  selectedIssues: number
  previousIssues: number
  deltaIssues: number
  weeklyIssues: number[]
  detailHref: string
}

export interface ProductWeeklyReport {
  queryWindows?: DateWindow[]
  batchId?: string
  selectedWeekStart: string
  selectedWeekLabel: string
  previousWeekLabel: string
  selectableWeeks: DateWindow[]
  displayWeeks: DateWindow[]
  rows: ProductWeeklyRow[]
  issueRows: IssueRow[]
  unmatchedIssues: number
  unmatchedDetailHref: string
  syncedAt: string
}
