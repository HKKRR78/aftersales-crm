import { reportBatch } from "@/src/modules/analytics/repository"
import { isDevFixtureMode } from "@/src/modules/analytics/dev-mode"
import { shanghaiToday } from "@/src/modules/analytics/date-windows"
import { Suspense } from "react"
import Link from "next/link"

import { DataError } from "@/src/components/data-error"
import { IssueWorkbench } from "@/src/components/issue-workbench"
import { PeriodSwitcher } from "@/src/components/period-switcher"
import { ProductOrderNotice } from "@/src/components/product-order-notice"
import { RouteLoading } from "@/src/components/route-loading"
import { loadCreatedIssueData, loadDashboard, loadWarehouseIssueRows } from "@/src/modules/analytics/service"
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
  warehouse_code?: string
  alert?: string
  scope?: string
  basis?: string
  week_start?: string
}> }

export default function DetailPage(props: Props) {
  return <Suspense fallback={<RouteLoading />}><DetailContent {...props} /></Suspense>
}

async function DetailContent({ searchParams }: Props) {
  const query = await searchParams
  const mode: PeriodMode = query.period === "progress" ? "progress" : "closed"
  let result
  let error: unknown
  let warehouseLabel = ""
  const createdBasis = query.basis === "created"
  try {
    const batch = isDevFixtureMode() ? undefined : await reportBatch(query.batch)
    const today = shanghaiToday()
    if (createdBasis) {
      result = await loadCreatedIssueData(query.week_start, today, batch, (query.warehouse_code || "").trim())
    } else {
      const dashboard = await loadDashboard(mode, today, batch)
      const warehouseCode = (query.warehouse_code || "").trim()
      if (warehouseCode) {
        const warehouse = dashboard.warehouseRows.find((row) => row.warehouseCode === warehouseCode)
        warehouseLabel = warehouse?.warehouseName || warehouseCode
        const issueRows = await loadWarehouseIssueRows(mode, warehouseCode, warehouse?.warehouseName || "", today, batch)
        result = { ...dashboard, issueRows }
      } else {
        result = dashboard
      }
    }
  } catch (caught) { error = caught }

  return (
    <>
      <div className="page-heading"><div><span className="eyebrow">ISSUE EXPLORER</span><h2>{createdBasis ? "产品周报问题明细" : warehouseLabel ? `${warehouseLabel}问题明细` : "问题明细"}</h2><p>{createdBasis ? `按售后创建周 ${result?.weeks.at(-1) || ""} 对账。` : warehouseLabel ? "从仓库风险下钻，继续按商品和问题分类定位。" : "按商品、问题分类和预警等级定位异常。"}</p></div>{createdBasis ? <Link href={`/products?week_start=${query.week_start || ""}&batch=${query.batch || ""}`}>返回产品周报</Link> : <PeriodSwitcher entries={[...(query.batch ? [["batch", query.batch] as [string, string]] : []), ...(query.warehouse_code ? [["warehouse_code", query.warehouse_code] as [string, string]] : [])]} mode={mode} path="/detail" />}</div>
      {result ? <>{!createdBasis && !warehouseLabel && "source" in result ? <ProductOrderNotice source={result.source} /> : null}<IssueWorkbench action="/detail" basis={createdBasis ? "created" : "payment"} data={result} eyebrow="ISSUE EXPLORER" query={query} title={createdBasis ? `${result.weeks.at(-1)} 创建的售后问题` : warehouseLabel ? `${warehouseLabel}售后问题组合` : "售后问题组合"} weekStart={query.week_start} /></> : <DataError error={error} />}
    </>
  )
}
