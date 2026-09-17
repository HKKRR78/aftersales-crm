import { addDays, parseISO } from "date-fns"
import { shanghaiToday } from "@/src/modules/analytics/date-windows"
import { reportBatch } from "@/src/modules/analytics/repository"
import { isDevFixtureMode } from "@/src/modules/analytics/dev-mode"
import { Readable } from "node:stream"

import { currentUser } from "@/src/auth/current-user"
import { loadCreatedIssueData, loadDashboard, loadProductWeeklyReport, loadWarehouseIssueRows } from "@/src/modules/analytics/service"
import { exportRequestFromUrl } from "@/src/modules/exports/selection"
import { createExcelExport } from "@/src/modules/exports/workbook"

function encodedFilename(filename: string) {
  return encodeURIComponent(filename).replace(/[!'()*]/g, (character) => `%${character.charCodeAt(0).toString(16).toUpperCase()}`)
}

export async function GET(request: Request) {
  const startedAt = Date.now()
  const parsed = exportRequestFromUrl(new URL(request.url))
  if (!parsed) return Response.json({ ok: false, error: "未知的导出视图" }, { status: 400 })

  let user
  try {
    user = await currentUser()
  } catch {
    return Response.json({ ok: false, error: "请从公司员工统一入口登录" }, { status: 401 })
  }

  try {
    const batch = isDevFixtureMode() ? undefined : await reportBatch(new URL(request.url).searchParams.get("batch") || undefined)
    const today = shanghaiToday()
    const needsProductReport = parsed.view === "complete"
      ? parsed.mode === "closed"
      : parsed.view === "products" || parsed.basis === "created"
    const productReport = needsProductReport
      ? await loadProductWeeklyReport(parsed.weekStart, today, batch, (parsed.search.warehouse_code || "").trim())
      : undefined
    const reportToday = parsed.weekStart && productReport && parsed.mode === "closed" ? addDays(parseISO(productReport.selectedWeekStart), 7) : today
    let data = parsed.view === "products" ? null : await loadDashboard(parsed.mode, reportToday, batch)
    if (parsed.basis === "created" && parsed.view === "detail") {
      const created = await loadCreatedIssueData(parsed.weekStart, today, batch, (parsed.search.warehouse_code || "").trim())
      data = { ...data!, mode: created.mode, windows: created.windows, weeks: created.weeks, issueRows: created.issueRows }
    }
    const warehouseCode = (parsed.search.warehouse_code || "").trim()
    if (data && warehouseCode && (parsed.view === "detail" || parsed.view === "complete") && !(parsed.basis === "created" && parsed.view === "detail")) {
      const warehouse = data.warehouseRows.find((row) => row.warehouseCode === warehouseCode)
      const issueRows = await loadWarehouseIssueRows(parsed.mode, warehouseCode, warehouse?.warehouseName || "", reportToday, batch)
      data = { ...data, issueRows }
    }
    const exported = createExcelExport(data, parsed, new Date(), productReport)
    const totalRows = Object.values(exported.rowCounts).reduce((sum, count) => sum + count, 0)
    void exported.done.then(
      () => console.info(JSON.stringify({
        event: "aftersales_excel_export",
        status: "success",
        view: parsed.view,
        period: parsed.mode,
        rows: exported.rowCounts,
        totalRows,
        durationMs: Date.now() - startedAt,
        userId: user.id,
      })),
      (error) => console.error(JSON.stringify({
        event: "aftersales_excel_export",
        status: "failed",
        view: parsed.view,
        period: parsed.mode,
        rows: exported.rowCounts,
        durationMs: Date.now() - startedAt,
        error: error instanceof Error ? error.message : String(error),
        userId: user.id,
      })),
    )
    return new Response(Readable.toWeb(exported.stream) as ReadableStream, {
      headers: {
        "cache-control": "private, no-store",
        "content-disposition": `attachment; filename="aftersales_${parsed.view}_${parsed.mode}.xlsx"; filename*=UTF-8''${encodedFilename(exported.filename)}`,
        "content-type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "x-export-row-count": String(totalRows),
        "x-data-batch": batch?.id || "fixture",
        "x-build-id": process.env.CRM_BUILD_ID || "development",
      },
    })
  } catch (error) {
    console.error(JSON.stringify({
      event: "aftersales_excel_export",
      status: "failed_before_stream",
      view: parsed.view,
      period: parsed.mode,
      durationMs: Date.now() - startedAt,
      error: error instanceof Error ? error.message : String(error),
      stack: error instanceof Error ? error.stack : undefined,
      userId: user.id,
    }))
    return Response.json({ ok: false, error: "Excel 生成失败，请稍后重试" }, { status: 500 })
  }
}
