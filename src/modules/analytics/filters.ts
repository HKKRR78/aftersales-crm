import { aggregateIssueRows, buildWeekMetrics } from "./metrics"
import type { AlertLevel, DashboardData, IssueAuditCounts, IssueAuditSummary, IssueRow, ProductWeeklyRow, SummaryRow, WarehouseRow } from "./types"

export interface IssueFilters {
  q: string
  p1: string
  p2: string
  p3: string
  merchantCode: string
  productId: string
  doudianProductId: string
  warehouseCode: string
  alert: AlertLevel | ""
  scope: "operating" | "all"
}

export interface ListFilters {
  q: string
}

export type SearchValues = Record<string, string | undefined>

const alertLevels = new Set<AlertLevel>(["critical", "warning", "improving", "neutral"])

function text(value: string | undefined) {
  return (value || "").trim()
}

export function issueFiltersFromSearch(values: SearchValues): IssueFilters {
  const alert = text(values.alert)
  return {
    q: text(values.q),
    p1: text(values.p1),
    p2: text(values.p2),
    p3: text(values.p3),
    merchantCode: text(values.merchant_code),
    productId: text(values.product_id),
    doudianProductId: text(values.doudian_product_id),
    warehouseCode: text(values.warehouse_code),
    alert: alertLevels.has(alert as AlertLevel) ? alert as AlertLevel : "",
    scope: values.scope === "all" ? "all" : "operating",
  }
}

export function listFiltersFromSearch(values: SearchValues): ListFilters {
  return { q: text(values.q) }
}

export function filterIssueRows(rows: IssueRow[], filters: IssueFilters) {
  const keyword = filters.q.toLocaleLowerCase("zh-CN")
  return rows.filter((row) => {
    if (filters.scope === "operating" && !row.includedInOperating) return false
    if (filters.p1 && row.p1 !== filters.p1) return false
    if (filters.p2 && row.p2 !== filters.p2) return false
    if (filters.p3 && row.p3 !== filters.p3) return false
    if (filters.merchantCode && row.code !== filters.merchantCode) return false
    if (filters.productId && row.productId !== filters.productId) return false
    if (filters.doudianProductId && row.doudianProductId !== filters.doudianProductId) return false
    if (filters.alert && row.alertLevel !== filters.alert) return false
    if (!keyword) return true
    const statusLabel = row.classificationStatus === "included" ? "已纳入" : row.classificationStatus === "excluded" ? "可剔除" : "待归类"
    return [row.sourceSystem, row.code, row.productId, row.doudianProductId, row.name, row.p1, row.p2, row.p3, row.category || "", statusLabel]
      .some((value) => value.toLocaleLowerCase("zh-CN").includes(keyword))
  })
}

function auditCounts(rows: IssueRow[], week: "current" | "previous"): IssueAuditCounts {
  const value = (row: IssueRow) => week === "current" ? row.currentIssues : row.previousIssues
  const sources = new Map<string, number>()
  for (const row of rows) {
    for (const source of row.sourceSystem.split("+").filter(Boolean)) {
      sources.set(source, (sources.get(source) || 0) + value(row))
    }
  }
  return {
    totalIssues: rows.reduce((sum, row) => sum + value(row), 0),
    operatingIssues: rows.filter((row) => row.classificationStatus === "included").reduce((sum, row) => sum + value(row), 0),
    excludedIssues: rows.filter((row) => row.classificationStatus === "excluded").reduce((sum, row) => sum + value(row), 0),
    unclassifiedIssues: rows.filter((row) => row.classificationStatus === "unclassified").reduce((sum, row) => sum + value(row), 0),
    matchedOperatingIssues: rows.filter((row) => row.classificationStatus === "included" && row.code !== "未填").reduce((sum, row) => sum + value(row), 0),
    unmatchedOperatingIssues: rows.filter((row) => row.classificationStatus === "included" && row.code === "未填").reduce((sum, row) => sum + value(row), 0),
    sourceInputs: [...sources.entries()].map(([sourceSystem, issues]) => ({ sourceSystem, issues })).sort((a, b) => a.sourceSystem.localeCompare(b.sourceSystem)),
  }
}

export function summarizeIssueRows(rows: IssueRow[]): IssueAuditSummary {
  return { ...auditCounts(rows, "current"), previous: auditCounts(rows, "previous") }
}

export function filterSummaryRows(rows: SummaryRow[], filters: ListFilters) {
  const keyword = filters.q.toLocaleLowerCase("zh-CN")
  if (!keyword) return rows
  return rows.filter((row) => `${row.label} ${row.secondary || ""} ${row.productId || ""} ${row.doudianProductId || ""}`.toLocaleLowerCase("zh-CN").includes(keyword))
}

export function filterProductWeeklyRows(rows: ProductWeeklyRow[], filters: ListFilters) {
  const keyword = filters.q.toLocaleLowerCase("zh-CN")
  if (!keyword) return rows
  return rows.filter((row) => `${row.label} ${row.secondary} ${row.code}`.toLocaleLowerCase("zh-CN").includes(keyword))
}

export function filterWarehouseRows(rows: WarehouseRow[], filters: ListFilters) {
  const keyword = filters.q.toLocaleLowerCase("zh-CN")
  if (!keyword) return rows
  return rows.filter((row) => `${row.warehouseCode} ${row.warehouseName} ${row.warehouse}`.toLocaleLowerCase("zh-CN").includes(keyword))
}

export function categoryRowsForIssues(data: DashboardData, rows: IssueRow[]) {
  if (rows === data.issueRows) return data.categoryRows
  const totalOrders = data.categoryRows[0]?.weeks.map((week) => week.orders) || data.windows.map(() => null)
  const totalSales = data.categoryRows[0]?.weeks.map((week) => week.sales) || data.windows.map(() => null)
  return aggregateIssueRows(
    rows.map((row) => ({
      ...row,
      weeks: buildWeekMetrics(row.weeks.map((week) => week.issues), totalOrders, totalSales),
    })),
    (row) => ({ key: row.p1, label: row.p1 }),
  )
}

export function productRowsForIssues(data: DashboardData, rows: IssueRow[]) {
  if (rows === data.issueRows) return data.productRows
  const products = new Map(data.productRows.map((row) => [row.key, row]))
  return aggregateIssueRows(
    rows.map((row) => {
      const product = products.get(row.code)
      return {
        ...row,
        weeks: buildWeekMetrics(
          row.weeks.map((week) => week.issues),
          product?.weeks.map((week) => week.orders) || row.weeks.map(() => null),
          product?.weeks.map((week) => week.sales) || row.weeks.map(() => null),
        ),
      }
    }),
    (row) => {
      const product = products.get(row.code)
      return {
        key: row.code,
        label: product?.label || row.name || "未命名产品",
        secondary: product?.secondary || row.code,
        detailHref: `/detail?merchant_code=${encodeURIComponent(row.code)}&period=${data.mode}`,
      }
    },
  )
}

export function issueFilterEntries(filters: IssueFilters) {
  return [
    ["q", filters.q],
    ["p1", filters.p1],
    ["p2", filters.p2],
    ["p3", filters.p3],
    ["merchant_code", filters.merchantCode],
    ["product_id", filters.productId],
    ["doudian_product_id", filters.doudianProductId],
    ["warehouse_code", filters.warehouseCode],
    ["alert", filters.alert],
    ["scope", filters.scope === "all" ? "all" : ""],
  ].filter((entry): entry is [string, string] => Boolean(entry[1]))
}

export function describeIssueFilters(filters: IssueFilters) {
  const labels = issueFilterEntries(filters).map(([key, value]) => {
    const names: Record<string, string> = {
      q: "关键词",
      p1: "一级问题",
      p2: "二级问题",
      p3: "三级问题",
      merchant_code: "商家编码",
      product_id: "售后商品ID",
      doudian_product_id: "抖店商品ID（已确认）",
      warehouse_code: "仓库编码",
      alert: "预警状态",
      scope: "统计口径",
    }
    return `${names[key]}=${value}`
  })
  return labels.length ? labels.join("；") : "全部数据"
}
