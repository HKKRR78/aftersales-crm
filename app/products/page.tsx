import { reportBatch } from "@/src/modules/analytics/repository"
import { isDevFixtureMode } from "@/src/modules/analytics/dev-mode"
import { shanghaiToday } from "@/src/modules/analytics/date-windows"
import Form from "next/form"
import Link from "next/link"
import { Suspense } from "react"

import { DataError } from "@/src/components/data-error"
import { ExportLink } from "@/src/components/export-link"
import { ProductWeekSwitcher } from "@/src/components/product-week-switcher"
import { ProductWeeklyTable } from "@/src/components/product-weekly-table"
import { RouteLoading } from "@/src/components/route-loading"
import { filterProductWeeklyRows, listFiltersFromSearch } from "@/src/modules/analytics/filters"
import { loadProductWeeklyReport } from "@/src/modules/analytics/service"
import { formatDateTime } from "@/src/components/format"

type Props = { searchParams: Promise<{ week_start?: string; q?: string; batch?: string }> }

export default function ProductsPage(props: Props) {
  return <Suspense fallback={<RouteLoading />}><ProductsContent {...props} /></Suspense>
}

async function ProductsContent({ searchParams }: Props) {
  const query = await searchParams
  let result
  let error: unknown
  try { result = await loadProductWeeklyReport(query.week_start, shanghaiToday(), isDevFixtureMode() ? undefined : await reportBatch(query.batch)) } catch (caught) { error = caught }
  const filters = listFiltersFromSearch(query)
  const rows = filterProductWeeklyRows(result?.rows || [], filters)
  return <>
    <div className="page-heading"><div><span className="eyebrow">PRODUCT WEEKLY REPORT</span><h2>产品售后周报</h2><p>按售后创建时间查看上一个完整周，并按经营异常问题数排序。</p></div>{result ? <ProductWeekSwitcher batchId={result.batchId} selectedWeekStart={result.selectedWeekStart} weeks={result.selectableWeeks} /> : null}</div>
    {result ? <><section className="source-strip"><span>统计口径：售后创建时间 · 经营异常商品记录</span><span>所选周 {result.selectedWeekLabel}</span><span>数据更新 {formatDateTime(result.syncedAt)}</span></section>{result.unmatchedIssues > 0 ? <aside className="data-notice"><span><strong>待匹配 {result.unmatchedIssues} 条</strong><span>缺少商家编码，已计入所选周问题总量，但不参与产品排名。<Link className="inline-link" href={result.unmatchedDetailHref}>查看待匹配记录</Link></span></span></aside> : null}<Form className="filter-bar compact" action="/products"><input type="hidden" name="batch" value={result.batchId || ""} /><input type="hidden" name="week_start" value={result.selectedWeekStart} /><label className="sr-only" htmlFor="product-search">搜索产品名称或商家编码</label><input autoComplete="off" id="product-search" name="q" defaultValue={query.q} placeholder="搜索产品名称或商家编码…" spellCheck={false} /><button type="submit">搜索产品</button><Link href={`/products?week_start=${result.selectedWeekStart}&batch=${result.batchId || ""}`}>清空</Link></Form><section className="panel"><div className="panel-heading"><div><span className="eyebrow">{rows.length} PRODUCTS</span><h3>{result.selectedWeekLabel} 有问题产品</h3></div><ExportLink entries={[...(result.batchId ? [["batch", result.batchId] as [string, string]] : []), ["basis", "created"], ["week_start", result.selectedWeekStart], ...(filters.q ? [["q", filters.q] as [string, string]] : [])]} mode="closed" view="products">导出当前结果</ExportLink></div><ProductWeeklyTable fetchUrl={`/aftersales/api/products?${new URLSearchParams({ week_start: result.selectedWeekStart, ...(result.batchId ? { batch: result.batchId } : {}), ...(filters.q ? { q: filters.q } : {}) }).toString()}`} key={`${result.selectedWeekStart}|${filters.q}`} rows={rows.slice(0, 120)} selectedWeekLabel={result.selectedWeekLabel} totalRows={rows.length} weekLabels={result.displayWeeks.map((week) => week.label)} /></section></> : <DataError error={error} />}
  </>
}
