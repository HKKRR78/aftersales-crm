"use client"

export default function ErrorPage({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return <main className="fatal-error"><span>AFTERSALES DASHBOARD</span><h1>页面暂时无法打开</h1><p>服务没有返回可展示的数据，请稍后重试。</p><button onClick={reset}>重新加载</button></main>
}
