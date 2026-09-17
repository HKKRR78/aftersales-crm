import "server-only"

import { headers } from "next/headers"

export interface CurrentUser {
  id: string
  displayName: string
  role: "admin" | "viewer"
}

export async function currentUser(): Promise<CurrentUser> {
  const requestHeaders = await headers()
  const id = requestHeaders.get("x-company-user-id")?.trim() || ""
  const rawName = requestHeaders.get("x-company-user-name")?.trim() || ""
  const role = requestHeaders.get("x-company-role")?.trim()
  if (!id || !rawName || (role !== "admin" && role !== "viewer")) {
    throw new Error("UNAUTHORIZED_COMPANY_IDENTITY")
  }
  let displayName = rawName
  try {
    displayName = decodeURIComponent(rawName)
  } catch {
    // Keep the validated header value when it is not percent-encoded.
  }
  return { id, displayName, role }
}
