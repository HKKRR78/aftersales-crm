export function RouteLoading() {
  return (
    <div aria-busy="true" aria-live="polite" className="route-loading">
      <div className="route-loading-heading">
        <span className="skeleton-line short" />
        <span className="skeleton-line title" />
        <span className="skeleton-line copy" />
      </div>
      <div className="route-loading-grid">
        <span className="skeleton-panel" />
        <span className="skeleton-panel" />
        <span className="skeleton-panel wide" />
      </div>
      <span className="sr-only">正在更新售后数据</span>
    </div>
  )
}
