import { format } from "date-fns"

import { completedDays, windowsFor } from "./date-windows"
import { aggregateIssueRows, buildWeekMetrics, comparisonFields, sumMetrics } from "./metrics"
import type { DashboardData, IssueRow, PeriodMode, WarehouseRow } from "./types"

const categories = ["快递问题", "库房问题", "买家问题", "产品问题", "运营问题"] as const
const secondaries = ["外观瑕疵", "功能异常", "包装压损", "配件缺失", "发货错误", "运输破损", "描述不符", "使用不便"]
const productRoots = ["东北黑蜂椴树蜜", "云南高山核桃", "即食燕窝礼盒", "长白山人参片", "有机杂粮组合", "冻干草莓脆", "手工牛肉干", "黑芝麻丸"]

function wave(index: number, step: number) {
  return ((index * 17 + step * 23) % 29) / 29
}

export function loadDevFixtureDashboard(mode: PeriodMode, today = new Date()): DashboardData {
  if (process.env.NODE_ENV === "production") throw new Error("Fixture data is disabled in production")
  const windows = windowsFor(mode, today)
  const points = windows.length
  const totalOrders = Array.from({ length: points }, (_, index) => 132_000 + index * 6_800)
  const issueRows: IssueRow[] = Array.from({ length: 2_400 }, (_, index) => {
    const productIndex = index % 800
    const batch = Math.floor(index / 800)
    const categoryIndex = (index + batch) % categories.length
    const baseline = 1 + (index % 7)
    const counts = Array.from({ length: points }, (_, step) => {
      const trend = index % 11 < 4 ? step * 2 : index % 11 > 8 ? -step : 0
      return Math.max(0, Math.round(baseline + trend + wave(index, step) * 4))
    })
    const productOrders = Array.from({ length: points }, (_, step) => 310 + (productIndex % 90) * 6 + step * 17)
    const productSales = productOrders.map((orders, step) => Math.round(orders * (1.14 + wave(index, step) * .22)))
    const weeks = buildWeekMetrics(counts, productOrders, productSales)
    const root = productRoots[productIndex % productRoots.length]
    return {
      sourceSystem: "fixture",
      code: `YY-${String(productIndex + 1).padStart(4, "0")}`,
      name: `${root} ${100 + (productIndex % 9) * 50}g`,
      productId: (7_000_000_000_000_000_000n + BigInt(productIndex)).toString(),
      doudianProductId: productIndex % 4 === 0
        ? (7_000_000_000_000_000_000n + BigInt(productIndex)).toString()
        : "",
      p1: categories[categoryIndex],
      p2: secondaries[(index * 3 + batch) % secondaries.length],
      p3: batch % 2 ? "要求理赔" : "30",
      category: categories[categoryIndex],
      classificationStatus: index % 13 === 0 ? "excluded" : "included",
      includedInOperating: index % 13 !== 0,
      weeks,
      ...comparisonFields(weeks),
    }
  })
  issueRows.sort((a, b) => b.alertRank - a.alertRank || b.latestIssues - a.latestIssues || a.code.localeCompare(b.code))

  const warehouseRows: WarehouseRow[] = Array.from({ length: 18 }, (_, index) => {
    const counts = Array.from({ length: points }, (_, step) => 4 + ((index * 7 + step * 5) % 19))
    const orders = Array.from({ length: points }, (_, step) => 8_000 + index * 630 + step * 280)
    const weeks = buildWeekMetrics(counts, orders, orders.map((value) => Math.round(value * 1.18)))
    const city = ["北京", "沈阳", "杭州", "武汉", "成都", "广州"][index % 6]
    return {
      warehouse: `WH-${String(index + 1).padStart(2, "0")} / ${city}仓${Math.floor(index / 6) + 1}`,
      warehouseCode: `WH-${String(index + 1).padStart(2, "0")}`,
      warehouseName: `${city}仓${Math.floor(index / 6) + 1}`,
      weeks,
      ...comparisonFields(weeks),
    }
  }).sort((a, b) => b.alertRank - a.alertRank || b.latestIssues - a.latestIssues)

  const operatingRows = issueRows.filter((row) => row.includedInOperating)
  const totalSales = totalOrders.map((value, index) => Math.round(value * (1.16 + index * .01)))
  const categoryRows = aggregateIssueRows(
    operatingRows.map((row) => ({ ...row, weeks: buildWeekMetrics(row.weeks.map((week) => week.issues), totalOrders, totalSales) })),
    (row) => ({ key: row.p1, label: row.p1 }),
  )
  const productRows = aggregateIssueRows(operatingRows, (row) => ({
    key: row.code,
    label: row.name,
    secondary: row.code,
    productId: row.productId,
    doudianProductId: row.doudianProductId,
    detailHref: `/detail?merchant_code=${encodeURIComponent(row.code)}&period=${mode}`,
  }))
  const totals = sumMetrics(operatingRows, totalOrders, totalSales)
  const weeklyTotals = buildWeekMetrics(
    windows.map((_, index) => operatingRows.reduce((sum, row) => sum + row.weeks[index].issues, 0)),
    totalOrders,
    totalSales,
  )

  return {
    mode,
    windows,
    weeks: windows.map((window) => window.label),
    kpis: {
      ...totals,
      latestAllIssues: issueRows.reduce((sum, row) => sum + row.currentIssues, 0),
      unclassifiedIssues: issueRows.filter((row) => row.classificationStatus === "unclassified").reduce((sum, row) => sum + row.currentIssues, 0),
      rowCount: operatingRows.length,
      redAlerts: operatingRows.filter((row) => row.alertLevel === "critical").length,
      deteriorated: operatingRows.filter((row) => (row.rateDeltaPp ?? 0) > 0).length,
    },
    weeklyTotals,
    categoryRows,
    productRows,
    issueRows,
    warehouseRows,
    source: {
      sourceType: "fixture",
      currentPeriod: windows.at(-1)?.label || "",
      syncedAt: format(today, "yyyy-MM-dd HH:mm:ss"),
      apiRows: 58_865,
      completedDays: completedDays(windows.at(-1)!),
      periodMode: mode,
      productOrderThrough: format(today, "yyyy-MM-dd"),
      productOrderState: "fresh",
      productOrderFallbackRows: 0,
      productOrderUnavailableRows: 0,
    },
  }
}
