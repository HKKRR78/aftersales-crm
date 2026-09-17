import { ShieldCheck } from "lucide-react"
import { Suspense } from "react"

import { currentUser } from "@/src/auth/current-user"
import { RouteLoading } from "@/src/components/route-loading"
import { isDevFixtureMode } from "@/src/modules/analytics/dev-mode"
import { defaultExclusionRules } from "@/src/modules/problem-rules/defaults"
import { loadExclusionRules } from "@/src/modules/problem-rules/repository"

import { RuleEditor } from "./rule-editor"

export default function SettingsPage() {
  return <Suspense fallback={<RouteLoading />}><SettingsContent /></Suspense>
}

async function SettingsContent() {
  const user = await currentUser()
  return (
    <>
      <div className="page-heading">
        <div><span className="eyebrow">PROBLEM GOVERNANCE</span><h2>问题分类与可剔除规则</h2><p>五大分类由一级问题直接确定；可剔除项独立控制经营统计范围。</p></div>
      </div>
      {user.role !== "admin" ? (
        <section className="permission-panel"><ShieldCheck aria-hidden="true" size={24} /><div><h3>仅管理员可访问</h3><p>可剔除规则会改变首页、产品、仓库和趋势统计口径。</p></div></section>
      ) : <RuleEditor fixture={isDevFixtureMode()} rules={isDevFixtureMode() ? defaultExclusionRules : await loadExclusionRules()} />}
    </>
  )
}
