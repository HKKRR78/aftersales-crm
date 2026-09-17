import type { RawIssueRow } from "@/src/modules/analytics/types"

import type { ExclusionRule, IssueClassificationStatus, ProblemCategory } from "./types"
import { exclusionRuleKey, isProblemCategory } from "./types"

export interface ClassifiedIssue extends RawIssueRow {
  category: ProblemCategory | null
  classificationStatus: IssueClassificationStatus
  includedInOperating: boolean
}

export function exclusionRuleIndex(rules: ExclusionRule[]) {
  return new Map(
    rules
      .filter((rule) => rule.enabled)
      .map((rule) => [exclusionRuleKey(rule.p1, rule.p2, rule.p3), rule]),
  )
}

export function classifyIssue(row: RawIssueRow, index: Map<string, ExclusionRule>): ClassifiedIssue {
  const category = isProblemCategory(row.p1) ? row.p1 : null
  if (!category) {
    return { ...row, category: null, classificationStatus: "unclassified", includedInOperating: false }
  }

  const p3 = row.p3.trim() || "未填写"
  const excluded = index.has(exclusionRuleKey(category, row.p2, p3))
    || index.has(exclusionRuleKey(category, row.p2, "*"))
  return {
    ...row,
    category,
    classificationStatus: excluded ? "excluded" : "included",
    includedInOperating: !excluded,
  }
}
