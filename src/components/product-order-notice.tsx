import { AlertTriangle } from "lucide-react"

import type { DashboardSource } from "@/src/modules/analytics/types"

export function ProductOrderNotice({ source }: { source: DashboardSource }) {
  if (source.productOrderState === "fresh") return null
  return (
    <aside className="data-notice" role="status">
      <AlertTriangle aria-hidden="true" size={18} />
      <span>
        <strong>商品订单明细截至 {source.productOrderThrough || "待确认"}</strong>
        唯一对应商品的商家编码已安全回填 {source.productOrderFallbackRows} 条；其余 {source.productOrderUnavailableRows} 条缺失分母显示“—”，不会误显示为 0。
      </span>
    </aside>
  )
}
