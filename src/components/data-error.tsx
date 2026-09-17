import { AlertTriangle, DatabaseZap } from "lucide-react"

import { DataUnavailableError } from "@/src/modules/analytics/errors"

export function DataError({ error }: { error: unknown }) {
  const expected = error instanceof DataUnavailableError
  return (
    <section className="data-error">
      <span className="error-icon">{expected ? <DatabaseZap aria-hidden="true" size={24} /> : <AlertTriangle aria-hidden="true" size={24} />}</span>
      <div>
        <span className="eyebrow">DATA PIPELINE BLOCKED</span>
        <h2>{expected ? "数据链路尚未完成" : "看板暂时无法读取数据"}</h2>
        <p>{expected ? error.message : "服务端读取失败，已停止展示可能失真的指标。请检查 MySQL 连接和聚合任务。"}</p>
        {expected ? <code>{error.code}</code> : null}
      </div>
    </section>
  )
}
