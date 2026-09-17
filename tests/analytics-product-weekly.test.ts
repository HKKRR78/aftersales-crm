import { describe, expect, it } from "vitest"

import { closedWeekWindows, productReportSelection } from "@/src/modules/analytics/date-windows"
import { buildWeekMetrics, comparisonFields } from "@/src/modules/analytics/metrics"
import { buildProductWeeklyRows } from "@/src/modules/analytics/product-weekly"
import type { IssueRow } from "@/src/modules/analytics/types"

function issue(code: string, counts: number[], productId = "1", included = true): IssueRow {
  const weeks = buildWeekMetrics(counts, counts.map(() => null), counts.map(() => null))
  return {
    sourceSystem: "test",
    code,
    name: `商品 ${code}`,
    productId,
    doudianProductId: "",
    p1: "质量问题",
    p2: "破损",
    p3: "未填写",
    category: "产品问题",
    classificationStatus: included ? "included" : "excluded",
    includedInOperating: included,
    weeks,
    ...comparisonFields(weeks),
  }
}

describe("product weekly report", () => {
  const queryWindows = closedWeekWindows(new Date(2026, 8, 14, 10), 6)
  const displayWeeks = [...queryWindows.slice(1)].reverse()

  it("defaults to the last complete Sunday-through-Saturday week and validates selections", () => {
    const latest = productReportSelection(undefined, new Date(2026, 8, 14, 10), "2026-06-08 12:20:51")
    expect(latest.selected.start).toBe("2026-09-06")
    expect(latest.selected.end).toBe("2026-09-13")
    expect(latest.selectableWeeks).toHaveLength(14)
    expect(latest.selectableWeeks[0].start).toBe("2026-06-07")
    expect(productReportSelection("2026-08-16", new Date(2026, 8, 14, 10), "2026-06-08").selected.start).toBe("2026-08-16")
    expect(productReportSelection("2025-01-01", new Date(2026, 8, 14, 10), "2026-06-08").selected.start).toBe("2026-09-06")
    const earliest = productReportSelection("2026-06-07", new Date(2026, 8, 14, 10), "2026-06-08")
    expect(earliest.selected.start).toBe("2026-06-07")
    expect(earliest.displayWeeks.map((week) => week.start)).toEqual(["2026-06-07"])
    expect(earliest.queryWindows[0].start).toBe("2026-05-31")
  })

  it("sorts by selected-week count, excludes zero rows and keeps exact codes separate", () => {
    const result = buildProductWeeklyRows({
      rows: [
        issue("A*3", [0, 0, 1, 2, 4, 7]),
        issue("A*6", [0, 0, 3, 2, 4, 7]),
        issue("B", [0, 1, 2, 3, 4, 9]),
        issue("C", [4, 3, 2, 1, 0, 0]),
        issue("D", [0, 0, 0, 0, 0, 20], "4", false),
        issue("未填", [0, 0, 0, 0, 2, 5]),
      ],
      queryWindows,
      displayWeeks,
      selectedWeekStart: "2026-09-06",
    })
    expect(result.productRows.map((row) => row.code)).toEqual(["B", "A*3", "A*6"])
    expect(result.productRows.map((row) => row.selectedIssues)).toEqual([9, 7, 7])
    expect(result.productRows[0].deltaIssues).toBe(5)
    expect(result.productRows[0].weeklyIssues).toEqual([9, 4, 3, 2, 1])
    expect(result.productRows[0].detailHref).toContain("scope=all")
    expect(result.unmatchedIssues).toBe(5)
  })
})
