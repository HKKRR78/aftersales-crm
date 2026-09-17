import { describe, expect, it } from "vitest"

import { loadDevFixtureDashboard } from "@/src/modules/analytics/dev-fixture"

describe("local acceptance fixture", () => {
  it("provides enough unique rows to exercise virtualization", () => {
    const dashboard = loadDevFixtureDashboard("closed", new Date(2026, 7, 25, 11, 0, 0))
    const keys = dashboard.issueRows.map((row) => `${row.code}|${row.productId}|${row.p1}|${row.p2}|${row.category}`)
    expect(dashboard.source.sourceType).toBe("fixture")
    expect(dashboard.issueRows).toHaveLength(2_400)
    expect(new Set(keys).size).toBe(keys.length)
    expect(dashboard.productRows).toHaveLength(800)
  })
})
