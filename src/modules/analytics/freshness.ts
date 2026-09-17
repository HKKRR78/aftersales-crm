export interface FreshnessStatus {
  state: "fresh" | "stale" | "unknown"
  ageHours: number | null
  maxAgeHours: number
}

export function sourceFreshness(
  syncedAt: string,
  now = new Date(),
  maxAgeHours = Number(process.env.AFTERSALES_MAX_SOURCE_AGE_HOURS || 16),
): FreshnessStatus {
  if (!syncedAt) return { state: "unknown", ageHours: null, maxAgeHours }
  const timestamp = new Date(syncedAt.replace(" ", "T"))
  if (Number.isNaN(timestamp.getTime())) return { state: "unknown", ageHours: null, maxAgeHours }
  const ageHours = Math.max(0, (now.getTime() - timestamp.getTime()) / 3_600_000)
  return { state: ageHours <= maxAgeHours ? "fresh" : "stale", ageHours, maxAgeHours }
}
