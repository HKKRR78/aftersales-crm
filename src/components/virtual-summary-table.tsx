"use client"

import { useVirtualizer } from "@tanstack/react-virtual"
import Link from "next/link"
import { useCallback, useEffect, useRef, useState } from "react"

import type { SummaryRow } from "@/src/modules/analytics/types"

import { AlertBadge } from "./alert-badge"
import { formatCount, formatDelta, formatPercent } from "./format"

export function VirtualSummaryTable({
  rows: initialRows,
  weekLabels,
  noun,
  totalRows = initialRows.length,
  fetchUrl,
  showProductIds = false,
}: {
  rows: SummaryRow[]
  weekLabels: string[]
  noun: string
  totalRows?: number
  fetchUrl?: string
  showProductIds?: boolean
}) {
  const viewportRef = useRef<HTMLDivElement>(null)
  const loadingRef = useRef(false)
  const [rows, setRows] = useState(initialRows)
  const [loadError, setLoadError] = useState("")
  // TanStack Virtual owns scroll measurements and intentionally exposes unstable callbacks.
  // eslint-disable-next-line react-hooks/incompatible-library
  const virtualizer = useVirtualizer({
    count: rows.length + (fetchUrl && rows.length < totalRows ? 1 : 0),
    getScrollElement: () => viewportRef.current,
    estimateSize: () => 72,
    getItemKey: (index) => rows[index]?.key || `load-more-${index}`,
    overscan: 12,
  })
  const visible = virtualizer.getVirtualItems()
  const lastVisibleIndex = visible.at(-1)?.index ?? 0
  const loadMore = useCallback(async () => {
    if (!fetchUrl || loadingRef.current || rows.length >= totalRows) return
    loadingRef.current = true
    setLoadError("")
    const offset = rows.length
    try {
      const response = await fetch(`${fetchUrl}&offset=${offset}&limit=200`, {
        credentials: "same-origin",
        headers: { accept: "application/json" },
      })
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
      const payload = await response.json() as { rows: SummaryRow[] }
      setRows((current) => current.length === offset ? [...current, ...payload.rows] : current)
    } catch {
      setLoadError("后续数据加载失败，请重试")
    } finally {
      loadingRef.current = false
    }
  }, [fetchUrl, rows.length, totalRows])

  useEffect(() => {
    if (lastVisibleIndex >= rows.length - 18 && rows.length < totalRows) void loadMore()
  }, [lastVisibleIndex, loadMore, rows.length, totalRows])

  if (!totalRows) return <div className="empty-state">当前筛选范围内没有数据</div>

  const identifierTemplate = showProductIds ? " 176px 184px" : ""
  const template = `minmax(280px, 2fr)${identifierTemplate} 110px 92px 104px 96px 98px 100px repeat(${weekLabels.length}, 104px)`
  const identifierWidth = showProductIds ? 360 : 0
  const identifierGaps = showProductIds ? 2 : 0
  const minWidth = 280 + identifierWidth + 110 + 92 + 104 + 96 + 98 + 100 + weekLabels.length * 104 + (6 + identifierGaps + weekLabels.length) * 10 + 26
  return (
    <div className="summary-virtual-frame" role="table" aria-label={`${noun}完整结果`} aria-rowcount={rows.length + 1}>
      <div className="summary-virtual-viewport" ref={viewportRef} tabIndex={0}>
        <div className="summary-virtual-grid summary-virtual-header" role="row" style={{ gridTemplateColumns: template, minWidth }}>
          <span role="columnheader">对象</span>
          {showProductIds ? <><span role="columnheader">售后商品ID</span><span role="columnheader">抖店商品ID（已确认）</span></> : null}
          <span role="columnheader">预警</span><span role="columnheader">问题数</span><span role="columnheader">订单数</span><span role="columnheader">销量</span><span role="columnheader">售后率</span><span role="columnheader">变化</span>
          {weekLabels.map((label) => <span key={label} role="columnheader">{label}</span>)}
        </div>
        <div className="summary-virtual-body" role="rowgroup" style={{ height: virtualizer.getTotalSize(), minWidth }}>
          {visible.map((virtualRow) => {
            const row = rows[virtualRow.index]
            if (!row) {
              return <div className="virtual-load-more" key={virtualRow.key} style={{ transform: `translateY(${virtualRow.start}px)` }}>{loadError ? <button onClick={() => void loadMore()} type="button">{loadError}</button> : "正在按需加载后续数据…"}</div>
            }
            return (
              <div className="summary-virtual-grid summary-virtual-row" data-index={virtualRow.index} key={virtualRow.key} ref={virtualizer.measureElement} role="row" style={{ gridTemplateColumns: template, minWidth, transform: `translateY(${virtualRow.start}px)` }}>
                <span className="summary-object" data-label="对象" role="cell">{row.detailHref ? <Link className="row-link" href={row.detailHref}>{row.label}</Link> : <strong>{row.label}</strong>}<small>{row.secondary}</small></span>
                {showProductIds ? <><span data-label="售后商品ID" role="cell"><code className="identifier-value" title={row.productId}>{row.productId || "—"}</code></span><span data-label="抖店商品ID（已确认）" role="cell"><code className="identifier-value" title={row.doudianProductId}>{row.doudianProductId || "—"}</code></span></> : null}
                <span data-label="预警" role="cell"><AlertBadge level={row.alertLevel} /></span>
                <span data-label="问题数" role="cell"><strong>{formatCount(row.currentIssues)}</strong></span>
                <span data-label="订单数" role="cell">{formatCount(row.currentOrders)}</span>
                <span data-label="销量" role="cell">{formatCount(row.currentSales)}</span>
                <span data-label="售后率" role="cell">{formatPercent(row.currentRate)}</span>
                <span className={(row.rateDeltaPp || 0) > 0 ? "number-up" : (row.rateDeltaPp || 0) < 0 ? "number-down" : ""} data-label="变化" role="cell">{formatDelta(row.rateDeltaPp)}</span>
                {row.weeks.map((week, index) => <span className="week-metric" data-label={weekLabels[index]} key={weekLabels[index] || index} role="cell"><strong>{formatCount(week.issues)}</strong><small>销量 {formatCount(week.sales)} · {formatPercent(week.rate)}</small></span>)}
              </div>
            )
          })}
        </div>
      </div>
      <p className="virtual-status">已按需加载 {formatCount(rows.length)} / {formatCount(totalRows)} 项 · Excel 导出全部结果</p>
    </div>
  )
}
