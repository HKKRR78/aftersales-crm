import { beforeEach, describe, expect, it, vi } from "vitest"
import { analysisWindows, loadCreatedIssueData } from "@/src/modules/analytics/service"
import { createdIssueRows, latestCompleteOrderDay } from "@/src/modules/analytics/repository"
import type { ReportBatch } from "@/src/modules/analytics/repository"

vi.mock("server-only", () => ({}))
vi.mock("next/cache", () => ({ cacheLife: vi.fn(), cacheTag: vi.fn() }))
vi.mock("@/src/modules/analytics/repository", () => ({
  createdIssueRows: vi.fn(), confirmedDoudianProductIds: vi.fn(async () => new Set()),
  earliestCreatedIssueDate: vi.fn(async () => "2026-05-31"),
  latestCompleteOrderDay: vi.fn(),
}))
const batch: ReportBatch = { id: "candidate", start: "2026-07-05", end: "2026-09-16", syncedAt: "2026-09-16",
  issueCount: 1, rules: [], completeThrough: "", earliestCreatedAt: "2026-05-31", verification: "candidate" }

describe("created-week drilldown warehouse scope", () => {
  beforeEach(() => { vi.mocked(createdIssueRows).mockReset() })
  it("reads the selected warehouse in the same two occurrence weeks and keeps missing warehouses empty", async () => {
    vi.mocked(createdIssueRows).mockResolvedValue([])
    const result = await loadCreatedIssueData("2026-09-06", new Date(2026,8,16), batch, "absent-warehouse")
    expect(vi.mocked(createdIssueRows).mock.calls[0]).toEqual([
      [{start:"2026-08-30",end:"2026-09-06",label:"0830-0905"},{start:"2026-09-06",end:"2026-09-13",label:"0906-0912"}],
      batch,"absent-warehouse",
    ])
    expect(result.issueRows).toEqual([])
    expect(result.batchId).toBe(batch.id)
  })
  it("pins a verified partial report's progress comparison to the batch endpoint", async () => {
    const partial={...batch,verification:"verified" as const,verificationKind:"issues_full_denominators_partial",issueCoverageApproved:true,salesCoverageApproved:false}
    const result=await analysisWindows("progress",new Date(2026,8,17),partial)
    expect(latestCompleteOrderDay).not.toHaveBeenCalled()
    expect(result.orderWatermark).toBeNull()
    expect(result.windows.map(window=>[window.start,window.end])).toEqual([
      ["2026-09-06","2026-09-09"],
      ["2026-09-13","2026-09-16"],
    ])
  })
})
