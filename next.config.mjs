import { createHash } from "node:crypto"
import { readFileSync, readdirSync } from "node:fs"
import { join } from "node:path"

const sourceHash = createHash("sha256")
function hashTree(path) {
  for (const entry of readdirSync(path, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name))) {
    if (entry.name === "__pycache__") continue
    const target = join(path, entry.name)
    if (entry.isDirectory()) hashTree(target)
    else sourceHash.update(target).update(readFileSync(target))
  }
}
for (const directory of ["app", "src", "scripts"]) hashTree(directory)
for (const file of ["package.json", "pnpm-lock.yaml", "next.config.mjs", "proxy.ts"]) sourceHash.update(file).update(readFileSync(file))
const buildId = `crm061-${sourceHash.digest("hex").slice(0, 20)}`

/** @type {import('next').NextConfig} */
const nextConfig = {
  generateBuildId: async () => buildId,
  env: { CRM_BUILD_ID: buildId },
  basePath: "/aftersales",
  cacheComponents: true,
  output: "standalone",
  outputFileTracingIncludes: {
    "/*": ["./node_modules/@swc/helpers/**/*"],
  },
  poweredByHeader: false,
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "Cache-Control", value: "private, no-store" },
          { key: "X-Build-ID", value: buildId },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Referrer-Policy", value: "no-referrer" },
          { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
        ],
      },
    ]
  },
}

export default nextConfig
