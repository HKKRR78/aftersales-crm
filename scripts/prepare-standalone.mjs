import { cpSync, existsSync, mkdirSync } from "node:fs"
import path from "node:path"

const projectRoot = process.cwd()
const standaloneRoot = path.join(projectRoot, ".next", "standalone")
const staticSource = path.join(projectRoot, ".next", "static")
const staticTarget = path.join(standaloneRoot, ".next", "static")

if (!existsSync(path.join(standaloneRoot, "server.js"))) {
  throw new Error("Next.js standalone server was not generated")
}

mkdirSync(path.dirname(staticTarget), { recursive: true })
cpSync(staticSource, staticTarget, { recursive: true, force: true })

const publicSource = path.join(projectRoot, "public")
if (existsSync(publicSource)) {
  cpSync(publicSource, path.join(standaloneRoot, "public"), { recursive: true, force: true })
}

console.info("Standalone runtime prepared")
