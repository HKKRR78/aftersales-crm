import Link from "next/link"

export default function NotFound() {
  return <main className="fatal-error"><span>404</span><h1>没有这个页面</h1><p>该入口已不属于新版售后看板。</p><Link href="/">返回经营总览</Link></main>
}
