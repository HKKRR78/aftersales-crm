import "server-only"
import type { RowDataPacket } from "mysql2"
import { getPool } from "@/src/db/mysql"
import type { ExclusionRule } from "@/src/modules/problem-rules/types"
import { DataUnavailableError } from "./errors"
import type { DateWindow, OrderWatermark, PeriodMode, RawIssueRow, RawWarehouseRow, SourceSnapshot } from "./types"

export interface ReportBatch {
  id: string
  dataId?: string
  start: string
  end: string
  syncedAt: string
  issueCount: number
  rules: ExclusionRule[]
  completeThrough: string
  earliestCreatedAt: string
  verification?: "candidate" | "verified"
  verificationKind?: string
  issueCoverageApproved?: boolean
  salesCoverageApproved?: boolean
  productSalesCoverageApproved?: boolean
  productOrderThrough?: string
  productMetricLayer?: boolean
}

// Production reads only verified batches. An isolated acceptance process can
// pin one candidate explicitly; request parameters cannot select other candidates.
export async function reportBatch(requested?: string): Promise<ReportBatch> {
  const preview = process.env.CRM_REPORT_PREVIEW_BATCH_ID
  // Employee URLs always follow the atomic current pointer. Candidate
  // acceptance is pinned only by a server-owned preview environment variable.
  const candidate = preview ? (!requested || requested === preview ? preview : requested) : process.env.CRM_REPORT_BATCH_ID
  const previewSelected = Boolean(preview && candidate === preview)
  const [rows] = await getPool().query<(RowDataPacket & {
    batch_id: string; coverage_start: string; coverage_end: string; source_synced_at: string;
    issue_count: number; summary_json: string; status: "candidate" | "verified"
  })[]>(`SELECT b.* FROM crm_report_batch b
    ${candidate ? "" : "JOIN crm_report_current c ON c.batch_id=b.batch_id AND c.singleton=1"}
    WHERE ${previewSelected ? "b.status IN ('candidate','verified')" : "b.status='verified'"} ${candidate ? "AND b.batch_id=?" : ""}`, candidate ? [candidate] : [])
  if (rows.length !== 1) throw new DataUnavailableError("没有已核验的报告批次", "report_batch_unavailable")
  const row = rows[0]
  const summary = JSON.parse(row.summary_json)
  if (!Array.isArray(summary.rules)) throw new DataUnavailableError("报告规则快照缺失", "report_rules_missing")
  if (!summary.earliestCreatedAt) throw new DataUnavailableError("历史期间范围缺失", "report_history_scope_missing")
  return { id: row.batch_id, dataId: summary.dataBatchId || row.batch_id, start: row.coverage_start, end: row.coverage_end,
    syncedAt: row.source_synced_at, issueCount: Number(row.issue_count),
    rules: summary.rules, completeThrough: summary.completeThrough || "", earliestCreatedAt: summary.earliestCreatedAt,
    verification: row.status, verificationKind: summary.verificationKind || "full",
    issueCoverageApproved: summary.issueCoverageApproved === true,
    salesCoverageApproved: summary.salesCoverageApproved !== false,
    productSalesCoverageApproved: summary.productSalesCoverageApproved === true,
    productOrderThrough: summary.productOrderThrough || summary.frozenThrough || "",
    productMetricLayer: summary.productMetricLayer === true }
}

type Series = Map<string, Array<number | null>>
type Grain = "merchant_code" | "aftersales_product_id" | "warehouse" | "warehouse_sales_link" | "total"

function requireReportScope(windows: DateWindow[], batch: ReportBatch) {
  if (!windows.length || windows.some(w => w.start < batch.start || w.end > batch.end || w.start > w.end)) {
    throw new DataUnavailableError("所选期间尚未完成核验，历史原始数据已保留", "report_period_unverified")
  }
}

async function periodCoverage(windows: DateWindow[], batch: ReportBatch) {
  requireReportScope(windows,batch)
  const [rows] = await getPool().query<(RowDataPacket & { stat_date: string; ready: number })[]>(
    `SELECT stat_date, MIN(status='verified') ready FROM crm_report_coverage
     WHERE batch_id=? AND stat_date>=? AND stat_date<? GROUP BY stat_date`,
    [batch.dataId ?? batch.id, windows[0].start, windows.at(-1)!.end])
  const days = new Map(rows.map(r => [r.stat_date, Boolean(r.ready)]))
  return windows.map(w => {
    for (let day = new Date(`${w.start}T00:00:00Z`); day < new Date(`${w.end}T00:00:00Z`); day.setUTCDate(day.getUTCDate()+1)) {
      if (!days.get(day.toISOString().slice(0,10))) return false
    }
    return w.start >= batch.start && w.end <= batch.end
  })
}

export async function requireCalculatedPeriods(windows: DateWindow[], batch: ReportBatch) {
  const nonempty=windows.filter(w=>w.start<w.end)
  if (!nonempty.length) return
  const coverage=await periodCoverage(nonempty,batch)
  if (coverage.some(ready=>!ready)) throw new DataUnavailableError("销售来源覆盖未完成", "order_coverage_incomplete")
  const [rows]=await getPool().query<(RowDataPacket & { period_start:string;period_end:string;grains:number })[]>(
    `SELECT period_start,period_end,COUNT(DISTINCT grain_type) grains FROM crm_report_denominator_status
     WHERE batch_id=? AND grain_key='' AND period_start>=? AND period_end<=? GROUP BY period_start,period_end`,
    [batch.dataId??batch.id,nonempty[0].start,nonempty.at(-1)!.end])
  const calculated=new Set(rows.filter(r=>Number(r.grains)===5).map(r=>`${r.period_start}|${r.period_end}`))
  if (nonempty.some(w=>!calculated.has(`${w.start}|${w.end}`))) {
    throw new DataUnavailableError("销售统计期间尚未计算完成", "order_period_incomplete")
  }
}

async function series(windows: DateWindow[], grain: Grain, field: "order_count" | "sales_qty", batch: ReportBatch, targeted = false): Promise<Series> {
  const sourceCoverage = await periodCoverage(windows, batch)
  const nativeGrain = grain === "aftersales_product_id" ? "sales_link" : grain
  const [periods] = await getPool().query<(RowDataPacket & { period_start: string; period_end: string; grain_key: string; is_complete: number })[]>(
    "SELECT period_start,period_end,grain_key,is_complete FROM crm_report_denominator_status WHERE batch_id=? AND grain_type=? AND period_start>=? AND period_end<=?",
    [batch.dataId ?? batch.id,nativeGrain,windows[0].start,windows.at(-1)!.end])
  const verified = new Set(periods.filter(row=>!row.grain_key && row.is_complete).map(row=>`${row.period_start}|${row.period_end}`))
  const invalid = new Set(periods.filter(row=>row.grain_key && !row.is_complete).map(row=>`${row.period_start}|${row.period_end}|${row.grain_key}`))
  const coverage = windows.map((window,i)=>(targeted || sourceCoverage[i]) && verified.has(`${window.start}|${window.end}`))
  const known = (key: string, i: number) => coverage[i] && !invalid.has(`${windows[i].start}|${windows[i].end}|${key}`)
  const [rows] = await getPool().query<(RowDataPacket & { grain_key: string; period_start: string; period_end: string; value: number })[]>(
    `SELECT grain_key, period_start, period_end, ${field} value FROM crm_report_orders
     WHERE batch_id=? AND grain_type=? AND period_start>=? AND period_end<=?`,
    [batch.dataId ?? batch.id, grain === "aftersales_product_id" ? "sales_link" : grain, windows[0].start, windows.at(-1)!.end])
  const result: Series = new Map()
  const index = new Map(windows.map((w,i) => [`${w.start}|${w.end}`,i]))
  for (const row of rows) {
    const i = index.get(`${row.period_start}|${row.period_end}`)
    if (i === undefined) continue
    const values = result.get(row.grain_key) ?? windows.map((_,n) => known(row.grain_key,n) ? 0 : null)
    values[i] = known(row.grain_key,i) ? Number(row.value) : null
    result.set(row.grain_key, values)
  }
  for (const row of periods) {
    if (row.grain_key && !result.has(row.grain_key)) result.set(row.grain_key, windows.map((_,i) => known(row.grain_key,i) ? 0 : null))
  }
  // An empty known-complete scope is a real zero; an absent scope is unknown.
  if (grain === "total" && !result.has("__all__")) result.set("__all__", windows.map((_,i) => known("__all__",i) ? 0 : null))
  result.set("", coverage.map(ok => ok ? 0 : null))
  return result
}

function unavailableSeries(w: DateWindow[]) { return w.map(() => null) }
async function productMetricSeries(windows: DateWindow[], field: "order_count" | "sales_qty", b: ReportBatch): Promise<Series> {
  const [rows]=await getPool().query<(RowDataPacket & { merchant_code:string;period_start:string;period_end:string;value:number|null })[]>(
    `SELECT merchant_code,period_start,period_end,${field} value FROM crm_report_product_metric
     WHERE batch_id=? AND period_start>=? AND period_end<=?`,
    [b.dataId??b.id,windows[0].start,windows.at(-1)!.end])
  const index=new Map(windows.map((window,i)=>[`${window.start}|${window.end}`,i]))
  const result:Series=new Map()
  for (const row of rows) {
    const i=index.get(`${row.period_start}|${row.period_end}`)
    if (i===undefined) continue
    const values=result.get(row.merchant_code)??unavailableSeries(windows)
    values[i]=row.value===null?null:Number(row.value)
    result.set(row.merchant_code,values)
  }
  result.set("",unavailableSeries(windows))
  return result
}
export async function totalOrderCounts(w: DateWindow[], _mode: PeriodMode, b: ReportBatch) { return b.salesCoverageApproved === false ? unavailableSeries(w) : (await series(w,"total","order_count",b)).get("__all__")! }
export async function totalSalesCounts(w: DateWindow[], _mode: PeriodMode, b: ReportBatch) { return b.salesCoverageApproved === false ? unavailableSeries(w) : (await series(w,"total","sales_qty",b)).get("__all__")! }
export async function groupedOrderCounts(w: DateWindow[], _mode: PeriodMode, grain: Exclude<Grain,"total">, b: ReportBatch) {
  if (grain === "merchant_code" && b.productMetricLayer) return productMetricSeries(w,"order_count",b)
  if (grain === "merchant_code" && b.productSalesCoverageApproved) return series(w,grain,"order_count",b,true)
  return b.salesCoverageApproved === false ? new Map<string,Array<number|null>>([["",unavailableSeries(w)]]) : series(w,grain,"order_count",b)
}
export async function groupedSalesCounts(w: DateWindow[], _mode: PeriodMode, grain: Exclude<Grain,"total">, b: ReportBatch) {
  if (grain === "merchant_code" && b.productMetricLayer) return productMetricSeries(w,"sales_qty",b)
  if (grain === "merchant_code" && b.productSalesCoverageApproved) return series(w,grain,"sales_qty",b,true)
  return b.salesCoverageApproved === false ? new Map<string,Array<number|null>>([["",unavailableSeries(w)]]) : series(w,grain,"sales_qty",b)
}

export async function confirmedDoudianProductIds(b: ReportBatch) {
  const [rows] = await getPool().query<(RowDataPacket & { product_id: string })[]>(
    "SELECT DISTINCT product_id FROM crm_report_issue WHERE batch_id=? AND platform='douyin' AND match_status='verified'", [b.dataId ?? b.id])
  return new Set(rows.map(r => r.product_id).filter(Boolean))
}
export async function latestCompleteOrderDay(b: ReportBatch): Promise<OrderWatermark> {
  if (!b.completeThrough) throw new DataUnavailableError("没有连续核验完成的订单日期", "order_coverage_incomplete")
  return { statDate: b.completeThrough, refreshedAt: b.syncedAt }
}
export async function latestProductOrderDay(b: ReportBatch): Promise<OrderWatermark | null> {
  return b.productOrderThrough ? { statDate: b.productOrderThrough, refreshedAt: b.syncedAt } : null
}

export async function issueRows(w: DateWindow[], _mode: PeriodMode, warehouseCode: string, b: ReportBatch): Promise<RawIssueRow[]> {
  requireReportScope(w,b)
  const [rows] = await getPool().query<(RowDataPacket & Record<string,string|number>)[]>(
    `SELECT source_system, COALESCE(NULLIF(merchant_code,''),'未填') code,
       MAX(product_title) name, product_id, denominator_key,
       COALESCE(NULLIF(problem1,''),'未分类') p1, COALESCE(NULLIF(problem2,''),'未填写') p2,
       COALESCE(NULLIF(problem3,''),'未填写') p3,
       ${w.map((_,i) => `SUM(CASE WHEN created_at>=? AND created_at<? THEN 1 ELSE 0 END) w${i}`).join(',')}
     FROM crm_report_issue WHERE batch_id=? AND created_at>=? AND created_at<?
       ${warehouseCode ? "AND warehouse_code=?" : ""}
     GROUP BY source_system,code,product_id,denominator_key,p1,p2,p3`,
    [...w.flatMap(x=>[x.start,x.end]),b.dataId ?? b.id,w[0].start,w.at(-1)!.end,...(warehouseCode?[warehouseCode]:[])])
  return rows.map(r => ({ sourceSystem: String(r.source_system), code: String(r.code), name: String(r.name || "未填"),
    productId: String(r.product_id || ""), denominatorKey: String(r.denominator_key || ""),
    p1: String(r.p1),p2: String(r.p2),p3: String(r.p3),counts:w.map((_,i)=>Number(r[`w${i}`]||0)) }))
}
export async function createdIssueRows(w: DateWindow[], b: ReportBatch, warehouseCode = "") { return issueRows(w,"closed",warehouseCode,b) }
export async function earliestCreatedIssueDate(b: ReportBatch): Promise<string|null> {
  return b.earliestCreatedAt
}
export async function warehouseIssueRows(w: DateWindow[], _mode: PeriodMode, b: ReportBatch): Promise<RawWarehouseRow[]> {
  requireReportScope(w,b)
  const [rows] = await getPool().query<(RowDataPacket & Record<string,string|number>)[]>(
    `SELECT COALESCE(NULLIF(warehouse_code,''),'未填') warehouse_code, MAX(warehouse_name) warehouse_name,
      ${w.map((_,i)=>`SUM(CASE WHEN created_at>=? AND created_at<? THEN 1 ELSE 0 END) w${i}`).join(',')}
     FROM crm_report_issue WHERE batch_id=? AND created_at>=? AND created_at<?
       AND problem1='库房问题' AND NOT EXISTS (
         SELECT 1 FROM JSON_TABLE(?, '$[*]' COLUMNS (
           p1 VARCHAR(255) PATH '$.p1', p2 VARCHAR(255) PATH '$.p2',
           p3 VARCHAR(255) PATH '$.p3', enabled INT PATH '$.enabled'
         )) rule_snapshot WHERE rule_snapshot.enabled=1 AND rule_snapshot.p1=problem1
           AND rule_snapshot.p2=COALESCE(NULLIF(problem2,''),'未填写')
           AND rule_snapshot.p3 IN ('*',COALESCE(NULLIF(problem3,''),'未填写'))
       ) GROUP BY warehouse_code`,
    [...w.flatMap(x=>[x.start,x.end]),b.dataId ?? b.id,w[0].start,w.at(-1)!.end,JSON.stringify(b.rules)])
  return rows.map(r=>({warehouseCode:String(r.warehouse_code),warehouseName:String(r.warehouse_name||""),counts:w.map((_,i)=>Number(r[`w${i}`]||0))}))
}
export async function sourceSnapshot(b: ReportBatch): Promise<SourceSnapshot> {
  const pending=b.verification === "candidate" || b.issueCoverageApproved !== true
  return { syncedAt:b.syncedAt,apiRows:b.issueCount,coverageStart:b.start,coverageEnd:b.end,batchId:b.id,reconciliationStatus:pending ? "pending" : "approved" }
}
