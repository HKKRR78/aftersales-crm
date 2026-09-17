export function isDevFixtureMode() {
  return process.env.NODE_ENV !== "production" && process.env.AFTERSALES_DEV_DATA === "fixture"
}
