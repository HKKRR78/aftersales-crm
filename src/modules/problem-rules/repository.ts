import "server-only"
import { randomUUID } from "node:crypto"

import type { ResultSetHeader, RowDataPacket } from "mysql2"

import { getPool } from "@/src/db/mysql"

import type { ExclusionRule } from "./types"
import { classifyIssue, exclusionRuleIndex } from "./classifier"

type ExclusionRuleRow = RowDataPacket & {
  problem1: ExclusionRule["p1"]
  problem2: string
  problem3_pattern: string
  note: string
  is_enabled: number
  updated_by: string
  updated_at: string
}

export async function loadExclusionRules(): Promise<ExclusionRule[]> {
  const [rows] = await getPool().query<ExclusionRuleRow[]>(
    `SELECT problem1, problem2, problem3_pattern, note, is_enabled, updated_by, updated_at
     FROM dim_crm_exclusion_rule
     ORDER BY problem1, problem2, problem3_pattern`,
  )
  return rows.map((row) => ({
    p1: row.problem1,
    p2: String(row.problem2 || ""),
    p3: String(row.problem3_pattern || "*"),
    note: String(row.note || ""),
    enabled: Boolean(row.is_enabled),
    updatedBy: String(row.updated_by || ""),
    updatedAt: String(row.updated_at || ""),
  }))
}

export async function saveExclusionRule(rule: ExclusionRule, userId: string) {
  const conn = await getPool().getConnection()
  try {
    await conn.beginTransaction()
    const [current] = await conn.query<RowDataPacket[]>(
      `SELECT b.* FROM crm_report_current c JOIN crm_report_batch b ON b.batch_id=c.batch_id
       WHERE c.singleton=1 FOR UPDATE`)
    const [result] = await conn.execute<ResultSetHeader>(
      `UPDATE dim_crm_exclusion_rule SET note=?, is_enabled=?, updated_by=?
       WHERE problem1=? AND problem2=? AND problem3_pattern=?`,
      [rule.note, Number(rule.enabled), userId, rule.p1, rule.p2, rule.p3])
    if (result.affectedRows !== 1) throw new Error("Exclusion rule does not exist")
    if (current.length) {
      const previous = current[0]
      if (previous.status !== "verified") throw new Error("Current report is not verified")
      const [rows] = await conn.query<ExclusionRuleRow[]>("SELECT * FROM dim_crm_exclusion_rule ORDER BY problem1,problem2,problem3_pattern")
      const summary = JSON.parse(previous.summary_json)
      summary.rules = rows.map(row => ({ p1: row.problem1, p2: row.problem2, p3: row.problem3_pattern,
        note: row.note, enabled: Boolean(row.is_enabled), updatedBy: row.updated_by, updatedAt: String(row.updated_at) }))
      // New immutable report metadata shares the already-verified facts and
      // denominators. Changing a rule does not duplicate millions of rows.
      summary.dataBatchId = summary.dataBatchId || previous.batch_id
      summary.previousReport = previous.batch_id
      summary.ruleChangeBy = userId
      // Only classification changes. Preserve the verified source scope and
      // observation time rather than presenting the rule save as a source read.
      summary.verificationKind = "rules_on_verified_facts"
      summary.sourceVerificationReport = summary.sourceVerificationReport || previous.batch_id
      const [groups] = await conn.query<(RowDataPacket & { p1: string; p2: string; p3: string; matched: number; unmatched: number })[]>(
        `SELECT problem1 p1,COALESCE(NULLIF(problem2,''),'未填写') p2,
           COALESCE(NULLIF(problem3,''),'未填写') p3,
           SUM(merchant_code<>'') matched,SUM(merchant_code='') unmatched
         FROM crm_report_issue WHERE batch_id=? GROUP BY p1,p2,p3`, [summary.dataBatchId])
      const index = exclusionRuleIndex(summary.rules)
      const counts = { operating: 0, matchedOperating: 0, unmatchedOperating: 0 }
      for (const group of groups) {
        const row = { sourceSystem: "", code: "", name: "", productId: "", denominatorKey: "",
          p1: group.p1, p2: group.p2, p3: group.p3, counts: [] }
        if (!classifyIssue(row, index).includedInOperating) continue
        counts.matchedOperating += Number(group.matched)
        counts.unmatchedOperating += Number(group.unmatched)
      }
      counts.operating = counts.matchedOperating + counts.unmatchedOperating
      summary.quantityConservation = counts
      const id = `rules_${randomUUID()}`
      await conn.execute(
        `INSERT INTO crm_report_batch(batch_id,status,started_at,completed_at,coverage_start,coverage_end,
           source_batch_id,source_synced_at,issue_count,summary_json,evidence_path)
         VALUES(?,'verified',NOW(),NOW(),?,?,?,?,?,?,?)`,
        [id,previous.coverage_start,previous.coverage_end,previous.source_batch_id,previous.source_synced_at,
          previous.issue_count,JSON.stringify(summary),previous.evidence_path])
      await conn.execute("UPDATE crm_report_current SET batch_id=?,published_at=NOW() WHERE singleton=1",[id])
    }
    await conn.commit()
  } catch (error) {
    await conn.rollback()
    throw error
  } finally {
    conn.release()
  }
}
