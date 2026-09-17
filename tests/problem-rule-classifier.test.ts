import { describe, expect, it } from "vitest"

import { classifyIssue, exclusionRuleIndex } from "@/src/modules/problem-rules/classifier"
import { defaultExclusionRules } from "@/src/modules/problem-rules/defaults"
import type { ExclusionRule } from "@/src/modules/problem-rules/types"

const baseIssue = {
  sourceSystem: "test",
  code: "YY-001",
  name: "测试产品",
  productId: "700001",
  p1: "产品问题",
  p2: "口味问题",
  p3: "待人工判断",
  counts: [1, 2],
}

function classify(overrides: Partial<typeof baseIssue> = {}, rules: ExclusionRule[] = defaultExclusionRules) {
  return classifyIssue({ ...baseIssue, ...overrides }, exclusionRuleIndex(rules))
}

describe("五大问题分类与可剔除规则", () => {
  it("只包含业务确认的六条可剔除规则", () => {
    expect(defaultExclusionRules).toHaveLength(6)
    expect(defaultExclusionRules).toEqual(expect.arrayContaining([
      expect.objectContaining({ p1: "快递问题", p2: "顾客退款", p3: "*" }),
      expect.objectContaining({ p1: "快递问题", p2: "签收未收到", p3: "需派件上门" }),
      expect.objectContaining({ p1: "快递问题", p2: "物流延迟", p3: "需催件" }),
      expect.objectContaining({ p1: "买家问题", p2: "无理由退", p3: "*" }),
    ]))
  })

  it("五大分类内未列入清单的问题默认纳入统计", () => {
    const result = classify()
    expect(result.category).toBe("产品问题")
    expect(result.classificationStatus).toBe("included")
    expect(result.includedInOperating).toBe(true)
  })

  it("二级通配规则剔除该二级下的所有三级问题", () => {
    expect(classify({ p1: "快递问题", p2: "顾客退款", p3: "拦截" }).classificationStatus).toBe("excluded")
    expect(classify({ p1: "快递问题", p2: "顾客退款", p3: "需退回" }).includedInOperating).toBe(false)
    expect(classify({ p1: "买家问题", p2: "无理由退", p3: "待人工判断" }).classificationStatus).toBe("excluded")
  })

  it("三级精确规则不误伤同一二级下的其他问题", () => {
    expect(classify({ p1: "快递问题", p2: "签收未收到", p3: "需派件上门" }).classificationStatus).toBe("excluded")
    expect(classify({ p1: "快递问题", p2: "签收未收到", p3: "找到退回" }).classificationStatus).toBe("included")
    expect(classify({ p1: "快递问题", p2: "物流延迟", p3: "需催件" }).classificationStatus).toBe("excluded")
    expect(classify({ p1: "快递问题", p2: "物流延迟", p3: "要求理赔" }).classificationStatus).toBe("included")
  })

  it("未确认的一级问题保留为待归类并不进入统计", () => {
    const result = classify({ p1: "平台介入", p2: "仅退款", p3: "未填写" })
    expect(result.category).toBeNull()
    expect(result.classificationStatus).toBe("unclassified")
    expect(result.includedInOperating).toBe(false)
  })

  it("停用可剔除规则后记录恢复纳入统计", () => {
    const rules = defaultExclusionRules.map((rule) => ({ ...rule, enabled: false }))
    const result = classify({ p1: "快递问题", p2: "改地址", p3: "待人工判断" }, rules)
    expect(result.classificationStatus).toBe("included")
    expect(result.includedInOperating).toBe(true)
  })
})
