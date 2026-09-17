import { shanghaiToday } from "@/src/modules/analytics/date-windows"
import { reportBatch } from "@/src/modules/analytics/repository"
import { isDevFixtureMode } from "@/src/modules/analytics/dev-mode"
import { NextResponse, type NextRequest } from "next/server"

import { currentUser } from "@/src/auth/current-user"
import { filterIssueRows, issueFiltersFromSearch, summarizeIssueRows } from "@/src/modules/analytics/filters"
import { loadCreatedIssueData, loadDashboard, loadWarehouseIssueRows } from "@/src/modules/analytics/service"
import type { PeriodMode } from "@/src/modules/analytics/types"

const MAX_PAGE_SIZE = 240

function boundedInteger(value: string | null, fallback: number, maximum: number) {
  const parsed = Number.parseInt(value || "", 10)
  if (!Number.isFinite(parsed) || parsed < 0) return fallback
  return Math.min(parsed, maximum)
}

export async function GET(request: NextRequest) {
  await currentUser()
  const batch = isDevFixtureMode() ? undefined : await reportBatch(request.nextUrl.searchParams.get("batch") || undefined)
  const today = shanghaiToday()
  const values = Object.fromEntries(request.nextUrl.searchParams.entries())
  const mode: PeriodMode = values.period === "progress" ? "progress" : "closed"
  const filters = issueFiltersFromSearch(values)
  const offset = boundedInteger(request.nextUrl.searchParams.get("offset"), 0, 1_000_000)
  const limit = boundedInteger(request.nextUrl.searchParams.get("limit"), MAX_PAGE_SIZE, MAX_PAGE_SIZE) || MAX_PAGE_SIZE

  const createdBasis = values.basis === "created"
  let sourceRows
  if (createdBasis) {
    sourceRows = (await loadCreatedIssueData(values.week_start, today, batch, filters.warehouseCode)).issueRows
  } else {
    const data = await loadDashboard(mode, today, batch)
    sourceRows = data.issueRows
    if (filters.warehouseCode) {
      const warehouse = data.warehouseRows.find((row) => row.warehouseCode === filters.warehouseCode)
      sourceRows = await loadWarehouseIssueRows(mode, filters.warehouseCode, warehouse?.warehouseName || "", today, batch)
    }
  }
  const auditRows = filterIssueRows(sourceRows, { ...filters, scope: "all" })
  const rows = filterIssueRows(sourceRows, filters)

  return NextResponse.json(
    { rows: rows.slice(offset, offset + limit), rowGroupCount: rows.length, auditSummary: summarizeIssueRows(auditRows), offset },
    { headers: { "cache-control": "private, no-store", "x-data-batch": batch?.id || "fixture", "x-build-id": process.env.CRM_BUILD_ID || "development" } },
  )
}
