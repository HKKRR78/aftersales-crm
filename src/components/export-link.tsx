import { reportBatch } from "@/src/modules/analytics/repository"
import { isDevFixtureMode } from "@/src/modules/analytics/dev-mode"

import { Download } from "lucide-react"
import type { ReactNode } from "react"

import { exportHref } from "@/src/modules/exports/links"
import type { ExportView } from "@/src/modules/exports/types"
import type { PeriodMode } from "@/src/modules/analytics/types"

export async function ExportLink({
  view,
  mode,
  entries = [],
  children,
  prominent = false,
}: {
  view: ExportView
  mode: PeriodMode
  entries?: Array<[string, string]>
  children: ReactNode
  prominent?: boolean
}) {
  const pinned = isDevFixtureMode() || entries.some(([key]) => key === "batch") ? entries : [...entries, ["batch", (await reportBatch()).id] as [string, string]]
  return (
    <a className={prominent ? "export-button primary" : "export-button"} href={exportHref(view, mode, pinned)}>
      <Download aria-hidden="true" size={15} />
      {children}
    </a>
  )
}
