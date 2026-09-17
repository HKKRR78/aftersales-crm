"use server"

import { updateTag } from "next/cache"

import { currentUser } from "@/src/auth/current-user"
import { isDevFixtureMode } from "@/src/modules/analytics/dev-mode"
import { defaultExclusionRules } from "@/src/modules/problem-rules/defaults"
import { saveExclusionRule } from "@/src/modules/problem-rules/repository"
import { exclusionRuleKey, type ExclusionRule } from "@/src/modules/problem-rules/types"

export interface RuleActionState {
  status: "idle" | "success" | "error"
  message: string
}

const allowedRuleKeys = new Set(defaultExclusionRules.map((rule) => exclusionRuleKey(rule.p1, rule.p2, rule.p3)))

function value(formData: FormData, key: string) {
  return String(formData.get(key) || "").trim()
}

export async function updateExclusionRule(
  _previousState: RuleActionState,
  formData: FormData,
): Promise<RuleActionState> {
  const user = await currentUser()
  if (user.role !== "admin") return { status: "error", message: "只有管理员可以修改可剔除规则" }
  if (isDevFixtureMode()) return { status: "error", message: "本地验收数据不会写入规则库" }

  const rule = {
    p1: value(formData, "p1"),
    p2: value(formData, "p2"),
    p3: value(formData, "p3"),
    note: value(formData, "note"),
    enabled: formData.has("is_enabled"),
  } as ExclusionRule
  if (!allowedRuleKeys.has(exclusionRuleKey(rule.p1, rule.p2, rule.p3))) {
    return { status: "error", message: "该规则不在已确认的可剔除清单中" }
  }
  try {
    await saveExclusionRule(rule, user.id)
    updateTag("aftersales-dashboard")
    return { status: "success", message: "可剔除规则已保存，统计口径已刷新" }
  } catch {
    return { status: "error", message: "规则保存失败，请稍后重试" }
  }
}
