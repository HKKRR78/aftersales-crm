import { beforeEach, describe, expect, it, vi } from "vitest"
import { getPool } from "@/src/db/mysql"
import { saveExclusionRule } from "@/src/modules/problem-rules/repository"

vi.mock("server-only", () => ({}))
vi.mock("@/src/db/mysql", () => ({ getPool: vi.fn() }))

const conn = { beginTransaction: vi.fn(), query: vi.fn(), execute: vi.fn(), commit: vi.fn(), rollback: vi.fn(), release: vi.fn() }
const rule = { p1: "买家问题" as const, p2: "退款", p3: "*", note: "", enabled: false, updatedBy: "employee", updatedAt: "2026-09-16" }
const previous = { batch_id: "old", status: "verified", coverage_start: "2026-06-07", coverage_end: "2026-09-16",
  source_batch_id: "source", source_synced_at: "2026-09-16", issue_count: 42, evidence_path: "/evidence",
  summary_json: JSON.stringify({ rules: [], completeThrough: "2026-09-15", dataBatchId: "original-data" }) }

describe("rule edits and immutable report publication", () => {
  beforeEach(() => {
    for (const mock of Object.values(conn)) mock.mockReset()
    vi.mocked(getPool).mockReturnValue({ getConnection: async () => conn } as never)
    conn.query.mockResolvedValueOnce([[previous]]).mockResolvedValueOnce([[{
      problem1: rule.p1, problem2: rule.p2, problem3_pattern: rule.p3, note: rule.note,
      is_enabled: 0, updated_by: "employee", updated_at: "2026-09-16",
    }]]).mockResolvedValueOnce([[{p1:"买家问题",p2:"退款",p3:"未填写",matched:6,unmatched:2},
      {p1:"未分类",p2:"未填写",p3:"未填写",matched:99,unmatched:1}]])
    conn.execute.mockResolvedValue([{ affectedRows: 1 }])
  })
  it("publishes a new rule snapshot sharing the same verified facts", async () => {
    await saveExclusionRule(rule, "employee")
    const summary = JSON.parse(conn.execute.mock.calls[1][1][6])
    expect(summary.dataBatchId).toBe("original-data")
    expect(summary.previousReport).toBe("old")
    expect(summary.rules[0].enabled).toBe(false)
    expect(summary.quantityConservation).toEqual({operating:8,matchedOperating:6,unmatchedOperating:2})
    expect(summary.verificationKind).toBe("rules_on_verified_facts")
    expect(summary.sourceVerificationReport).toBe("old")
    expect(conn.commit).toHaveBeenCalledOnce()
    expect(conn.rollback).not.toHaveBeenCalled()
    expect(conn.release).toHaveBeenCalledOnce()
  })
  it("rolls back the rule change if snapshot publication fails", async () => {
    conn.execute.mockResolvedValueOnce([{ affectedRows: 1 }]).mockRejectedValueOnce(new Error("storage failure"))
    await expect(saveExclusionRule(rule, "employee")).rejects.toThrow("storage failure")
    expect(conn.commit).not.toHaveBeenCalled()
    expect(conn.rollback).toHaveBeenCalledOnce()
    expect(conn.release).toHaveBeenCalledOnce()
    expect(conn.execute.mock.calls.some(call => call[0].startsWith("UPDATE crm_report_current"))).toBe(false)
  })
})
