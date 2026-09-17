import { filterIssueRows, issueFilterEntries, issueFiltersFromSearch, summarizeIssueRows, type SearchValues } from "@/src/modules/analytics/filters"
import type { DashboardData } from "@/src/modules/analytics/types"

import { ExportLink } from "./export-link"
import { formatCount } from "./format"
import { LiveIssueFilters } from "./live-issue-filters"
import { VirtualIssueTable } from "./virtual-issue-table"

export function IssueWorkbench({
  data,
  query,
  action,
  title = "售后问题分析明细",
  eyebrow = "AFTERSALES WORKBENCH",
  basis = "payment",
  weekStart = "",
}: {
  data: Pick<DashboardData, "issueRows" | "mode" | "weeks"> & { batchId?: string; source?: { batchId?: string } }
  query: SearchValues
  action: "/" | "/detail"
  title?: string
  eyebrow?: string
  basis?: "payment" | "created"
  weekStart?: string
}) {
  const filters = issueFiltersFromSearch(query)
  const auditRows = filterIssueRows(data.issueRows, { ...filters, scope: "all" })
  const audit = summarizeIssueRows(auditRows)
  const rows = filterIssueRows(data.issueRows, filters)
  const initialRows = rows.slice(0, 160)
  const productRows = data.issueRows.filter((row) => filters.scope === "all" || row.includedInOperating)
  const products = [...new Map(productRows.map((row) => [row.code, { value: row.code, label: `${row.name} · ${row.code}` }])).values()]
    .sort((a, b) => a.label.localeCompare(b.label, "zh-CN"))
  const productScope = productRows.filter((row) => !filters.merchantCode || row.code === filters.merchantCode)
  const links = [...new Map(productScope.filter((row) => row.productId).map((row) => [row.productId, {
    value: row.productId,
    label: `${row.productId}${row.doudianProductId ? " · 抖店已确认" : " · 售后来源"}`,
  }])).values()].sort((a, b) => a.label.localeCompare(b.label, "zh-CN"))
  const linkScope = productScope.filter((row) => !filters.productId || row.productId === filters.productId)
  const categories = [...new Set(linkScope.map((row) => row.p1))].sort((a, b) => a.localeCompare(b, "zh-CN"))
  const primaryScope = linkScope.filter((row) => !filters.p1 || row.p1 === filters.p1)
  const secondaryCategories = [...new Set(primaryScope.map((row) => row.p2).filter(Boolean))].sort((a, b) => a.localeCompare(b, "zh-CN"))
  const secondaryScope = primaryScope.filter((row) => !filters.p2 || row.p2 === filters.p2)
  const tertiaryCategories = [...new Set(secondaryScope.map((row) => row.p3).filter(Boolean))].sort((a, b) => a.localeCompare(b, "zh-CN"))
  const batchId = data.batchId || data.source?.batchId
  const contextEntries: Array<[string, string]> = [...(basis === "created" ? [["basis", "created"], ["week_start", weekStart]] as Array<[string, string]> : []), ...(batchId ? [["batch", batchId] as [string, string]] : [])]
  const entries = [...contextEntries, ...issueFilterEntries(filters)]

  return (
    <section className="panel workbench-panel">
      <div className="panel-heading workbench-heading">
        <div><span className="eyebrow">{eyebrow}</span><h3>{title}</h3></div>
        <ExportLink entries={entries} mode={data.mode} view="detail">导出当前结果</ExportLink>
      </div>
      <p className="workbench-intro">{basis === "created" ? "以下记录按售后创建时间归入所选周，数量与产品周报保持一致。" : "按产品、商品链接、一级问题、二级问题和三级问题逐层定位；五大分类按一级问题确定，可剔除规则统一控制经营统计范围。"}</p>
      {filters.warehouseCode ? <p className="context-filter">当前下钻范围：仓库 {filters.warehouseCode}</p> : null}
      <LiveIssueFilters action={action} contextEntries={contextEntries} filters={filters} links={links} mode={data.mode} primaryProblems={categories} products={products} secondaryProblems={secondaryCategories} showAlert={basis !== "created"} tertiaryProblems={tertiaryCategories} />
      <div className="result-scope audit-summary">
        <strong>全量售后 {formatCount(audit.totalIssues)}</strong>
        <span>经营问题 {formatCount(audit.operatingIssues)}（前周 {formatCount(audit.previous.operatingIssues)}）</span>
        <span>规则剔除 {formatCount(audit.excludedIssues)}（前周 {formatCount(audit.previous.excludedIssues)}）</span>
        <span>待归类 {formatCount(audit.unclassifiedIssues)}（前周 {formatCount(audit.previous.unclassifiedIssues)}）</span>
        <span>当前筛选 {formatCount(rows.reduce((sum, row) => sum + row.currentIssues, 0))} 条售后 · {formatCount(rows.length)} 个聚合组合</span>
      </div>
      <VirtualIssueTable
        fetchUrl={`/aftersales/api/issues?${new URLSearchParams({ period: data.mode, ...Object.fromEntries(entries) }).toString()}`}
        initialRows={initialRows}
        key={`${data.mode}|${entries.map((entry) => entry.join("=")).join("|")}`}
        totalRows={rows.length}
        weekLabels={data.weeks}
        quantityOnly={basis === "created"}
      />
    </section>
  )
}
