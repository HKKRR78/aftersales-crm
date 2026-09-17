import { describe, expect, it } from "vitest"

import { aggregateIssueRows, buildWeekMetrics, comparisonFields } from "@/src/modules/analytics/metrics"
import { sourceFreshness } from "@/src/modules/analytics/freshness"
import type { IssueRow } from "@/src/modules/analytics/types"

describe("analytics metrics", () => {
  it("keeps a missing denominator unavailable", () => {
    const weeks = buildWeekMetrics([2, 3], [null, null])
    expect(weeks[1].orders).toBeNull()
    expect(comparisonFields(weeks).currentOrders).toBeNull()
    expect(weeks[0].rate).toBeNull()
    expect(weeks[1].rate).toBeNull()
    expect(comparisonFields(weeks).alertLevel).toBe("neutral")
  })

  it("keeps a real zero distinct from a missing denominator", () => {
    const [week] = buildWeekMetrics([0], [0])
    expect(week.orders).toBe(0)
    expect(week.rate).toBeNull()
  })

  it("marks material deterioration as a critical alert", () => {
    const result = comparisonFields(buildWeekMetrics([6, 12], [800, 1000]))
    expect(result.rateDeltaPp).toBeCloseTo(0.45)
    expect(result.expectedIssues).toBeCloseTo(7.5)
    expect(result.excessIssues).toBeCloseTo(4.5)
    expect(result.alertLevel).toBe("critical")
  })

  it("does not multiply a product order denominator while grouping issues", () => {
    const first = issue("SKU", "质量问题", [3, 5], [100, 110])
    const second = issue("SKU", "包装问题", [2, 4], [100, 110])
    const [product] = aggregateIssueRows([first, second], (row) => ({ key: row.code, label: row.name }))
    expect(product.currentIssues).toBe(9)
    expect(product.currentOrders).toBe(110)
    expect(product.currentRate).toBeCloseTo((9 / 110) * 100)
  })

  it("separates source freshness from web health", () => {
    expect(sourceFreshness("2026-08-25 06:00:00", new Date(2026, 7, 25, 11, 0, 0), 16).state).toBe("fresh")
    expect(sourceFreshness("2026-08-21 07:43:09", new Date(2026, 7, 25, 11, 0, 0), 16).state).toBe("stale")
    expect(sourceFreshness("", new Date(2026, 7, 25, 11, 0, 0), 16).state).toBe("unknown")
  })
})

function issue(code: string, p1: string, issues: number[], orders: number[]): IssueRow {
  const weeks = buildWeekMetrics(issues, orders)
  return {
    sourceSystem: "test",
    code,
    name: "测试商品",
    productId: "",
    doudianProductId: "",
    p1,
    p2: "",
    p3: "未填写",
    category: "产品问题",
    classificationStatus: "included",
    includedInOperating: true,
    weeks,
    ...comparisonFields(weeks),
  }
}
