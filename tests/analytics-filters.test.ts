import { describe, expect, it } from "vitest"

import { filterIssueRows, issueFiltersFromSearch, summarizeIssueRows } from "@/src/modules/analytics/filters"
import { loadDevFixtureDashboard } from "@/src/modules/analytics/dev-fixture"

describe("shared page and export filters", () => {
  const data = loadDevFixtureDashboard("closed", new Date(2026, 7, 25, 11, 0, 0))

  it("defaults to the operating-exception scope", () => {
    const rows = filterIssueRows(data.issueRows, issueFiltersFromSearch({}))
    expect(rows.length).toBeLessThan(2_400)
    expect(rows.every((row) => row.includedInOperating)).toBe(true)
    expect(filterIssueRows(data.issueRows, issueFiltersFromSearch({ scope: "all" }))).toHaveLength(2_400)
  })

  it("combines exact identifiers, categories, alert and keyword filters", () => {
    const source = data.issueRows.find((row) => row.alertLevel === "critical" && row.doudianProductId)!
    const rows = filterIssueRows(data.issueRows, issueFiltersFromSearch({
      q: source.name.slice(0, 4),
      p1: source.p1,
      p2: source.p2,
      merchant_code: source.code,
      product_id: source.productId,
      doudian_product_id: source.doudianProductId,
      alert: source.alertLevel,
    }))
    expect(rows.length).toBeGreaterThan(0)
    expect(rows.every((row) => row.code === source.code && row.productId === source.productId && row.doudianProductId === source.doudianProductId)).toBe(true)
    expect(rows.every((row) => row.p1 === source.p1 && row.p2 === source.p2 && row.alertLevel === source.alertLevel)).toBe(true)
  })

  it("searches the raw aftersales ID even when no Doudian ID is confirmed", () => {
    const source = data.issueRows.find((row) => row.productId && !row.doudianProductId)!
    const rows = filterIssueRows(data.issueRows, issueFiltersFromSearch({ product_id: source.productId }))
    expect(rows.length).toBeGreaterThan(0)
    expect(rows.every((row) => row.productId === source.productId)).toBe(true)
  })

  it("balances operating, excluded, unclassified and both source inputs", () => {
    const rows = data.issueRows.slice(0, 3).map((row, index) => ({
      ...row,
      sourceSystem: index === 0 ? "banniu+ticket_service" : "ticket_service",
      classificationStatus: (["included", "excluded", "unclassified"] as const)[index],
      includedInOperating: index === 0,
      currentIssues: index + 1,
      previousIssues: index,
      code: index === 0 ? "未填" : row.code,
    }))
    const audit = summarizeIssueRows(rows)
    expect(audit.totalIssues).toBe(6)
    expect(audit.operatingIssues + audit.excludedIssues + audit.unclassifiedIssues).toBe(6)
    expect(audit.matchedOperatingIssues + audit.unmatchedOperatingIssues).toBe(audit.operatingIssues)
    expect(audit.sourceInputs).toEqual([
      { sourceSystem: "banniu", issues: 1 },
      { sourceSystem: "ticket_service", issues: 6 },
    ])
  })
})
