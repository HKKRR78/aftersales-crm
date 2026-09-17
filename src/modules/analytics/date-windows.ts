import { addDays, differenceInCalendarWeeks, format, isValid, parseISO, startOfDay, startOfWeek, subDays, subWeeks } from "date-fns"

import type { DateWindow, PeriodMode } from "./types"

const ISO_DATE = "yyyy-MM-dd"

// Derive the business calendar day independently of the server's local TZ.
export function shanghaiToday(now = new Date()) {
  const parts = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(now)
  const value = (type: string) => Number(parts.find(part => part.type === type)!.value)
  return new Date(value("year"), value("month") - 1, value("day"))
}

function iso(value: Date) {
  return format(value, ISO_DATE)
}

export function closedWeekWindows(today = shanghaiToday(), count = 5): DateWindow[] {
  const currentWeekStart = startOfWeek(startOfDay(today), { weekStartsOn: 0 })
  const lastCompleteEnd = currentWeekStart
  const lastCompleteStart = subWeeks(lastCompleteEnd, 1)

  return Array.from({ length: count }, (_, index) => {
    const distance = count - index - 1
    const start = subWeeks(lastCompleteStart, distance)
    const end = addDays(start, 7)
    return {
      start: iso(start),
      end: iso(end),
      label: `${format(start, "MMdd")}-${format(subDays(end, 1), "MMdd")}`,
    }
  })
}

export function progressWeekWindows(today = shanghaiToday()): DateWindow[] {
  const currentEnd = startOfDay(today)
  const currentStart = startOfWeek(currentEnd, { weekStartsOn: 0 })
  const previousStart = subWeeks(currentStart, 1)
  const previousEnd = subWeeks(currentEnd, 1)

  const window = (prefix: string, start: Date, end: Date): DateWindow => ({
    start: iso(start),
    end: iso(end),
    observeEnd: iso(end),
    label:
      start >= end
        ? `${prefix}（无完整日）`
        : `${prefix} ${format(start, "MMdd")}-${format(subDays(end, 1), "MMdd")}`,
  })

  return [
    window("上周同期", previousStart, previousEnd),
    window("本周同期", currentStart, currentEnd),
  ]
}

export function windowsFor(mode: PeriodMode, today = shanghaiToday()) {
  return mode === "progress" ? progressWeekWindows(today) : closedWeekWindows(today)
}

export function productReportSelection(
  requestedStart: string | undefined,
  today = shanghaiToday(),
  earliestCreatedAt?: string | null,
) {
  const latestCompleteWeek = closedWeekWindows(today, 1)[0]
  const parsedEarliest = earliestCreatedAt ? parseISO(earliestCreatedAt.slice(0, 10)) : null
  const earliestWeekStart = parsedEarliest && isValid(parsedEarliest)
    ? startOfWeek(startOfDay(parsedEarliest), { weekStartsOn: 0 })
    : subWeeks(parseISO(latestCompleteWeek.start), 4)
  const availableWeekCount = Math.max(
    1,
    differenceInCalendarWeeks(parseISO(latestCompleteWeek.start), earliestWeekStart, { weekStartsOn: 0 }) + 1,
  )
  const selectableWeeks = closedWeekWindows(today, availableWeekCount)
  const selected = selectableWeeks.find((window) => window.start === requestedStart) ?? selectableWeeks.at(-1)!
  const selectedIndex = selectableWeeks.findIndex((window) => window.start === selected.start)
  const displayChronological = selectableWeeks.slice(Math.max(0, selectedIndex - 4), selectedIndex + 1)
  const comparisonStart = subWeeks(parseISO(displayChronological[0].start), 1)
  const comparisonWindow: DateWindow = {
    start: iso(comparisonStart),
    end: displayChronological[0].start,
    label: `${format(comparisonStart, "MMdd")}-${format(subDays(parseISO(displayChronological[0].start), 1), "MMdd")}`,
  }
  return {
    selected,
    selectableWeeks,
    displayWeeks: [...displayChronological].reverse(),
    queryWindows: [comparisonWindow, ...displayChronological],
  }
}

export function completedDays(window: DateWindow) {
  const start = new Date(`${window.start}T00:00:00`)
  const end = new Date(`${window.end}T00:00:00`)
  return Math.max(0, Math.round((end.getTime() - start.getTime()) / 86_400_000))
}
