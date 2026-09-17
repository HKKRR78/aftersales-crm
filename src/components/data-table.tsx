import Link from "next/link"

import { AlertBadge } from "./alert-badge"
import { formatCount, formatDelta, formatPercent } from "./format"
import { TrendBars } from "./trend-bars"
import type { SummaryRow } from "@/src/modules/analytics/types"

export function SummaryTable({ rows, emptyText = "当前筛选范围内没有数据" }: { rows: SummaryRow[]; emptyText?: string }) {
  if (!rows.length) return <div className="empty-state">{emptyText}</div>
  return (
    <div className="table-scroll">
      <table>
        <thead><tr><th>对象</th><th>预警</th><th>问题数</th><th>售后率</th><th>变化</th><th>趋势</th></tr></thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.key}>
              <td>
                {row.detailHref ? <Link className="row-link" href={row.detailHref}>{row.label}</Link> : <strong>{row.label}</strong>}
                {row.secondary ? <small className="cell-note">{row.secondary}</small> : null}
              </td>
              <td><AlertBadge level={row.alertLevel} /></td>
              <td><strong>{formatCount(row.latestIssues)}</strong><small className="cell-note">累计 {formatCount(row.totalIssues)}</small></td>
              <td>{formatPercent(row.latestRate)}</td>
              <td className={(row.rateDeltaPp || 0) > 0 ? "number-up" : (row.rateDeltaPp || 0) < 0 ? "number-down" : ""}>{formatDelta(row.rateDeltaPp)}</td>
              <td><TrendBars weeks={row.weeks} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
