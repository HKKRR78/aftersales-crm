import Form from "next/form"

import type { DateWindow } from "@/src/modules/analytics/types"

export function ProductWeekSwitcher({
  selectedWeekStart,
  weeks,
  batchId,
}: {
  selectedWeekStart: string
  weeks: DateWindow[]
  batchId?: string
}) {
  return (
    <div className="period-control">
      <Form action="/products" className="week-picker">
        {batchId ? <input type="hidden" name="batch" value={batchId} /> : null}
        <label htmlFor="product-week">选择售后创建周</label>
        <select defaultValue={selectedWeekStart} id="product-week" name="week_start">
          {[...weeks].reverse().map((week) => <option key={week.start} value={week.start}>{week.label}</option>)}
        </select>
        <button type="submit">查看</button>
      </Form>
      <small>全部 {weeks.length} 个完整周 · 周日至周六</small>
    </div>
  )
}
