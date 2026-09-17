import type { Metadata, Viewport } from "next"
import type { ReactNode } from "react"

import { AppShell } from "@/src/components/app-shell"
import { isDevFixtureMode } from "@/src/modules/analytics/dev-mode"
import { z0Mono, z0Sans, z0Serif } from "./fonts"

import "./globals.css"

export const metadata: Metadata = {
  title: "售后经营看板",
  description: "榆园集团售后经营分析与预警面板",
  icons: {
    icon: [
      { url: "/aftersales/brand/yuyuan-mark-light.png", media: "(prefers-color-scheme: light)" },
      { url: "/aftersales/brand/yuyuan-mark-dark.png", media: "(prefers-color-scheme: dark)" },
    ],
    apple: "/aftersales/brand/yuyuan-mark-light.png",
  },
}

export const viewport: Viewport = { themeColor: "#12392c" }

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body className={`${z0Sans.variable} ${z0Serif.variable} ${z0Mono.variable}`}>
        <AppShell dataLabel={isDevFixtureMode() ? "本地验收数据" : "数据仓库定时同步"}>{children}</AppShell>
      </body>
    </html>
  )
}
