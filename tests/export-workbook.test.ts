import { describe, expect, it, vi } from "vitest"

import ExcelJS from "exceljs"

import { loadDevFixtureDashboard } from "@/src/modules/analytics/dev-fixture"
import type { ProductWeeklyReport } from "@/src/modules/analytics/types"
import type { ExportRequest } from "@/src/modules/exports/selection"

vi.mock("server-only", () => ({}))

async function workbookFor(request: ExportRequest, productReport?: ProductWeeklyReport) {
  const { createExcelExport } = await import("@/src/modules/exports/workbook")
  const data = loadDevFixtureDashboard(request.mode, new Date(2026, 7, 25, 11, 0, 0))
  const chunks: Buffer[] = []
  const exported = createExcelExport(data, request, new Date(2026, 7, 25, 12, 30, 0), productReport)
  const collected = new Promise<Buffer>((resolve, reject) => {
    exported.stream.on("data", (chunk) => chunks.push(Buffer.from(chunk)))
    exported.stream.on("end", () => resolve(Buffer.concat(chunks)))
    exported.stream.on("error", reject)
  })
  await exported.done
  const buffer = await collected
  const workbook = new ExcelJS.Workbook()
  // ExcelJS 4.4 types predate Node 24's generic Buffer declaration.
  await workbook.xlsx.load(buffer as never)
  return { workbook, exported, data }
}

async function productWorkbookFor(report: ProductWeeklyReport, request: ExportRequest) {
  const { createExcelExport } = await import("@/src/modules/exports/workbook")
  const chunks: Buffer[] = []
  const exported = createExcelExport(null, request, new Date(2026, 8, 14, 12, 30, 0), report)
  const collected = new Promise<Buffer>((resolve, reject) => {
    exported.stream.on("data", (chunk) => chunks.push(Buffer.from(chunk)))
    exported.stream.on("end", () => resolve(Buffer.concat(chunks)))
    exported.stream.on("error", reject)
  })
  await exported.done
  const workbook = new ExcelJS.Workbook()
  await workbook.xlsx.load((await collected) as never)
  return { workbook, exported }
}

describe("streaming Excel export", () => {
  function headerRow(sheet: ExcelJS.Worksheet) {
    const row = sheet.findRow(sheet.getColumn(1).values.findIndex((value) => value === "商家编码"))
    if (!row) throw new Error("未找到导出表头")
    return row
  }

  it("keeps every sheet on the same occurrence period for a progress export", async () => {
    const source = loadDevFixtureDashboard("progress", new Date(2026, 7, 25, 11, 0, 0))
    const target = source.issueRows.find((row) => row.includedInOperating && row.currentIssues > 0)!
    const staleWeek = { start: "2026-08-16", end: "2026-08-23", label: "0816-0822" }
    const stale: ProductWeeklyReport = {
      selectedWeekStart: staleWeek.start, selectedWeekLabel: staleWeek.label,
      previousWeekLabel: "0809-0815", selectableWeeks: [staleWeek], displayWeeks: [staleWeek],
      rows: [], issueRows: [], unmatchedIssues: 0, unmatchedDetailHref: "", syncedAt: "",
    }
    const { workbook, data, exported } = await workbookFor({
      view: "complete", mode: "progress", search: { merchant_code: target.code },
      basis: "payment", weekStart: "",
    }, stale)
    const sheet = workbook.getWorksheet("产品分析")!
    const header = headerRow(sheet)
    const firstDataRow = header.number + 1
    const expectedRows = data.issueRows.filter((row) => row.code === target.code && row.includedInOperating)
    expect(exported.rowCounts.products).toBe(1)
    expect(sheet.getRow(firstDataRow).getCell(1).value).toBe(target.code)
    expect(sheet.getRow(firstDataRow).getCell(4).value).toBe(expectedRows.reduce((sum, row) => sum + row.currentIssues, 0))
    expect(sheet.getRow(firstDataRow).getCell(5).value).toBe(expectedRows.reduce((sum, row) => sum + row.previousIssues, 0))
    expect(header.getCell(4).value).toBe(`${data.windows.at(-1)!.label} 问题数`)
    expect(header.getCell(5).value).toBe(`${data.windows.at(-2)!.label} 问题数`)
    expect(sheet.getCell("B3").value).toContain(data.windows.at(-1)!.start)
    expect(header.values).not.toContain(`${staleWeek.label} 问题数`)
    expect(workbook.getWorksheet("售后问题明细")!.getCell("B3").value).toContain(data.windows.at(-1)!.start)
  })

  it("creates the four-sheet operating workbook from the same filtered result", async () => {
    const data = loadDevFixtureDashboard("closed", new Date(2026, 7, 25, 11, 0, 0))
    const target = data.issueRows[0]
    const { workbook, exported } = await workbookFor({
      view: "complete",
      mode: "closed",
      search: { merchant_code: target.code },
      basis: "payment",
      weekStart: "",
    })
    expect(workbook.worksheets.map((sheet) => sheet.name)).toEqual(["一级类别汇总", "售后问题明细", "产品分析", "仓库分析"])
    expect(workbook.getWorksheet("售后问题明细")!.rowCount).toBe(exported.rowCounts.detail + 9)
    expect(workbook.getWorksheet("售后问题明细")!.getCell("B4").value).toBeTruthy()
    expect(workbook.getWorksheet("售后问题明细")!.autoFilter).toBeTruthy()
  })

  it("writes identifiers as text, rates as numeric percentages and protects formulas", async () => {
    const data = loadDevFixtureDashboard("progress", new Date(2026, 7, 25, 11, 0, 0))
    const target = data.issueRows[0]
    const { workbook } = await workbookFor({
      view: "detail",
      mode: "progress",
      search: { merchant_code: target.code },
      basis: "payment",
      weekStart: "",
    })
    const sheet = workbook.getWorksheet("售后问题明细")!
    expect(sheet.getCell("A10").numFmt).toBe("@")
    expect(sheet.getCell("B10").numFmt).toBe("@")
    expect(sheet.getCell("D10").numFmt).toBe("@")
    expect(sheet.getCell("B10").value).toBe(target.productId)
    expect(typeof sheet.getCell("B10").value).toBe("string")
    expect(String(sheet.getCell("B10").value)).toHaveLength(19)
    expect(sheet.getCell("C10").value).toBe("fixture")
    expect(sheet.getCell("D10").value).toBe(target.doudianProductId)
    const headerValues = sheet.getRow(9).values
    expect(headerValues).toContain("统计状态")
    expect(headerValues).not.toContain("归并后问题")
    expect(headerValues).not.toContain("问题大类")
    const rateColumn = Array.isArray(headerValues) ? headerValues.findIndex((value) => value === "当期售后率") : -1
    expect(rateColumn).toBeGreaterThan(0)
    expect(typeof sheet.getRow(10).getCell(rateColumn).value).toBe("number")
    expect(sheet.getRow(10).getCell(rateColumn).numFmt).toBe("0.00%")
    const { safeExcelText } = await import("@/src/modules/exports/workbook")
    expect(safeExcelText("=SUM(A1:A2)")).toBe("'=SUM(A1:A2)")
    expect(safeExcelText("正常商品")).toBe("正常商品")
  })

  it("exports the complete created-week product ranking without legacy denominator columns", async () => {
    const displayWeeks = [
      { start: "2026-09-06", end: "2026-09-13", label: "0906-0912" },
      { start: "2026-08-30", end: "2026-09-06", label: "0830-0905" },
    ]
    const report: ProductWeeklyReport = {
      selectedWeekStart: "2026-09-06",
      selectedWeekLabel: "0906-0912",
      previousWeekLabel: "0830-0905",
      selectableWeeks: displayWeeks,
      displayWeeks,
      rows: [{
        key: "SKU-001",
        code: "SKU-001",
        label: "测试商品",
        secondary: "SKU-001",
        linkCount: 2,
        selectedIssues: 9,
        previousIssues: 3,
        deltaIssues: 6,
        weeklyIssues: [9, 3],
        detailHref: "/detail?basis=created&week_start=2026-09-06&merchant_code=SKU-001",
      }],
      issueRows: [],
      unmatchedIssues: 2,
      unmatchedDetailHref: "/detail?basis=created&week_start=2026-09-06&merchant_code=__unmatched__",
      syncedAt: "2026-09-14 12:00:00",
    }
    const { workbook, exported } = await productWorkbookFor(report, {
      view: "products",
      mode: "closed",
      search: {},
      basis: "created",
      weekStart: "2026-09-06",
    })
    const sheet = workbook.getWorksheet("产品分析")!
    const header = headerRow(sheet)
    const headers = header.values
    expect(exported.rowCounts.products).toBe(1)
    expect(sheet.rowCount).toBe(header.number + 1)
    expect(headers).toContain("0906-0912 问题数")
    expect(headers).toContain("较前一周增减")
    expect(headers).not.toContain("当期订单数")
    expect(headers).not.toContain("产品销量")
    expect(headers).not.toContain("售后率")
    expect(sheet.getRow(header.number + 1).getCell(1).value).toBe("SKU-001")
    expect(sheet.getColumn(1).width).toBe(20)
    expect(sheet.getColumn(2).width).toBe(42)
    expect(sheet.getRow(header.number + 1).getCell(1).alignment.wrapText).toBe(true)
    expect(sheet.getColumn(1).values).not.toContain("待匹配记录")
  })
})
