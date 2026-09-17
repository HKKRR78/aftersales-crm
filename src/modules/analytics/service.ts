import "server-only"

import { addDays, parseISO } from "date-fns"
import { cacheLife, cacheTag } from "next/cache"

import { completedDays, productReportSelection, shanghaiToday, windowsFor } from "./date-windows"
import { isDevFixtureMode } from "./dev-mode"
import { aggregateIssueRows, buildWeekMetrics, comparisonFields, sumMetrics } from "./metrics"
import { orderSeries, resolveProductOrders } from "./product-orders"
import { buildProductWeeklyRows } from "./product-weekly"
import {
  reportBatch,
  type ReportBatch,
  confirmedDoudianProductIds,
  createdIssueRows,
  earliestCreatedIssueDate,
  groupedOrderCounts,
  groupedSalesCounts,
  issueRows,
  latestCompleteOrderDay,
  latestProductOrderDay,
  sourceSnapshot,
  totalOrderCounts,
  totalSalesCounts,
  warehouseIssueRows,
} from "./repository"
import type { DashboardData, IssueRow, PeriodMode, ProductWeeklyReport, RawIssueRow, WarehouseRow } from "./types"
import { classifyIssue, exclusionRuleIndex } from "@/src/modules/problem-rules/classifier"
import type { ExclusionRule } from "@/src/modules/problem-rules/types"

function thresholds() {
  return {
    minExcess: Number(process.env.AFTERSALES_PROGRESS_ALERT_MIN_EXCESS || 3),
    minDeltaPp: Number(process.env.AFTERSALES_PROGRESS_ALERT_MIN_DELTA_PP || 0.3),
  }
}

function hydratedIssueRows(
  rows: RawIssueRow[],
  windows: ReturnType<typeof windowsFor>,
  doudianIds: Set<string>,
  seriesFor: (row: RawIssueRow) => { orders: Array<number | null>; sales: Array<number | null> },
  rules: ReturnType<typeof exclusionRuleIndex>,
) {
  const alertThresholds = thresholds()
  return rows.map((row): IssueRow => {
    const classified = classifyIssue(row, rules)
    const series = seriesFor(row)
    const weeks = buildWeekMetrics(row.counts, series.orders, series.sales)
    return {
      ...classified,
      doudianProductId: doudianIds.has(row.productId) ? row.productId : "",
      weeks,
      ...comparisonFields(weeks, alertThresholds),
    }
  })
}

export async function analysisWindows(mode: PeriodMode, today: Date, batch: ReportBatch) {
  if (batch.verification === "candidate" || (!batch.completeThrough && batch.verificationKind !== "full")) {
    return { orderWatermark: null, windows: windowsFor(mode, parseISO(batch.end)) }
  }
  const orderWatermark = mode === "progress" ? await latestCompleteOrderDay(batch) : null
  const analysisToday = orderWatermark ? addDays(parseISO(orderWatermark.statDate), 1) : today
  return { orderWatermark, windows: windowsFor(mode, analysisToday) }
}

export async function loadDashboard(mode: PeriodMode, today = shanghaiToday(), requestedBatch?: ReportBatch): Promise<DashboardData> {
  if (isDevFixtureMode()) {
    const { loadDevFixtureDashboard } = await import("./dev-fixture")
    return loadDevFixtureDashboard(mode, today)
  }
  return dashboardForBatch(mode, today, requestedBatch ?? await reportBatch())
}

async function dashboardForBatch(mode: PeriodMode, today: Date, batch: ReportBatch): Promise<DashboardData> {
  "use cache"
  cacheLife({ stale: 300, revalidate: 60, expire: 3600 })
  cacheTag("aftersales-dashboard")

  if (isDevFixtureMode()) {
    const { loadDevFixtureDashboard } = await import("./dev-fixture")
    return loadDevFixtureDashboard(mode, today)
  }
  const { orderWatermark, windows } = await analysisWindows(mode, today, batch)
  const alertThresholds = thresholds()

  const totalOrdersPromise = totalOrderCounts(windows, mode, batch)
  const [rawIssues, rawWarehouses, merchantOrders, platformOrders, merchantSales, platformSales, warehouseOrders, warehouseSales, doudianIds, source, totalOrders, totalSales, productWatermark, exclusionRules] =
    await Promise.all([
      issueRows(windows, mode, "", batch),
      warehouseIssueRows(windows, mode, batch),
      groupedOrderCounts(windows, mode, "merchant_code", batch),
      groupedOrderCounts(windows, mode, "aftersales_product_id", batch),
      groupedSalesCounts(windows, mode, "merchant_code", batch),
      groupedSalesCounts(windows, mode, "aftersales_product_id", batch),
      groupedOrderCounts(windows, mode, "warehouse", batch),
      groupedSalesCounts(windows, mode, "warehouse", batch),
      confirmedDoudianProductIds(batch!),
      sourceSnapshot(batch!),
      totalOrdersPromise,
      totalSalesCounts(windows, mode, batch),
      latestProductOrderDay(batch),
      Promise.resolve(batch!.rules),
    ])

  const productOrderFallbackRows = 0
  const issueData = hydratedIssueRows(rawIssues, windows, doudianIds, (row) => {
    const resolved = resolveProductOrders({ row, length: windows.length, platformOrders, platformSales })
    return { orders: resolved.orders, sales: resolved.sales }
  }, exclusionRuleIndex(exclusionRules))
  const operatingIssueData = issueData.filter((row) => row.includedInOperating)

  const warehouseData: WarehouseRow[] = rawWarehouses
    .map((row) => {
      const orders = row.warehouseName
        ? warehouseOrders.get(row.warehouseCode) || warehouseOrders.get("") || Array.from({ length: windows.length }, () => null)
        : Array.from({ length: windows.length }, () => null)
      const sales = row.warehouseName
        ? warehouseSales.get(row.warehouseCode) || warehouseSales.get("") || Array.from({ length: windows.length }, () => null)
        : Array.from({ length: windows.length }, () => null)
      const weeks = buildWeekMetrics(row.counts, orders, sales)
      return {
        ...row,
        warehouse: row.warehouseName ? `${row.warehouseCode} / ${row.warehouseName}` : row.warehouseCode,
        weeks,
        ...comparisonFields(weeks, alertThresholds),
      }
    })
    .sort((a, b) => b.alertRank - a.alertRank || b.latestIssues - a.latestIssues || a.warehouse.localeCompare(b.warehouse, "zh-CN"))

  const categoryRows = aggregateIssueRows(
    operatingIssueData.map((row) => ({ ...row, weeks: buildWeekMetrics(row.weeks.map((week) => week.issues), totalOrders, totalSales) })),
    (row) => ({ key: row.p1, label: row.p1 }),
    alertThresholds,
  )
  const productRows = productRowsByCode(operatingIssueData, merchantOrders, merchantSales, alertThresholds, mode)
  const productOrderUnavailableRows = productRows.filter(row => row.weeks.some(week => week.orders === null || week.sales === null)).length
  const totals = sumMetrics(operatingIssueData, totalOrders, totalSales, alertThresholds)
  const weeklyTotals = buildWeekMetrics(
    windows.map((_, index) => operatingIssueData.reduce((sum, row) => sum + (row.weeks[index]?.issues ?? 0), 0)),
    totalOrders,
    totalSales,
  )

  issueData.sort((a, b) =>
    b.alertRank - a.alertRank ||
    b.latestIssues - a.latestIssues ||
    b.totalIssues - a.totalIssues ||
    a.code.localeCompare(b.code, "zh-CN"),
  )

  return {
    mode,
    windows,
    weeks: windows.map((window) => window.label),
    kpis: {
      ...totals,
      latestAllIssues: issueData.reduce((sum, row) => sum + row.currentIssues, 0),
      unclassifiedIssues: issueData.filter((row) => row.classificationStatus === "unclassified").reduce((sum, row) => sum + row.currentIssues, 0),
      rowCount: operatingIssueData.length,
      redAlerts: operatingIssueData.filter((row) => row.alertLevel === "critical").length,
      deteriorated: operatingIssueData.filter((row) => (row.rateDeltaPp ?? 0) > 0).length,
    },
    weeklyTotals,
    categoryRows,
    productRows: productRows.map(row => ({ ...row, detailHref: `${row.detailHref}&batch=${batch.id}` })),
    issueRows: issueData,
    warehouseRows: warehouseData,
    source: {
      sourceType: "mysql",
      currentPeriod: windows.at(-1)?.label || "",
      syncedAt: source.syncedAt,
      apiRows: source.apiRows,
      completedDays: completedDays(windows.at(-1)!),
      periodMode: mode,
      orderThrough: orderWatermark?.statDate,
      productOrderThrough: productWatermark?.statDate,
      productOrderState: productOrderUnavailableRows === 0 && productWatermark ? "fresh" : productWatermark ? "partial" : "unavailable",
      productOrderFallbackRows,
      productOrderUnavailableRows,
      coverageStart: source.coverageStart,
      coverageEnd: source.coverageEnd,
      batchId: source.batchId,
      reconciliationStatus: source.reconciliationStatus,
    },
  }
}

function productRowsByCode(
  rows: IssueRow[],
  merchantOrders: Map<string, Array<number | null>>,
  merchantSales: Map<string, Array<number | null>>,
  alertThresholds: ReturnType<typeof thresholds>,
  mode: PeriodMode,
) {
  const groups = new Map<string, { name: string; issues: number[]; linkIds: Set<string> }>()
  for (const row of rows) {
    const group = groups.get(row.code) ?? {
      name: row.name || "未命名产品",
      issues: row.weeks.map(() => 0),
      linkIds: new Set<string>(),
    }
    row.weeks.forEach((week, index) => { group.issues[index] += week.issues })
    if (row.productId) group.linkIds.add(row.productId)
    if ((row.name || "").length > group.name.length) group.name = row.name
    groups.set(row.code, group)
  }
  return [...groups.entries()].filter(([code]) => code !== "未填").map(([code, group]) => {
    const orders = orderSeries(code, merchantOrders) ?? group.issues.map(() => null)
    const sales = orderSeries(code, merchantSales) ?? group.issues.map(() => null)
    const weeks = buildWeekMetrics(group.issues, orders, sales)
    return {
      key: code,
      label: group.name,
      secondary: `${code} · ${group.linkIds.size} 个链接`,
      productId: "",
      doudianProductId: "",
      detailHref: `/detail?merchant_code=${encodeURIComponent(code)}&period=${mode}`,
      weeks,
      ...comparisonFields(weeks, alertThresholds),
    }
  }).sort((a, b) => b.alertRank - a.alertRank || b.latestIssues - a.latestIssues || a.label.localeCompare(b.label, "zh-CN"))
}

export async function loadWarehouseIssueRows(
  mode: PeriodMode,
  warehouseCode: string,
  warehouseName: string,
  today = shanghaiToday(),
  requestedBatch?: ReportBatch,
): Promise<IssueRow[]> {
  return warehouseForBatch(mode, warehouseCode, warehouseName, today, isDevFixtureMode() ? null : requestedBatch ?? await reportBatch())
}

async function warehouseForBatch(mode: PeriodMode, warehouseCode: string, warehouseName: string, today: Date, batch: ReportBatch | null): Promise<IssueRow[]> {
  "use cache"
  cacheLife({ stale: 300, revalidate: 60, expire: 3600 })
  cacheTag("aftersales-dashboard")

  if (isDevFixtureMode()) {
    const { loadDevFixtureDashboard } = await import("./dev-fixture")
    const fixture = loadDevFixtureDashboard(mode, today)
    const target = Number(warehouseCode.replace(/\D/g, ""))
    return fixture.issueRows.filter((row) => {
      const code = Number(row.code.replace(/\D/g, ""))
      return ((code - 1) % fixture.warehouseRows.length) + 1 === target
    })
  }

  if (!batch) throw new Error("Report batch is required")
  const { windows } = await analysisWindows(mode, today, batch)
  const [rawIssues, warehouseOrders, warehouseSales, doudianIds, exclusionRules] = await Promise.all([
    issueRows(windows, mode, warehouseCode, batch),
    groupedOrderCounts(windows, mode, "warehouse_sales_link", batch),
    groupedSalesCounts(windows, mode, "warehouse_sales_link", batch),
    confirmedDoudianProductIds(batch!),
    Promise.resolve(batch!.rules),
  ])
  return hydratedIssueRows(
    rawIssues,
    windows,
    doudianIds,
    (row) => {
      const key = warehouseName && row.denominatorKey ? `${warehouseCode}|${row.denominatorKey}` : ""
      return {
        orders: key ? warehouseOrders.get(key) ?? warehouseOrders.get("") ?? windows.map(() => null) : windows.map(() => null),
        sales: key ? warehouseSales.get(key) ?? warehouseSales.get("") ?? windows.map(() => null) : windows.map(() => null),
      }
    },
    exclusionRuleIndex(exclusionRules),
  )
    .sort((a, b) => b.alertRank - a.alertRank || b.latestIssues - a.latestIssues || b.totalIssues - a.totalIssues || a.code.localeCompare(b.code, "zh-CN"))
}

function quantityIssueRows(
  rawIssues: RawIssueRow[],
  doudianIds: Set<string>,
  exclusionRules: ExclusionRule[],
) {
  return hydratedIssueRows(
    rawIssues,
    rawIssues[0]?.counts.map((_, index) => ({ start: "", end: "", label: String(index) })) ?? [],
    doudianIds,
    (row) => ({ orders: row.counts.map(() => null), sales: row.counts.map(() => null) }),
    exclusionRuleIndex(exclusionRules),
  )
}

export async function loadProductWeeklyReport(
  requestedWeekStart?: string,
  today = shanghaiToday(),
  requestedBatch?: ReportBatch,
  warehouseCode = "",
): Promise<ProductWeeklyReport> {
  return productForBatch(requestedWeekStart, today, isDevFixtureMode() ? null : requestedBatch ?? await reportBatch(), warehouseCode)
}

async function productForBatch(requestedWeekStart: string | undefined, today: Date, batch: ReportBatch | null, warehouseCode: string): Promise<ProductWeeklyReport> {
  "use cache"
  cacheLife({ stale: 300, revalidate: 60, expire: 3600 })
  cacheTag("aftersales-dashboard")

  const selection = productReportSelection(
    requestedWeekStart,
    today,
    isDevFixtureMode() ? undefined : await earliestCreatedIssueDate(batch!),
  )
  if (isDevFixtureMode()) {
    const { loadDevFixtureDashboard } = await import("./dev-fixture")
    const fixture = loadDevFixtureDashboard("closed", today)
    const emptyWeek = { issues: 0, orders: null, sales: null, rate: null, wow: null }
    const issueRows = fixture.issueRows.map((row) => ({ ...row, weeks: [emptyWeek, ...row.weeks] }))
    const { productRows: rows, unmatchedIssues, previousIndex } = buildProductWeeklyRows({
      rows: issueRows,
      queryWindows: selection.queryWindows,
      displayWeeks: selection.displayWeeks,
      selectedWeekStart: selection.selected.start,
    })
    return {
      selectedWeekStart: selection.selected.start,
      selectedWeekLabel: selection.selected.label,
      previousWeekLabel: selection.queryWindows[previousIndex]?.label || "前一周",
      selectableWeeks: selection.selectableWeeks,
      displayWeeks: selection.displayWeeks,
      queryWindows: selection.queryWindows,
      rows,
      issueRows: issueRows.filter((row) => row.includedInOperating),
      unmatchedIssues,
      unmatchedDetailHref: `/detail?basis=created&week_start=${selection.selected.start}&merchant_code=${encodeURIComponent("未填")}`,
      syncedAt: fixture.source.syncedAt,
    }
  }
  const [rawIssues, doudianIds, source, exclusionRules] = await Promise.all([
    createdIssueRows(selection.queryWindows, batch!, warehouseCode),
    confirmedDoudianProductIds(batch!),
    sourceSnapshot(batch!),
    Promise.resolve(batch!.rules),
  ])
  const issueData = quantityIssueRows(rawIssues, doudianIds, exclusionRules)
  const operatingRows = issueData.filter((row) => row.includedInOperating)
  const { productRows: rows, unmatchedIssues, previousIndex } = buildProductWeeklyRows({
    rows: operatingRows,
    queryWindows: selection.queryWindows,
    displayWeeks: selection.displayWeeks,
    selectedWeekStart: selection.selected.start,
  })

  return {
    selectedWeekStart: selection.selected.start,
    selectedWeekLabel: selection.selected.label,
    previousWeekLabel: selection.queryWindows[previousIndex]?.label || "前一周",
    selectableWeeks: selection.selectableWeeks,
    displayWeeks: selection.displayWeeks,
    queryWindows: selection.queryWindows,
    rows: rows.map(row => ({ ...row, detailHref: `${row.detailHref}&batch=${batch!.id}` })),
    issueRows: operatingRows,
    unmatchedIssues,
    unmatchedDetailHref: `/detail?basis=created&week_start=${selection.selected.start}&merchant_code=${encodeURIComponent("未填")}&batch=${batch!.id}`,
    syncedAt: source.syncedAt,
    batchId: batch!.id,
  }
}

export async function loadCreatedIssueData(requestedWeekStart?: string, today = shanghaiToday(), requestedBatch?: ReportBatch, warehouseCode = "") {
  return createdForBatch(requestedWeekStart, today, isDevFixtureMode() ? null : requestedBatch ?? await reportBatch(), warehouseCode)
}

async function createdForBatch(requestedWeekStart: string | undefined, today: Date, batch: ReportBatch | null, warehouseCode: string) {
  "use cache"
  cacheLife({ stale: 300, revalidate: 60, expire: 3600 })
  cacheTag("aftersales-dashboard")

  const selection = productReportSelection(
    requestedWeekStart,
    today,
    isDevFixtureMode() ? undefined : await earliestCreatedIssueDate(batch!),
  )
  const selectedIndex = selection.queryWindows.findIndex((window) => window.start === selection.selected.start)
  const windows = selection.queryWindows.slice(selectedIndex - 1, selectedIndex + 1)
  if (isDevFixtureMode()) {
    const { loadDevFixtureDashboard } = await import("./dev-fixture")
    const fixture = loadDevFixtureDashboard("closed", today)
    const fixtureSelectedIndex = selection.selectableWeeks.findIndex((window) => window.start === selection.selected.start)
    const issueRows = fixture.issueRows.map((row) => {
      const counts = [row.weeks[fixtureSelectedIndex - 1]?.issues ?? 0, row.weeks[fixtureSelectedIndex]?.issues ?? 0]
      const quantityWeeks = buildWeekMetrics(counts, [null, null], [null, null])
      return { ...row, weeks: quantityWeeks, ...comparisonFields(quantityWeeks) }
    }).filter((row) => row.currentIssues > 0)
      .sort((a, b) => b.currentIssues - a.currentIssues || a.code.localeCompare(b.code, "zh-CN"))
    return { mode: "closed" as const, windows, weeks: windows.map((window) => window.label), issueRows, batchId: batch?.id }
  }
  const [rawIssues, doudianIds, exclusionRules] = await Promise.all([
    createdIssueRows(windows, batch!, warehouseCode),
    confirmedDoudianProductIds(batch!),
    Promise.resolve(batch!.rules),
  ])
  const issueRows = quantityIssueRows(rawIssues, doudianIds, exclusionRules)
    .filter((row) => row.currentIssues > 0)
    .sort((a, b) => b.currentIssues - a.currentIssues || b.totalIssues - a.totalIssues || a.code.localeCompare(b.code, "zh-CN"))
  return { mode: "closed" as const, windows, weeks: windows.map((window) => window.label), issueRows, batchId: batch?.id }
}
