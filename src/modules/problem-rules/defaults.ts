import rawRules from "@/config/aftersales-exclusion-rules.json"

import type { ExclusionRule } from "./types"

export const defaultExclusionRules: ExclusionRule[] = rawRules.map((rule) => ({
  ...rule,
  enabled: true,
})) as ExclusionRule[]
