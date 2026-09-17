"use client"

import { Boxes, ClipboardList, LayoutDashboard, PackageSearch, Settings } from "lucide-react"
import Link, { useLinkStatus } from "next/link"
import { usePathname } from "next/navigation"

const navigation = [
  { href: "/", label: "经营总览", icon: LayoutDashboard },
  { href: "/detail", label: "问题明细", icon: ClipboardList },
  { href: "/products", label: "产品分析", icon: PackageSearch },
  { href: "/warehouses", label: "仓库分析", icon: Boxes },
  { href: "/settings", label: "规则设置", icon: Settings },
] as const

function PendingMark() {
  const { pending } = useLinkStatus()
  return <span aria-hidden="true" className={pending ? "nav-pending visible" : "nav-pending"} />
}

export function AppNavigation() {
  const pathname = usePathname()

  return (
    <nav aria-label="售后看板导航">
      {navigation.map((item) => {
        const Icon = item.icon
        const active = item.href === "/" ? pathname === item.href : pathname.startsWith(item.href)
        return (
          <Link aria-current={active ? "page" : undefined} className={active ? "nav-item active" : "nav-item"} href={item.href} key={item.href}>
            <Icon aria-hidden="true" size={18} />
            <span>{item.label}</span>
            <PendingMark />
          </Link>
        )
      })}
    </nav>
  )
}
