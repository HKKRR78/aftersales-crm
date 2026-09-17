"use client"

import { Search, SlidersHorizontal } from "lucide-react"
import { useActionState, useDeferredValue, useState } from "react"

import { problemCategories, type ExclusionRule } from "@/src/modules/problem-rules/types"

import { updateExclusionRule, type RuleActionState } from "./actions"

const initialState: RuleActionState = { status: "idle", message: "" }

export function RuleEditor({ rules, fixture }: { rules: ExclusionRule[]; fixture: boolean }) {
  const [query, setQuery] = useState("")
  const deferredQuery = useDeferredValue(query.trim().toLocaleLowerCase("zh-CN"))
  const visibleRules = deferredQuery
    ? rules.filter((rule) => [rule.p1, rule.p2, rule.p3, rule.note]
      .some((value) => value.toLocaleLowerCase("zh-CN").includes(deferredQuery)))
    : rules
  const enabled = rules.filter((rule) => rule.enabled).length
  return (
    <>
      <section className="settings-summary" aria-label="规则概览">
        <span><strong>{problemCategories.length}</strong><small>固定业务分类</small></span>
        <span><strong>{rules.length}</strong><small>可剔除规则</small></span>
        <span><strong>{enabled}</strong><small>当前启用</small></span>
        <label><Search aria-hidden="true" size={16} /><span className="sr-only">搜索可剔除规则</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索一级、二级、三级问题…" /></label>
      </section>
      <p className="settings-notice">一级问题直接归入五大分类。以下规则只控制是否进入经营统计；被剔除记录仍保留在全量售后和 Excel 中。</p>
      {fixture ? <p className="settings-notice">当前使用本地验收数据，可以查看交互，但不会写入规则库。</p> : null}
      <section className="rule-list" aria-label="可剔除规则列表">
        {visibleRules.map((rule) => <RuleForm fixture={fixture} key={`${rule.p1}|${rule.p2}|${rule.p3}`} rule={rule} />)}
      </section>
    </>
  )
}

function RuleForm({ rule, fixture }: { rule: ExclusionRule; fixture: boolean }) {
  const [state, action, pending] = useActionState(updateExclusionRule, initialState)
  return (
    <form action={action} className="rule-card">
      <input name="p1" type="hidden" value={rule.p1} />
      <input name="p2" type="hidden" value={rule.p2} />
      <input name="p3" type="hidden" value={rule.p3} />
      <div className="rule-path"><SlidersHorizontal aria-hidden="true" size={16} /><span>{rule.p1}</span><i>›</i><span>{rule.p2}</span><i>›</i><strong>{rule.p3 === "*" ? "全部三级" : rule.p3}</strong></div>
      <div className="rule-fields exclusion-rule-fields">
        <label className="rule-note"><span>规则说明</span><input defaultValue={rule.note} name="note" /></label>
      </div>
      <div className="rule-switches">
        <label><input defaultChecked={rule.enabled} name="is_enabled" type="checkbox" /><span>启用可剔除规则</span></label>
        <button disabled={pending || fixture} type="submit">{pending ? "保存中…" : "保存规则"}</button>
      </div>
      {state.message ? <p aria-live="polite" className={`rule-message ${state.status}`}>{state.message}</p> : null}
    </form>
  )
}
