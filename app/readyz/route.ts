import { addDays, differenceInCalendarDays, parseISO, startOfDay, subDays } from "date-fns"

import { checkDatabase } from "@/src/db/mysql"
import { windowsFor } from "@/src/modules/analytics/date-windows"
import { isDevFixtureMode } from "@/src/modules/analytics/dev-mode"
import { DataUnavailableError } from "@/src/modules/analytics/errors"
import { sourceFreshness } from "@/src/modules/analytics/freshness"
import { reportBatch, latestCompleteOrderDay, latestProductOrderDay, sourceSnapshot, requireCalculatedPeriods } from "@/src/modules/analytics/repository"

export async function GET() {
  if (isDevFixtureMode()) {
    return Response.json(
      { ok: true, service: "aftersales-dashboard", source: { sourceType: "fixture", state: "fresh" } },
      { headers: { "cache-control": "no-store" } },
    )
  }
  try {
    const batch = await reportBatch()
    if (batch.verification === "candidate") {
      return Response.json({ ok: false, service: "aftersales-dashboard", batchId: batch.id,
        analytics: { state: "candidate", code: "report_not_verified" } },
      { status: 503, headers: { "cache-control": "no-store" } })
    }
    if (batch.verificationKind !== "full") {
      const [databaseLatencyMs, source] = await Promise.all([checkDatabase(), sourceSnapshot(batch)])
      const freshness = sourceFreshness(source.syncedAt)
      const issueReady = batch.issueCoverageApproved === true && batch.salesCoverageApproved === false && freshness.state === "fresh"
      return Response.json(
        {
          ok: issueReady,
          service: "aftersales-dashboard",
          databaseLatencyMs,
          source: { syncedAt: source.syncedAt, coverageStart: source.coverageStart, coverageEnd: source.coverageEnd, batchId: source.batchId, reconciliationStatus: source.reconciliationStatus, ...sourceFreshness(source.syncedAt) },
          orders: { through: null },
          productOrders: { through: null, state: "unavailable" },
          analytics: { state: issueReady ? "issue_facts_ready" : "partial", code: "denominators_pending_verification" },
        },
        { status: issueReady ? 200 : 503, headers: { "cache-control": "no-store" } },
      )
    }
    const [databaseLatencyMs, source, orderWatermark, productOrderWatermark] = await Promise.all([
      checkDatabase(),
      sourceSnapshot(batch),
      latestCompleteOrderDay(batch),
      latestProductOrderDay(batch),
    ])
    const freshness = sourceFreshness(source.syncedAt)
    const orderLagDays = Math.max(
      0,
      differenceInCalendarDays(subDays(startOfDay(new Date()), 1), parseISO(orderWatermark.statDate)),
    )
    const maxOrderLagDays = Number(process.env.AFTERSALES_MAX_ORDER_LAG_DAYS || 2)
    const productOrderLagDays = productOrderWatermark ? Math.max(
      0,
      differenceInCalendarDays(subDays(startOfDay(new Date()), 1), parseISO(productOrderWatermark.statDate)),
    ) : null
    const progressToday = addDays(parseISO(orderWatermark.statDate), 1)
    try {
      // A verified source can contain a documented unresolved attribution.
      // Its ratio remains null; that differs from a missing/failed source or
      // an uncalculated period, both of which prevent readiness.
      await Promise.all([
        requireCalculatedPeriods(windowsFor("closed"), batch),
        requireCalculatedPeriods(windowsFor("progress", progressToday), batch),
      ])
    } catch (error) {
      if (error instanceof DataUnavailableError) {
        return Response.json(
          {
            ok: false,
            service: "aftersales-dashboard",
            databaseLatencyMs,
            source: { syncedAt: source.syncedAt, coverageStart: source.coverageStart, coverageEnd: source.coverageEnd, batchId: source.batchId, reconciliationStatus: source.reconciliationStatus, ...freshness },
            orders: { through: orderWatermark.statDate, lagDays: orderLagDays, maxLagDays: maxOrderLagDays },
            analytics: { state: "incomplete", code: error.code },
          },
          { status: 503, headers: { "cache-control": "no-store" } },
        )
      }
      throw error
    }

    const productOrdersReady = productOrderLagDays !== null && productOrderLagDays <= maxOrderLagDays
    const ok = freshness.state === "fresh" && orderLagDays <= maxOrderLagDays && productOrdersReady
    return Response.json(
      {
        ok,
        service: "aftersales-dashboard",
        databaseLatencyMs,
        source: { syncedAt: source.syncedAt, coverageStart: source.coverageStart, coverageEnd: source.coverageEnd, batchId: source.batchId, reconciliationStatus: source.reconciliationStatus, ...freshness },
        orders: { through: orderWatermark.statDate, lagDays: orderLagDays, maxLagDays: maxOrderLagDays },
        productOrders: { through: productOrderWatermark?.statDate || null, lagDays: productOrderLagDays, maxLagDays: maxOrderLagDays, state: productOrdersReady ? "ready" : "stale" },
        analytics: { state: orderLagDays > maxOrderLagDays ? "stale" : productOrdersReady ? "ready" : "partial" },
      },
      { status: ok ? 200 : 503, headers: { "cache-control": "no-store" } },
    )
  } catch {
    return Response.json({ ok: false, service: "aftersales-dashboard", database: "unavailable" }, { status: 503, headers: { "cache-control": "no-store" } })
  }
}
