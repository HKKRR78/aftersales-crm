import { afterAll, expect, it, vi } from "vitest"
import type { RowDataPacket } from "mysql2"
import ExcelJS from "exceljs"
import { getPool } from "@/src/db/mysql"
import { loadExclusionRules, saveExclusionRule } from "@/src/modules/problem-rules/repository"
import { reportBatch } from "@/src/modules/analytics/repository"
import { loadCreatedIssueData, loadProductWeeklyReport } from "@/src/modules/analytics/service"
import { createExcelExport } from "@/src/modules/exports/workbook"

vi.mock("server-only", () => ({}))
vi.mock("next/cache", () => ({ cacheLife: vi.fn(), cacheTag: vi.fn() }))

if (!/^crm_rule_acceptance_\d{8}_\d{4}$/.test(process.env.MYSQL_DATABASE || "")) {
  throw new Error("Use a separately cloned crm_rule_acceptance database; never run against source or candidate")
}

afterAll(async () => { await getPool().end() })

async function current() {
  const [rows] = await getPool().query<RowDataPacket[]>(
    "SELECT b.* FROM crm_report_current c JOIN crm_report_batch b ON b.batch_id=c.batch_id WHERE singleton=1")
  return { row: rows[0], summary: JSON.parse(rows[0].summary_json) }
}

it("reclassifies real facts in a rule-only batch while preserving source scope and export totals", async () => {
  const before = await current()
  const dataId = before.summary.dataBatchId || before.row.batch_id
  expect(before.summary.integrationTestOnly).toBe(true)
  expect(before.summary.sourceCoverageApproved).toBe(false)
  const rule = (await loadExclusionRules()).find(r => r.p1 === "快递问题" && r.p2 === "改地址" && r.p3 === "*")!
  expect(rule.enabled).toBe(true)
  const [rows] = await getPool().query<RowDataPacket[]>(
    "SELECT COUNT(*) n FROM crm_report_issue WHERE batch_id=? AND problem1='快递问题' AND problem2='改地址'",
    [dataId])
  expect(Number(rows[0].n)).toBeGreaterThan(0)
  try {
    await saveExclusionRule({ ...rule, enabled: false }, "isolated-real-fact-acceptance")
    const changed = await current()
    expect(changed.row.batch_id).not.toBe(before.row.batch_id)
    expect(changed.summary.dataBatchId).toBe(dataId)
    expect(changed.summary.verificationKind).toBe("rules_on_verified_facts")
    expect(changed.row.coverage_start).toBe(before.row.coverage_start)
    expect(changed.row.coverage_end).toBe(before.row.coverage_end)
    expect(changed.row.source_synced_at).toBe(before.row.source_synced_at)
    expect(changed.summary.quantityConservation.operating).toBe(before.summary.quantityConservation.operating + Number(rows[0].n))
    const batch = await reportBatch(changed.row.batch_id)
    const today = new Date(2026, 8, 16)
    for (const week of ["2026-08-09", "2026-08-16", "2026-08-23", "2026-08-30", "2026-09-06"]) {
      const report = await loadProductWeeklyReport(week, today, batch)
      const detail = await loadCreatedIssueData(week, today, batch)
      const total = detail.issueRows.filter(row => row.includedInOperating).reduce((n, row) => n + row.currentIssues, 0)
      expect(report.rows.reduce((n, row) => n + row.selectedIssues, 0) + report.unmatchedIssues).toBe(total)
      const chunks: Buffer[] = []
      const exported = createExcelExport(null, { view: "products", mode: "closed", search: {}, basis: "created", weekStart: week }, today, report)
      const collected = new Promise<Buffer>((resolve, reject) => {
        exported.stream.on("data", chunk => chunks.push(Buffer.from(chunk)))
        exported.stream.on("end", () => resolve(Buffer.concat(chunks)))
        exported.stream.on("error", reject)
      })
      await exported.done
      const workbook = new ExcelJS.Workbook()
      await workbook.xlsx.load((await collected) as never)
      const sheet = workbook.getWorksheet("产品分析")!
      const headers = sheet.getRow(9).values as ExcelJS.CellValue[]
      const countColumn = headers.indexOf(`${report.selectedWeekLabel} 问题数`)
      expect(countColumn).toBeGreaterThan(0)
      let exportedIssues = 0
      for (let index = 10; index <= sheet.rowCount; index++) exportedIssues += Number(sheet.getRow(index).getCell(countColumn).value)
      expect(exportedIssues + report.unmatchedIssues).toBe(total)
      expect(exported.rowCounts.products).toBe(report.rows.length)
    }
  } finally {
    await saveExclusionRule(rule, "isolated-real-fact-acceptance-restored")
  }
  const restored = await current()
  expect(restored.summary.quantityConservation).toEqual(before.summary.quantityConservation)
  expect(restored.row.source_synced_at).toBe(before.row.source_synced_at)
})
