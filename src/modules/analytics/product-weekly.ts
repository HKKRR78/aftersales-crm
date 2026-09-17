import type { DateWindow, IssueRow, ProductWeeklyRow } from "./types"

export function buildProductWeeklyRows({
  rows,
  queryWindows,
  displayWeeks,
  selectedWeekStart,
}: {
  rows: IssueRow[]
  queryWindows: DateWindow[]
  displayWeeks: DateWindow[]
  selectedWeekStart: string
}) {
  const selectedIndex = queryWindows.findIndex((window) => window.start === selectedWeekStart)
  if (selectedIndex < 1) throw new Error("所选产品周缺少前一周比较窗口")
  const previousIndex = selectedIndex - 1
  const displayIndexes = displayWeeks.map((window) => queryWindows.findIndex((candidate) => candidate.start === window.start))
  const groups = new Map<string, { name: string; issues: number[]; links: Set<string> }>()

  for (const row of rows.filter((item) => item.includedInOperating && item.code !== "未填")) {
    const group = groups.get(row.code) ?? {
      name: row.name || "未命名产品",
      issues: row.weeks.map(() => 0),
      links: new Set<string>(),
    }
    row.weeks.forEach((week, index) => { group.issues[index] += week.issues })
    if (row.productId) group.links.add(row.productId)
    if ((row.name || "").length > group.name.length) group.name = row.name
    groups.set(row.code, group)
  }

  const productRows: ProductWeeklyRow[] = [...groups.entries()].map(([code, group]) => {
    const selectedIssues = group.issues[selectedIndex] ?? 0
    const previousIssues = group.issues[previousIndex] ?? 0
    return {
      key: code,
      code,
      label: group.name,
      secondary: `${code} · ${group.links.size} 个链接`,
      linkCount: group.links.size,
      selectedIssues,
      previousIssues,
      deltaIssues: selectedIssues - previousIssues,
      weeklyIssues: displayIndexes.map((index) => group.issues[index] ?? 0),
      detailHref: `/detail?basis=created&scope=all&week_start=${selectedWeekStart}&merchant_code=${encodeURIComponent(code)}`,
    }
  }).filter((row) => row.selectedIssues > 0)
    .sort((a, b) => b.selectedIssues - a.selectedIssues || a.code.localeCompare(b.code, "zh-CN"))

  const unmatchedIssues = rows
    .filter((row) => row.includedInOperating && row.code === "未填")
    .reduce((sum, row) => sum + (row.weeks[selectedIndex]?.issues ?? 0), 0)

  return { productRows, unmatchedIssues, selectedIndex, previousIndex }
}
