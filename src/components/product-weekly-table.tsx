"use client"

import { useVirtualizer } from "@tanstack/react-virtual"
import Link from "next/link"
import { useCallback, useEffect, useRef, useState } from "react"

import type { ProductWeeklyRow } from "@/src/modules/analytics/types"

import { formatCount } from "./format"

export function ProductWeeklyTable({
  rows: initialRows,
  weekLabels,
  totalRows,
  fetchUrl,
  selectedWeekLabel,
}: {
  rows: ProductWeeklyRow[]
  weekLabels: string[]
  totalRows: number
  fetchUrl: string
  selectedWeekLabel: string
}) {
  const viewportRef = useRef<HTMLDivElement>(null)
  const loadingRef = useRef(false)
  const [rows, setRows] = useState(initialRows)
  const [loadError, setLoadError] = useState("")
  // TanStack Virtual owns scroll measurements and intentionally exposes unstable callbacks.
  // eslint-disable-next-line react-hooks/incompatible-library
  const virtualizer = useVirtualizer({
    count: rows.length + (rows.length < totalRows ? 1 : 0),
    getScrollElement: () => viewportRef.current,
    estimateSize: () => 72,
    getItemKey: (index) => rows[index]?.key || `load-more-${index}`,
    overscan: 12,
  })
  const visible = virtualizer.getVirtualItems()
  const lastVisibleIndex = visible.at(-1)?.index ?? 0

  const loadMore = useCallback(async () => {
    if (loadingRef.current || rows.length >= totalRows) return
    loadingRef.current = true
    setLoadError("")
    const offset = rows.length
    try {
      const response = await fetch(`${fetchUrl}&offset=${offset}&limit=200`, {
        credentials: "same-origin",
        headers: { accept: "application/json" },
      })
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
      const payload = await response.json() as { rows: ProductWeeklyRow[] }
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

  if (!totalRows) return <div className="empty-state">所选周没有已归属产品的经营异常记录</div>

  const template = `56px minmax(280px, 2fr) 112px 116px repeat(${weekLabels.length}, 104px)`
  const minWidth = 56 + 280 + 112 + 116 + weekLabels.length * 104 + (3 + weekLabels.length) * 10 + 26
  return (
    <div className="summary-virtual-frame" role="table" aria-label="产品周报完整结果" aria-rowcount={totalRows + 1}>
      <div className="summary-virtual-viewport" ref={viewportRef} tabIndex={0}>
        <div className="summary-virtual-grid summary-virtual-header" role="row" style={{ gridTemplateColumns: template, minWidth }}>
          <span role="columnheader">排名</span>
          <span role="columnheader">产品</span>
          <span role="columnheader">所选周问题数</span>
          <span role="columnheader">较前一周</span>
          {weekLabels.map((label) => <span className={label === selectedWeekLabel ? "selected-week" : ""} key={label} role="columnheader">{label}</span>)}
        </div>
        <div className="summary-virtual-body" role="rowgroup" style={{ height: virtualizer.getTotalSize(), minWidth }}>
          {visible.map((virtualRow) => {
            const row = rows[virtualRow.index]
            if (!row) return <div className="virtual-load-more" key={virtualRow.key} style={{ transform: `translateY(${virtualRow.start}px)` }}>{loadError ? <button onClick={() => void loadMore()} type="button">{loadError}</button> : "正在按需加载后续数据…"}</div>
            return (
              <div className="summary-virtual-grid summary-virtual-row" data-index={virtualRow.index} key={virtualRow.key} ref={virtualizer.measureElement} role="row" style={{ gridTemplateColumns: template, minWidth, transform: `translateY(${virtualRow.start}px)` }}>
                <span className="rank" data-label="排名" role="cell">{String(virtualRow.index + 1).padStart(2, "0")}</span>
                <span className="summary-object" data-label="产品" role="cell"><Link className="row-link" href={row.detailHref}>{row.label}</Link><small>{row.secondary}</small></span>
                <span data-label="所选周问题数" role="cell"><strong>{formatCount(row.selectedIssues)}</strong></span>
                <span className={row.deltaIssues > 0 ? "number-up" : row.deltaIssues < 0 ? "number-down" : ""} data-label="较前一周" role="cell"><strong>{row.deltaIssues > 0 ? "+" : ""}{formatCount(row.deltaIssues)}</strong><small>前周 {formatCount(row.previousIssues)}</small></span>
                {row.weeklyIssues.map((issues, index) => <span className={`week-metric ${weekLabels[index] === selectedWeekLabel ? "selected-week" : ""}`} data-label={weekLabels[index]} key={weekLabels[index]} role="cell"><strong>{formatCount(issues)}</strong><small>问题记录</small></span>)}
              </div>
            )
          })}
        </div>
      </div>
      <p className="virtual-status">已按需加载 {formatCount(rows.length)} / {formatCount(totalRows)} 个产品 · Excel 导出全部结果</p>
    </div>
  )
}
