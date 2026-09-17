import type { RawIssueRow } from "./types"

type Series = Map<string, Array<number | null>>

// A complete sales specification is indivisible. Never borrow a base SKU's
// denominator, sum component orders, or infer a link from the issue sample.
export function orderSeries(code: string, values: Series) {
  return code && code !== "未填" ? values.get(code) ?? values.get("") : undefined
}

export function resolveProductOrders({ row, length, platformOrders, platformSales }: {
  row: RawIssueRow
  length: number
  platformOrders: Series
  platformSales: Series
}) {
  const key = row.denominatorKey
  const orders = (key && (platformOrders.get(key) ?? platformOrders.get(""))) || Array.from({ length }, () => null)
  const sales = (key && (platformSales.get(key) ?? platformSales.get(""))) || Array.from({ length }, () => null)
  return { orders, sales, usedFallback: false, unavailable: orders.some(value => value === null) }
}
