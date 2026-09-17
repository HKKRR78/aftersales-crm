import "server-only"

import mysql from "mysql2/promise"

declare global {
  var aftersalesMysqlPool: mysql.Pool | undefined
}

function required(name: string, fallback?: string) {
  const value = process.env[name] || fallback
  if (!value) throw new Error(`Missing required environment variable: ${name}`)
  return value
}

export function getPool() {
  if (!globalThis.aftersalesMysqlPool) {
    globalThis.aftersalesMysqlPool = mysql.createPool({
      host: required("MYSQL_HOST", "127.0.0.1"),
      port: Number(process.env.MYSQL_PORT || 3306),
      user: required("MYSQL_USER"),
      password: process.env.MYSQL_PASSWORD || "",
      database: process.env.MYSQL_DATABASE || "ecom_profit",
      charset: "utf8mb4",
      dateStrings: true,
      enableKeepAlive: true,
      connectionLimit: Number(process.env.MYSQL_CONNECTION_LIMIT || 6),
      maxIdle: 3,
      idleTimeout: 60_000,
      queueLimit: 20,
    })
  }
  return globalThis.aftersalesMysqlPool
}

export async function checkDatabase() {
  const startedAt = performance.now()
  await getPool().query("SELECT 1")
  return Math.round(performance.now() - startedAt)
}
