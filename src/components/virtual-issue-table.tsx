"use client"

import { useVirtualizer } from "@tanstack/react-virtual"
import { Columns3 } from "lucide-react"
import { type CSSProperties, type ReactNode, useCallback, useEffect, useMemo, useRef, useState } from "react"

import type { IssueRow } from "@/src/modules/analytics/types"

import { AlertBadge } from "./alert-badge"
import { formatCount, formatDelta, formatPercent, formatSourceSystem } from "./format"

type ColumnGroup = "identifiers" | "details" | "orders" | "sales" | "excess" | "weeks"

interface TableColumn {
  id: string
  label: string
  width: number
  group?: ColumnGroup
  sticky?: "code" | "name"
  numeric?: boolean
  render: (row: IssueRow) => ReactNode
}

const groupOptions: Array<{ id: ColumnGroup; label: string }> = [
  { id: "identifiers", label: "商品ID（售后来源/抖店）" },
  { id: "details", label: "问题详细分类" },
  { id: "orders", label: "当期订单数" },
  { id: "sales", label: "当期产品销量" },
  { id: "excess", label: "超出预期问题数" },
  { id: "weeks", label: "近5周具体数值" },
]

function weekValue(row: IssueRow, index: number) {
  const week = row.weeks[index]
  if (!week) return <span className="week-metric"><strong>—</strong><small>—</small></span>
  return <span className="week-metric"><strong>{formatCount(week.issues)}</strong><small>销量 {formatCount(week.sales)} · {formatPercent(week.rate)}</small></span>
}

export function VirtualIssueTable({
  initialRows,
  totalRows,
  weekLabels,
  fetchUrl,
  quantityOnly = false,
}: {
  initialRows: IssueRow[]
  totalRows: number
  weekLabels: string[]
  fetchUrl: string
  quantityOnly?: boolean
}) {
  const viewportRef = useRef<HTMLDivElement>(null)
  const loadingRef = useRef(false)
  const [rows, setRows] = useState(initialRows)
  const [loadError, setLoadError] = useState("")
  const [hiddenGroups, setHiddenGroups] = useState<Set<ColumnGroup>>(() => new Set())
  const columns = useMemo<TableColumn[]>(() => {
    const result: TableColumn[] = [
    { id: "code", label: "商家编码", width: 132, sticky: "code", render: (row: IssueRow) => <strong>{row.code}</strong> },
    { id: "name", label: "商品名称", width: 260, sticky: "name", render: (row) => <strong title={row.name}>{row.name}</strong> },
    { id: "product-id", label: "售后商品ID", width: 176, group: "identifiers", render: (row) => <code className="identifier-value" title={row.productId}>{row.productId || "—"}</code> },
    { id: "source", label: "售后来源", width: 122, group: "identifiers", render: (row) => formatSourceSystem(row.sourceSystem) },
    { id: "doudian", label: "抖店商品ID（已确认）", width: 184, group: "identifiers", render: (row) => <code className="identifier-value" title={row.doudianProductId}>{row.doudianProductId || "—"}</code> },
    { id: "p1", label: "一级问题", width: 118, render: (row) => row.p1 },
    { id: "p2", label: "二级问题", width: 138, group: "details", render: (row) => row.p2 || "—" },
    { id: "p3", label: "三级问题", width: 150, group: "details", render: (row) => row.p3 || "—" },
    { id: "status", label: "统计状态", width: 118, group: "details", render: (row) => row.classificationStatus === "included" ? "已纳入" : row.classificationStatus === "excluded" ? "可剔除" : "待归类" },
    { id: "issues", label: quantityOnly ? "所选周问题数" : "当期问题数", width: 104, numeric: true, render: (row) => formatCount(row.currentIssues) },
    ]
    if (quantityOnly) result.push({ id: "count-delta", label: "较前一周", width: 100, numeric: true, render: (row: IssueRow) => {
      const delta = row.currentIssues - row.previousIssues
      return <span className={delta > 0 ? "number-up" : delta < 0 ? "number-down" : ""}>{delta > 0 ? "+" : ""}{formatCount(delta)}</span>
    } })
    else result.push(
      { id: "orders", label: "当期订单数", width: 104, group: "orders", numeric: true, render: (row: IssueRow) => formatCount(row.currentOrders) },
      { id: "sales", label: "当期销量", width: 96, group: "sales", numeric: true, render: (row: IssueRow) => formatCount(row.currentSales) },
      { id: "rate", label: "当期售后率", width: 98, numeric: true, render: (row: IssueRow) => formatPercent(row.currentRate) },
      { id: "delta", label: "较上期变化", width: 100, numeric: true, render: (row: IssueRow) => <span className={(row.rateDeltaPp || 0) > 0 ? "number-up" : (row.rateDeltaPp || 0) < 0 ? "number-down" : ""}>{formatDelta(row.rateDeltaPp)}</span> },
      { id: "excess", label: "超出预期问题数", width: 124, group: "excess", numeric: true, render: (row: IssueRow) => row.excessIssues === null ? "—" : row.excessIssues.toFixed(1) },
    )
    result.push(...weekLabels.map((label, index): TableColumn => ({
      id: `week-${index}`,
      label,
      width: 104,
      group: "weeks",
      numeric: true,
      render: (row) => quantityOnly ? <span className="week-metric"><strong>{formatCount(row.weeks[index]?.issues ?? 0)}</strong><small>问题记录</small></span> : weekValue(row, index),
    })))
    if (!quantityOnly) result.push({ id: "alert", label: "预警状态", width: 104, render: (row: IssueRow) => <AlertBadge level={row.alertLevel} /> })
    return result
  }, [quantityOnly, weekLabels])
  const visibleColumns = columns.filter((column) => !column.group || !hiddenGroups.has(column.group))
  const tableWidth = visibleColumns.reduce((sum, column) => sum + column.width, 0) + Math.max(0, visibleColumns.length - 1) * 10 + 26
  const gridStyle = {
    gridTemplateColumns: visibleColumns.map((column) => `${column.width}px`).join(" "),
    minWidth: `${tableWidth}px`,
  } satisfies CSSProperties
  // TanStack Virtual owns scroll measurements and intentionally exposes unstable callbacks.
  // eslint-disable-next-line react-hooks/incompatible-library
  const virtualizer = useVirtualizer({
    count: rows.length + (rows.length < totalRows ? 1 : 0),
    getScrollElement: () => viewportRef.current,
    estimateSize: () => 78,
    getItemKey: (index) => {
      const row = rows[index]
      return row ? `${row.sourceSystem}|${row.code}|${row.productId}|${row.p1}|${row.p2}|${row.p3}|${row.denominatorKey || ""}|${row.classificationStatus}` : `load-more-${index}`
    },
    overscan: 12,
  })
  const visibleRows = virtualizer.getVirtualItems()
  const lastVisibleIndex = visibleRows.at(-1)?.index ?? 0
  const loadMore = useCallback(async () => {
    if (loadingRef.current || rows.length >= totalRows) return
    loadingRef.current = true
    setLoadError("")
    const offset = rows.length
    try {
      const separator = fetchUrl.includes("?") ? "&" : "?"
      const response = await fetch(`${fetchUrl}${separator}offset=${offset}&limit=240`, {
        credentials: "same-origin",
        headers: { accept: "application/json" },
      })
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
      const payload = await response.json() as { rows: IssueRow[]; rowGroupCount: number }
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

  if (!totalRows) return <div className="empty-state">当前筛选范围内没有数据，Excel 也将导出 0 条</div>

  const firstVisible = (visibleRows[0]?.index ?? 0) + 1
  const lastVisible = Math.min((visibleRows.at(-1)?.index ?? 0) + 1, rows.length, totalRows)

  return (
    <div className="virtual-table-shell">
      <div className="table-tools">
        <details>
          <summary><Columns3 aria-hidden="true" size={15} />列显示</summary>
          <div className="column-picker">
            {groupOptions.filter((option) => !quantityOnly || !["orders", "sales", "excess"].includes(option.id)).map((option) => (
              <label key={option.id}>
                <input
                  checked={!hiddenGroups.has(option.id)}
                  onChange={(event) => setHiddenGroups((current) => {
                    const next = new Set(current)
                    if (event.target.checked) next.delete(option.id)
                    else next.add(option.id)
                    return next
                  })}
                  type="checkbox"
                />
                {option.label}
              </label>
            ))}
          </div>
        </details>
        <span>商家编码和商品名称固定在左侧</span>
      </div>
      <div className="virtual-table-frame" role="table" aria-colcount={visibleColumns.length} aria-label="售后问题组合" aria-rowcount={totalRows + 1}>
        <div aria-label={`问题明细，共 ${totalRows} 行`} className="virtual-viewport" ref={viewportRef} tabIndex={0}>
          <div className="virtual-grid virtual-header" role="row" style={gridStyle}>
            {visibleColumns.map((column) => <span className={column.sticky ? `sticky-cell sticky-${column.sticky}` : ""} key={column.id} role="columnheader">{column.label}</span>)}
          </div>
          <div className="virtual-body" role="rowgroup" style={{ height: virtualizer.getTotalSize(), minWidth: tableWidth }}>
            {visibleRows.map((virtualRow) => {
              const row = rows[virtualRow.index]
              if (!row) {
                return (
                  <div
                    className="virtual-load-more"
                    key={virtualRow.key}
                    style={{ transform: `translateY(${virtualRow.start}px)` }}
                  >
                    {loadError ? <button onClick={() => void loadMore()} type="button">{loadError}</button> : "正在按需加载后续数据…"}
                  </div>
                )
              }
              return (
                <div
                  aria-rowindex={virtualRow.index + 2}
                  className="virtual-grid virtual-row"
                  data-index={virtualRow.index}
                  key={virtualRow.key}
                  ref={virtualizer.measureElement}
                  role="row"
                  style={{ ...gridStyle, transform: `translateY(${virtualRow.start}px)` }}
                >
                  {visibleColumns.map((column) => (
                    <span
                      className={[
                        "virtual-cell",
                        column.numeric ? "numeric" : "",
                        column.sticky ? `sticky-cell sticky-${column.sticky}` : "",
                      ].filter(Boolean).join(" ")}
                      data-column={column.id}
                      data-label={column.label}
                      key={column.id}
                      role="cell"
                    >
                      {column.render(row)}
                    </span>
                  ))}
                </div>
              )
            })}
          </div>
        </div>
        <p aria-live="polite" className="virtual-status">当前渲染第 {formatCount(firstVisible)}–{formatCount(lastVisible)} 行 · 已按需加载 {formatCount(rows.length)} / {formatCount(totalRows)} 行 · Excel 导出全部结果</p>
      </div>
    </div>
  )
}
