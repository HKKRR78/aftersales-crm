import { describe, expect, it } from "vitest"

import { closedWeekWindows, progressWeekWindows, shanghaiToday } from "@/src/modules/analytics/date-windows"

describe("analysis windows", () => {
  it("switches the business date at Shanghai midnight", () => {
    const before = shanghaiToday(new Date("2026-09-12T15:59:59Z"))
    const after = shanghaiToday(new Date("2026-09-12T16:00:00Z"))
    expect(closedWeekWindows(before, 1)[0].start).toBe("2026-08-30")
    expect(closedWeekWindows(after, 1)[0].start).toBe("2026-09-06")
  })
  it("uses Sunday through Saturday for complete weeks", () => {
    const windows = closedWeekWindows(new Date(2026, 7, 25, 11, 0, 0), 2)
    expect(windows).toEqual([
      { start: "2026-08-09", end: "2026-08-16", label: "0809-0815" },
      { start: "2026-08-16", end: "2026-08-23", label: "0816-0822" },
    ])
  })

  it("switches to the just-finished week on Sunday and crosses the year boundary", () => {
    expect(closedWeekWindows(new Date(2027, 0, 3, 9, 0, 0), 1)).toEqual([
      { start: "2026-12-27", end: "2027-01-03", label: "1227-0102" },
    ])
  })

  it("compares completed days at the same weekly progress", () => {
    const windows = progressWeekWindows(new Date(2026, 7, 25, 16, 30, 0))
    expect(windows[0]).toEqual({
      start: "2026-08-16",
      end: "2026-08-18",
      observeEnd: "2026-08-18",
      label: "上周同期 0816-0817",
    })
    expect(windows[1]).toEqual({
      start: "2026-08-23",
      end: "2026-08-25",
      observeEnd: "2026-08-25",
      label: "本周同期 0823-0824",
    })
  })

  it("shows an empty progress window on Sunday", () => {
    const windows = progressWeekWindows(new Date(2026, 7, 23, 9, 0, 0))
    expect(windows[1].start).toBe(windows[1].end)
    expect(windows[1].label).toContain("无完整日")
  })
})
