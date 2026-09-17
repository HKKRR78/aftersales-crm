import Image from "next/image"
import { Suspense, type ReactNode } from "react"

import brandMark from "@/public/brand/yuyuan-mark-dark.png"
import { currentUser } from "@/src/auth/current-user"

import { AppNavigation } from "./app-navigation"

export function AppShell({
  dataLabel = "数据仓库定时同步",
  children,
}: {
  dataLabel?: string
  children: ReactNode
}) {
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">跳到主要内容</a>
      <aside className="sidebar">
        <div className="brand">
          <Image className="brand-mark" src={brandMark} alt="" aria-hidden="true" sizes="40px" preload />
          <span><strong>榆园售后</strong><small>经营分析中心</small></span>
        </div>
        <Suspense fallback={null}><ReportNavigation /></Suspense>
        <div className="sidebar-note">
          <span className="live-dot" />
          <span>{dataLabel}</span>
        </div>
      </aside>
      <main className="main-content" id="main-content">
        <header className="topbar">
          <div>
            <span className="eyebrow">AFTERSALES INTELLIGENCE</span>
            <h1>售后经营看板</h1>
          </div>
          <Suspense fallback={<div aria-label="正在读取员工身份" className="viewer viewer-skeleton"><span className="avatar" /><span /></div>}>
            <CurrentUserViewer />
          </Suspense>
        </header>
        {children}
      </main>
    </div>
  )
}

async function ReportNavigation() {
  return <AppNavigation />
}

async function CurrentUserViewer() {
  const user = await currentUser()
  return (
    <div className="viewer">
      <span className="avatar">{user.displayName.slice(0, 1)}</span>
      <span><strong>{user.displayName}</strong><small>{user.role === "admin" ? "管理员" : "员工"}</small></span>
    </div>
  )
}
