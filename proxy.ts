import { NextResponse, type NextRequest } from "next/server"

const publicSuffixes = ["/healthz", "/readyz"]

export function proxy(request: NextRequest) {
  const path = request.nextUrl.pathname
  const publicRequest = publicSuffixes.some((suffix) => path.endsWith(suffix)) || path.includes("/_next/")
  if (publicRequest) return NextResponse.next()

  if (process.env.NODE_ENV !== "production" && process.env.AFTERSALES_DEV_DATA === "fixture") {
    const requestHeaders = new Headers(request.headers)
    requestHeaders.set("x-company-user-id", "local-acceptance")
    requestHeaders.set("x-company-user-name", encodeURIComponent("本地验收"))
    requestHeaders.set("x-company-role", "admin")
    return NextResponse.next({ request: { headers: requestHeaders } })
  }

  const userId = request.headers.get("x-company-user-id")?.trim()
  const userName = request.headers.get("x-company-user-name")?.trim()
  const role = request.headers.get("x-company-role")?.trim()
  if (!userId || !userName || (role !== "admin" && role !== "viewer")) {
    return NextResponse.json(
      { ok: false, error: "请从公司员工统一入口登录" },
      { status: 401, headers: { "cache-control": "no-store" } },
    )
  }
  return NextResponse.next()
}
