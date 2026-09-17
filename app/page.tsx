import { Activity, BadgePercent, ClipboardCheck, PackageCheck, RefreshCw } from "lucide-react"
import Link from "next/link"
import { Suspense } from "react"

import { DataError } from "@/src/components/data-error"
import { ExportLink } from "@/src/components/export-link"
import { formatCount, formatDateTime, formatDelta, formatPercent } from "@/src/components/format"
import { IssueWorkbench } from "@/src/components/issue-workbench"
import { MetricCard } from "@/src/components/metric-card"
import { PeriodSwitcher } from "@/src/components/period-switcher"
import { ProductOrderNotice } from "@/src/components/product-order-notice"
import { RouteLoading } from "@/src/components/route-loading"
import { issueFilterEntries, issueFiltersFromSearch } from "@/src/modules/analytics/filters"
import { loadDashboard } from "@/src/modules/analytics/service"
import { sourceFreshness } from "@/src/modules/analytics/freshness"
import { reportBatch } from "@/src/modules/analytics/repository"
import { isDevFixtureMode } from "@/src/modules/analytics/dev-mode"
import { shanghaiToday } from "@/src/modules/analytics/date-windows"
import type { PeriodMode } from "@/src/modules/analytics/types"

type Props = { searchParams: Promise<{
  batch?: string
  period?: string
  q?: string
  p1?: string
  p2?: string
  p3?: string
  merchant_code?: string
  product_id?: string
  doudian_product_id?: string
  alert?: string
  scope?: string
}> }

export default function DashboardPage(props: Props) {
  return <Suspense fallback={<RouteLoading />}><DashboardContent {...props} /></Suspense>
}

async function DashboardContent({ searchParams }: Props) {
  const query = await searchParams
  const mode: PeriodMode = query.period === "progress" ? "progress" : "closed"
  let result
  let error: unknown
  try {
    result = await loadDashboard(mode, shanghaiToday(), isDevFixtureMode() ? undefined : await reportBatch(query.batch))
  } catch (caught) {
    error = caught
  }
  const freshness = result ? sourceFreshness(result.source.syncedAt) : null
  const batchEntries: Array<[string, string]> = result?.source.batchId ? [["batch", result.source.batchId]] : []

  return (
    <>
      <div className="page-heading">
        <div><span className="eyebrow">OVERVIEW + WORKBENCH</span><h2>经营总览与售后工作台</h2><p>先掌握整体，再进入全量大表查数、对账和导出。</p></div>
        <div className="page-heading-actions"><PeriodSwitcher entries={batchEntries} mode={mode} /><ExportLink entries={[...batchEntries, ...issueFilterEntries(issueFiltersFromSearch(query))]} mode={mode} prominent view="complete">导出完整经营分析</ExportLink></div>
      </div>
      {result ? (
        <>
          <section className={freshness?.state === "fresh" ? "source-strip" : "source-strip stale"}>
            <span><RefreshCw aria-hidden="true" size={15} /> {result.source.sourceType === "fixture" ? "本地验收数据" : freshness?.state === "fresh" ? "数据正常" : freshness?.state === "stale" ? `数据已滞后 ${Math.floor(freshness.ageHours || 0)} 小时` : "同步状态待确认"} · {formatDateTime(result.source.syncedAt)}</span>
            <span>分析周期 {result.source.currentPeriod}</span>
            <span>{mode === "progress" ? `已结束 ${result.source.completedDays} 个自然日` : "近 5 个完整周"}</span>
            {mode === "progress" && result.source.orderThrough ? <span>订单截至 {result.source.orderThrough}</span> : null}
            <span>售后事实 {formatCount(result.source.apiRows)} 行</span>
            {result.source.coverageStart && result.source.coverageEnd ? <span>新工单覆盖 {result.source.coverageStart.slice(0, 10)} 至 {result.source.coverageEnd.slice(0, 10)}</span> : null}
            {result.source.reconciliationStatus === "pending" ? <span>交接对账待确认</span> : null}
          </section>
          <ProductOrderNotice source={result.source} />
          <section className="metric-grid">
            <MetricCard icon={ClipboardCheck} label="全量售后问题" value={formatCount(result.kpis.latestAllIssues)} note={`其中 ${formatCount(result.kpis.unclassifiedIssues)} 个问题待分类`} />
            <MetricCard icon={ClipboardCheck} label="经营异常问题" value={formatCount(result.kpis.latestIssues)} note={`涉及 ${formatCount(result.kpis.rowCount)} 个产品问题组合`} tone={result.kpis.latestIssues > 0 ? "warning" : "good"} />
            <MetricCard icon={PackageCheck} label="产品销量" value={formatCount(result.kpis.currentSales)} note={`销售订单 ${formatCount(result.kpis.currentOrders)} 单`} />
            <MetricCard icon={BadgePercent} label="经营异常售后率" value={formatPercent(result.kpis.latestRate)} note="经营异常问题数 ÷ 销售订单数" tone={(result.kpis.latestRate || 0) >= 2 ? "critical" : "neutral"} />
            <MetricCard icon={Activity} label="售后率周环比" value={formatDelta(result.kpis.latestWow)} note={`${formatCount(result.kpis.deteriorated)} 项售后率正在上升`} tone={(result.kpis.latestWow || 0) > 0 ? "warning" : "good"} />
          </section>
          <aside className="usage-guide" aria-label="今天怎么用">
            <strong>今天怎么用</strong>
            <span>① 看全量问题、经营异常和产品销量</span><span>② 按产品→链接→问题逐层定位</span><span>③ 导出全部结果用于对账和跟进</span>
          </aside>
          <article className="panel weekly-overview">
            <div className="panel-heading"><div><span className="eyebrow">FIVE-WEEK TREND</span><h3>近 5 周经营售后趋势</h3></div><Link href={`/detail?period=${mode}&batch=${result?.source.batchId || ""}`}>进入问题分析</Link></div>
            <div className="table-scroll"><table><thead><tr><th>周期</th><th>经营异常问题</th><th>产品销量</th><th>销售订单</th><th>售后率</th><th>周环比</th></tr></thead><tbody>{result.weeklyTotals.map((week, index) => <tr key={result.weeks[index]}><td><strong>{result.weeks[index]}</strong></td><td>{formatCount(week.issues)}</td><td>{formatCount(week.sales)}</td><td>{formatCount(week.orders)}</td><td>{formatPercent(week.rate)}</td><td className={(week.wow || 0) > 0 ? "number-up" : (week.wow || 0) < 0 ? "number-down" : ""}>{formatDelta(week.wow)}</td></tr>)}</tbody></table></div>
          </article>
          <IssueWorkbench action="/" data={result} query={query} />
          <section className="specialty-grid">
            <article className="panel">
              <div className="panel-heading"><div><span className="eyebrow">PRODUCT WATCHLIST</span><h3>产品预警榜</h3></div><Link href={`/products?period=${mode}&batch=${result.source.batchId || ""}`}>全部产品</Link></div>
              <div className="watch-list">
                {result.productRows.slice(0, 7).map((row, index) => (
                  <Link href={row.detailHref!} key={row.key} className="watch-row">
                    <span className="rank">{String(index + 1).padStart(2, "0")}</span>
                    <span className="watch-copy"><strong>{row.label}</strong><small>{row.secondary}</small></span>
                    <span className="watch-metric"><strong>{formatCount(row.latestIssues)}</strong><small>{formatPercent(row.latestRate)}</small></span>
                  </Link>
                ))}
              </div>
            </article>
            <article className="panel">
              <div className="panel-heading"><div><span className="eyebrow">WAREHOUSE WATCH</span><h3>仓库风险</h3></div><Link href={`/warehouses?period=${mode}&batch=${result.source.batchId || ""}`}>全部仓库</Link></div>
              <div className="warehouse-list">
                {result.warehouseRows.slice(0, 6).map((row) => (
                  <Link className="warehouse-row" href={`/detail?warehouse_code=${encodeURIComponent(row.warehouseCode)}&period=${mode}&batch=${result?.source.batchId || ""}`} key={row.warehouseCode}>
                    <span><strong>{row.warehouseName || row.warehouseCode}</strong><small>{row.warehouseName ? row.warehouseCode : "未完成仓库映射"}</small></span>
                    <span><strong>{formatCount(row.latestIssues)}</strong><small>{formatPercent(row.latestRate)}</small></span>
                    <i className={row.alertLevel} />
                  </Link>
                ))}
              </div>
            </article>
          </section>
        </>
      ) : <DataError error={error} />}
    </>
  )
}
