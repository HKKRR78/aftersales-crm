export const problemCategories = [
  "快递问题",
  "库房问题",
  "买家问题",
  "产品问题",
  "运营问题",
] as const

export type ProblemCategory = typeof problemCategories[number]
export type IssueClassificationStatus = "included" | "excluded" | "unclassified"

export interface ExclusionRule {
  p1: ProblemCategory
  p2: string
  p3: string
  note: string
  enabled: boolean
  updatedBy?: string
  updatedAt?: string
}

export function exclusionRuleKey(p1: string, p2: string, p3: string) {
  return `${p1.trim()}\u001f${p2.trim()}\u001f${p3.trim() || "未填写"}`
}

export function isProblemCategory(value: string): value is ProblemCategory {
  return (problemCategories as readonly string[]).includes(value.trim())
}
