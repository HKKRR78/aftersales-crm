"use client"

import { RotateCcw, Search } from "lucide-react"
import { useRouter } from "next/navigation"
import { useEffect, useRef, useState, useTransition } from "react"

import type { IssueFilters } from "@/src/modules/analytics/filters"

interface Option { value: string; label: string }

export function LiveIssueFilters({
  action,
  mode,
  filters,
  products,
  links,
  primaryProblems,
  secondaryProblems,
  tertiaryProblems,
  contextEntries = [],
  showAlert = true,
}: {
  action: "/" | "/detail"
  mode: string
  filters: IssueFilters
  products: Option[]
  links: Option[]
  primaryProblems: string[]
  secondaryProblems: string[]
  tertiaryProblems: string[]
  contextEntries?: Array<[string, string]>
  showAlert?: boolean
}) {
  const router = useRouter()
  const [isPending, startTransition] = useTransition()
  const [keyword, setKeyword] = useState(filters.q)
  const firstKeywordRender = useRef(true)

  function navigate(changes: Record<string, string>, remove: string[] = []) {
    const params = new URLSearchParams()
    params.set("period", mode)
    contextEntries.forEach(([key, value]) => { if (value) params.set(key, value) })
    const current: Record<string, string> = {
      q: keyword,
      merchant_code: filters.merchantCode,
      product_id: filters.productId,
      p1: filters.p1,
      p2: filters.p2,
      p3: filters.p3,
      alert: filters.alert,
      scope: filters.scope === "all" ? "all" : "",
      warehouse_code: filters.warehouseCode,
    }
    for (const [key, value] of Object.entries({ ...current, ...changes })) {
      if (value && !remove.includes(key)) params.set(key, value)
    }
    startTransition(() => router.replace(`${action}?${params.toString()}`, { scroll: false }))
  }

  useEffect(() => {
    if (firstKeywordRender.current) {
      firstKeywordRender.current = false
      return
    }
    const timer = window.setTimeout(() => navigate({ q: keyword }), 250)
    return () => window.clearTimeout(timer)
    // Navigation is intentionally driven only by the keyword value.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [keyword])

  return (
    <div className="live-filter-shell">
      <div className="live-filter-status"><span className={isPending ? "live-dot pending" : "live-dot"} /><span aria-live="polite">{isPending ? "正在更新结果…" : "选择后立即更新"}</span></div>
      <div className="live-filter-grid">
        <label><span>1. 产品</span><select value={filters.merchantCode} onChange={(event) => navigate({ merchant_code: event.target.value }, ["product_id", "p1", "p2", "p3"])}><option value="">全部产品</option>{products.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label>
        <label><span>2. 商品链接</span><select disabled={!filters.merchantCode} value={filters.productId} onChange={(event) => navigate({ product_id: event.target.value }, ["p1", "p2", "p3"])}><option value="">全部链接</option>{links.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label>
        <label><span>3. 一级问题</span><select value={filters.p1} onChange={(event) => navigate({ p1: event.target.value }, ["p2", "p3"])}><option value="">全部一级问题</option>{primaryProblems.map((value) => <option key={value}>{value}</option>)}</select></label>
        <label><span>4. 二级问题</span><select disabled={!filters.p1} value={filters.p2} onChange={(event) => navigate({ p2: event.target.value }, ["p3"])}><option value="">全部二级问题</option>{secondaryProblems.map((value) => <option key={value}>{value}</option>)}</select></label>
        <label><span>三级问题</span><select disabled={!filters.p2} value={filters.p3} onChange={(event) => navigate({ p3: event.target.value })}><option value="">全部三级问题</option>{tertiaryProblems.map((value) => <option key={value}>{value}</option>)}</select></label>
        <label><span>统计口径</span><select value={filters.scope} onChange={(event) => navigate({ scope: event.target.value === "all" ? "all" : "" })}><option value="operating">经营异常</option><option value="all">全量售后</option></select></label>
        <label className="keyword-filter"><span>关键词</span><div><Search aria-hidden="true" size={15} /><input autoComplete="off" value={keyword} onChange={(event) => setKeyword(event.target.value)} placeholder="产品、编码或问题…" /></div></label>
        {showAlert ? <label><span>预警状态</span><select value={filters.alert} onChange={(event) => navigate({ alert: event.target.value })}><option value="">全部状态</option><option value="critical">重点预警</option><option value="warning">正在上升</option><option value="improving">正在改善</option><option value="neutral">保持稳定</option></select></label> : null}
        <button className="reset-live-filters" onClick={() => {
          const params = new URLSearchParams({ period: mode })
          contextEntries.forEach(([key, value]) => { if (value) params.set(key, value) })
          if (filters.warehouseCode) params.set("warehouse_code", filters.warehouseCode)
          startTransition(() => router.replace(`${action}?${params.toString()}`, { scroll: false }))
        }} type="button"><RotateCcw aria-hidden="true" size={15} />清空筛选</button>
      </div>
    </div>
  )
}
