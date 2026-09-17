import { shanghaiToday } from "@/src/modules/analytics/date-windows"
import { reportBatch } from "@/src/modules/analytics/repository"
import { isDevFixtureMode } from "@/src/modules/analytics/dev-mode"
import { NextResponse, type NextRequest } from "next/server"

import { currentUser } from "@/src/auth/current-user"
import { filterProductWeeklyRows, listFiltersFromSearch } from "@/src/modules/analytics/filters"
import { loadProductWeeklyReport } from "@/src/modules/analytics/service"

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
  const offset = boundedInteger(request.nextUrl.searchParams.get("offset"), 0, 1_000_000)
  const limit = boundedInteger(request.nextUrl.searchParams.get("limit"), 200, 200) || 200
  const data = await loadProductWeeklyReport(values.week_start, today, batch)
  const rows = filterProductWeeklyRows(data.rows, listFiltersFromSearch(values))

  return NextResponse.json(
    { rows: rows.slice(offset, offset + limit), total: rows.length, offset },
    { headers: { "cache-control": "private, no-store", "x-data-batch": batch?.id || "fixture", "x-build-id": process.env.CRM_BUILD_ID || "development" } },
  )
}
