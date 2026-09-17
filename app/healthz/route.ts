import packageJson from "@/package.json"

export async function GET() {
  return Response.json(
    { ok: true, service: "aftersales-dashboard", version: packageJson.version },
    { headers: { "cache-control": "no-store" } },
  )
}
