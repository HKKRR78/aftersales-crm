import Form from "next/form"
import Link from "next/link"
import { Suspense } from "react"

import { DataError } from "@/src/components/data-error"
import { ExportLink } from "@/src/components/export-link"
import { PeriodSwitcher } from "@/src/components/period-switcher"
import { RouteLoading } from "@/src/components/route-loading"
import { VirtualSummaryTable } from "@/src/components/virtual-summary-table"
import { filterWarehouseRows, listFiltersFromSearch } from "@/src/modules/analytics/filters"
import { loadDashboard } from "@/src/modules/analytics/service"
import { reportBatch } from "@/src/modules/analytics/repository"
import { isDevFixtureMode } from "@/src/modules/analytics/dev-mode"
import { shanghaiToday } from "@/src/modules/analytics/date-windows"
import type { DashboardData, PeriodMode, SummaryRow } from "@/src/modules/analytics/types"

type Props = { searchParams: Promise<{ period?: string; q?: string; batch?: string }> }

export default function WarehousesPage(props: Props) {
  return <Suspense fallback={<RouteLoading />}><WarehousesContent {...props} /></Suspense>
}

async function WarehousesContent({ searchParams }: Props) {
  const query = await searchParams
  const mode: PeriodMode = query.period === "progress" ? "progress" : "closed"
  let result: DashboardData | undefined
  let error: unknown
  try { result = await loadDashboard(mode, shanghaiToday(), isDevFixtureMode() ? undefined : await reportBatch(query.batch)) } catch (caught) { error = caught }
  const batchEntries: Array<[string, string]> = result?.source.batchId ? [["batch", result.source.batchId]] : []
  const filters = listFiltersFromSearch(query)
  const rows: SummaryRow[] = filterWarehouseRows(result?.warehouseRows || [], filters).map((row) => ({ ...row, key: row.warehouseCode, label: row.warehouseName || row.warehouseCode, secondary: row.warehouseName ? row.warehouseCode : "未完成仓库映射", detailHref: `/detail?warehouse_code=${encodeURIComponent(row.warehouseCode)}&period=${mode}&batch=${result?.source.batchId || ""}` }))
  return <>
    <div className="page-heading"><div><span className="eyebrow">WAREHOUSE QUALITY</span><h2>仓库分析</h2><p>只统计库房问题，并使用映射后的仓库订单作为分母。</p></div><PeriodSwitcher entries={batchEntries} mode={mode} path="/warehouses" /></div>
    {result ? <><Form className="filter-bar compact" action="/warehouses"><input name="period" type="hidden" value={mode} /><input name="batch" type="hidden" value={result.source.batchId || ""} /><label className="sr-only" htmlFor="warehouse-search">搜索仓库名称或编码</label><input autoComplete="off" defaultValue={filters.q} id="warehouse-search" name="q" placeholder="搜索仓库名称或编码…" spellCheck={false} /><button type="submit">搜索仓库</button><Link href={`/warehouses?period=${mode}&batch=${result.source.batchId || ""}`}>清空</Link></Form><section className="panel"><div className="panel-heading"><div><span className="eyebrow">{rows.length} WAREHOUSES</span><h3>仓库完整结果</h3></div><ExportLink entries={[...batchEntries, ...(filters.q ? [["q", filters.q] as [string, string]] : [])]} mode={mode} view="warehouse">导出当前结果</ExportLink></div><VirtualSummaryTable noun="仓库" rows={rows} weekLabels={result.weeks} /></section></> : <DataError error={error} />}
  </>
}
