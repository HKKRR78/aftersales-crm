import { beforeEach, describe, expect, it, vi } from "vitest"
import { getPool } from "@/src/db/mysql"
import { createdIssueRows, earliestCreatedIssueDate, groupedOrderCounts, groupedSalesCounts, issueRows, latestCompleteOrderDay, reportBatch, requireCalculatedPeriods, sourceSnapshot, totalOrderCounts, warehouseIssueRows, type ReportBatch } from "@/src/modules/analytics/repository"
vi.mock("@/src/db/mysql", () => ({ getPool: vi.fn() }))
vi.mock("server-only", () => ({}))
const query=vi.fn()
const batch:ReportBatch={id:"immutable-a",start:"2026-06-07",end:"2026-09-16",syncedAt:"2026-09-16",issueCount:10,rules:[],completeThrough:"2026-09-15",earliestCreatedAt:"2026-05-31"}
const windows=[{start:"2026-09-06",end:"2026-09-08",label:"同期"}]
describe("verified immutable report reads",()=>{
  beforeEach(()=>{vi.unstubAllEnvs();query.mockReset();vi.mocked(getPool).mockReturnValue({query} as never)})
  it("allows only the explicitly pinned acceptance candidate and marks it pending",async()=>{
    vi.stubEnv("CRM_REPORT_PREVIEW_BATCH_ID","isolated-candidate")
    query.mockResolvedValueOnce([[{batch_id:"isolated-candidate",status:"candidate",summary_json:JSON.stringify({rules:[],earliestCreatedAt:"2026-05-31"})}]])
    const preview=await reportBatch()
    expect(query.mock.calls[0][1]).toEqual(["isolated-candidate"])
    expect((await sourceSnapshot(preview)).reconciliationStatus).toBe("pending")
    query.mockResolvedValueOnce([[]])
    await expect(reportBatch("another-unverified-batch")).rejects.toMatchObject({code:"report_batch_unavailable"})
    expect(query.mock.calls[1][0]).toContain("b.status='verified'")
  })
  it("ignores a stale URL batch in production and follows the current pointer",async()=>{
    query.mockResolvedValueOnce([[{batch_id:"current-batch",status:"verified",coverage_start:"2026-07-05",coverage_end:"2026-09-17",
      source_synced_at:"2026-09-17",issue_count:10,summary_json:JSON.stringify({rules:[],earliestCreatedAt:"2026-07-05"})}]])
    const current=await reportBatch("retired-batch-from-url")
    expect(current.id).toBe("current-batch")
    expect(query.mock.calls[0][0]).toContain("JOIN crm_report_current")
    expect(query.mock.calls[0][1]).toEqual([])
  })
  it("marks verified issue facts approved while keeping denominators unavailable",async()=>{
    query.mockResolvedValueOnce([[{batch_id:"partial",status:"verified",coverage_start:"2026-07-05",coverage_end:"2026-09-16",
      source_synced_at:"2026-09-16",issue_count:10,summary_json:JSON.stringify({rules:[],earliestCreatedAt:"2026-07-05",
        verificationKind:"issues_full_denominators_partial",issueCoverageApproved:true,salesCoverageApproved:false})}]])
    const partial=await reportBatch("partial")
    expect((await sourceSnapshot(partial)).reconciliationStatus).toBe("approved")
    expect(await totalOrderCounts(windows,"closed",partial)).toEqual([null])
    expect(query).toHaveBeenCalledTimes(1)
  })
  it("keeps a rules-only successor of a partial release visibly pending",async()=>{
    query.mockResolvedValueOnce([[{batch_id:"rules",status:"verified",coverage_start:"2026-07-05",coverage_end:"2026-09-16",
      source_synced_at:"2026-09-16",issue_count:10,summary_json:JSON.stringify({rules:[],earliestCreatedAt:"2026-07-05",
        verificationKind:"rules_on_verified_facts"})}]])
    const rules=await reportBatch("rules")
    expect((await sourceSnapshot(rules)).reconciliationStatus).toBe("pending")
  })
  it("accepts a verified zero, without adding daily distinct orders",async()=>{
    query.mockResolvedValueOnce([[{stat_date:"2026-09-06",ready:1},{stat_date:"2026-09-07",ready:1}]])
    query.mockResolvedValueOnce([[{period_start:"2026-09-06",period_end:"2026-09-08",is_complete:1}]])
    query.mockResolvedValueOnce([[{grain_key:"__all__",period_start:"2026-09-06",period_end:"2026-09-08",value:0}]])
    expect(await totalOrderCounts(windows,"progress",batch)).toEqual([0])
    expect(query.mock.calls[2][0]).toContain("crm_report_orders")
  })
  it("does not publish a partial denominator or infer coverage from max date",async()=>{
    query.mockResolvedValueOnce([[{stat_date:"2026-09-07",ready:1}]])
    query.mockResolvedValueOnce([[{period_start:"2026-09-06",period_end:"2026-09-08",is_complete:1}]])
    query.mockResolvedValueOnce([[{grain_key:"__all__",period_start:"2026-09-06",period_end:"2026-09-08",value:999}]])
    expect(await totalOrderCounts(windows,"progress",batch)).toEqual([null])
  })
  it("keeps an uncertain spec unknown even when no shipped order row exists",async()=>{
    query.mockResolvedValueOnce([[{stat_date:"2026-09-06",ready:1},{stat_date:"2026-09-07",ready:1}]])
    query.mockResolvedValueOnce([[
      {period_start:"2026-09-06",period_end:"2026-09-08",grain_key:"",is_complete:1},
      {period_start:"2026-09-06",period_end:"2026-09-08",grain_key:"A*3",is_complete:0},
    ]])
    query.mockResolvedValueOnce([[{grain_key:"A*6",period_start:"2026-09-06",period_end:"2026-09-08",value:12}]])
    const values=await groupedOrderCounts(windows,"progress","merchant_code",batch)
    expect(values.get("A*3")).toEqual([null])
    expect(values.get("A*6")).toEqual([12])
    expect(values.get("")).toEqual([0])
  })
  it("shows only frozen positive sales while keeping orders and rates unavailable",async()=>{
    const frozen={...batch,productMetricLayer:true,productOrderThrough:"2026-09-12"}
    query.mockResolvedValueOnce([[{merchant_code:"A*3",period_start:"2026-09-06",period_end:"2026-09-08",value:null}]])
    expect((await groupedOrderCounts(windows,"progress","merchant_code",frozen)).get("A*3")).toEqual([null])
    query.mockResolvedValueOnce([[{merchant_code:"A*3",period_start:"2026-09-06",period_end:"2026-09-08",value:321}]])
    expect((await groupedSalesCounts(windows,"progress","merchant_code",frozen)).get("A*3")).toEqual([321])
    expect(query.mock.calls[0][0]).toContain("crm_report_product_metric")
  })
  it("uses created time and pinned batch for both entry points",async()=>{
    query.mockResolvedValue([[]])
    await issueRows(windows,"closed","",batch)
    await createdIssueRows(windows,batch)
    expect(query.mock.calls[0]).toEqual(query.mock.calls[1])
    expect(query.mock.calls[0][0]).toContain("created_at>=?")
    expect(query.mock.calls[0][0]).not.toContain("wdt_pay_time")
    expect(query.mock.calls[0][1]).toContain(batch.id)
  })
  it("uses the verified continuous coverage boundary",async()=>{
    expect(await latestCompleteOrderDay(batch)).toEqual({statDate:"2026-09-15",refreshedAt:batch.syncedAt})
    await expect(latestCompleteOrderDay({...batch,completeThrough:""})).rejects.toMatchObject({code:"order_coverage_incomplete"})
  })
  it("uses the same snapshotted exclusions in warehouse counts",async()=>{
    query.mockResolvedValue([[]]);await warehouseIssueRows(windows,"closed",batch)
    expect(query.mock.calls[0][0]).toContain("JSON_TABLE")
    expect(query.mock.calls[0][1].at(-1)).toEqual(JSON.stringify(batch.rules))
    expect(query.mock.calls[0][0]).not.toContain("dim_crm_exclusion_rule")
  })
  it("rejects an unavailable batch without the obsolete algorithm",async()=>{
    query.mockResolvedValue([[]]);await expect(reportBatch("unpublished")).rejects.toMatchObject({code:"report_batch_unavailable"})
    expect(query.mock.calls[0][0]).toContain("b.status='verified'")
  })
  it("does not turn an older unverified period into zero issues",async()=>{
    await expect(issueRows([{start:"2026-05-31",end:"2026-06-07",label:"old"}],"closed","",batch))
      .rejects.toMatchObject({code:"report_period_unverified"})
    expect(query).not.toHaveBeenCalled()
  })
  it("keeps historical week choices without claiming they are verified",async()=>{
    expect(await earliestCreatedIssueDate(batch)).toEqual("2026-05-31")
    expect(query).not.toHaveBeenCalled()
  })
  it("treats Sunday with no completed days as an empty comparison, not source failure",async()=>{
    await requireCalculatedPeriods([{start:"2026-09-13",end:"2026-09-13",label:"无完整日"}],batch)
    expect(query).not.toHaveBeenCalled()
  })
  it("requires source coverage and all calculated grains, while permitting documented unknown values",async()=>{
    query.mockResolvedValueOnce([[{stat_date:"2026-09-06",ready:1},{stat_date:"2026-09-07",ready:1}]])
    query.mockResolvedValueOnce([[{period_start:"2026-09-06",period_end:"2026-09-08",grains:5}]])
    await requireCalculatedPeriods(windows,batch)
    expect(query.mock.calls[1][0]).not.toContain("is_complete=1")
    query.mockResolvedValueOnce([[{stat_date:"2026-09-06",ready:1}]])
    await expect(requireCalculatedPeriods(windows,batch)).rejects.toMatchObject({code:"order_coverage_incomplete"})
    query.mockResolvedValueOnce([[{stat_date:"2026-09-06",ready:1},{stat_date:"2026-09-07",ready:1}]])
    query.mockResolvedValueOnce([[]])
    await expect(requireCalculatedPeriods(windows,batch)).rejects.toMatchObject({code:"order_period_incomplete"})
  })
})
