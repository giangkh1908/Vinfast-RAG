import type { OverviewData } from '../../types/admin'

interface Props {
  overview: OverviewData | null
}

export default function AdminKpiCards({ overview }: Props) {
  return (
    <div className="admin-kpi-grid">
      <div className="admin-kpi-card">
        <div className="kpi-icon blue">
          <i className="mdi mdi-message-text-fast-outline"></i>
        </div>
        <div className="kpi-info">
          <span className="kpi-label">Tổng Lượt Chat</span>
          <h3 className="kpi-val">{(overview?.total_requests ?? 0).toLocaleString()}</h3>
          <span className="kpi-sub">
            Lỗi/Reject: {overview?.total_errors ?? 0} ({overview?.error_rate_pct ?? 0}%)
          </span>
        </div>
      </div>

      <div className="admin-kpi-card">
        <div className="kpi-icon purple">
          <i className="mdi mdi-currency-usd"></i>
        </div>
        <div className="kpi-info">
          <span className="kpi-label">Chi Phí LLM</span>
          <h3 className="kpi-val">
            {(overview?.total_cost_vnd ?? 0).toLocaleString('vi-VN')} đ
          </h3>
          <span className="kpi-sub">
            ${(overview?.total_cost_usd ?? 0).toFixed(4)} USD • {(overview?.total_tokens ?? 0).toLocaleString()} tokens
          </span>
        </div>
      </div>

      <div className="admin-kpi-card">
        <div className="kpi-icon yellow">
          <i className="mdi mdi-timer-sand"></i>
        </div>
        <div className="kpi-info">
          <span className="kpi-label">Độ Trễ P95 & TTFT</span>
          <h3 className="kpi-val">{overview?.p95_latency_ms ?? 0} ms</h3>
          <span className="kpi-sub">
            TTFT Avg: {overview?.avg_ttft_ms ?? 0} ms • P50: {overview?.p50_latency_ms ?? 0} ms
          </span>
        </div>
      </div>

      <div className="admin-kpi-card">
        <div className="kpi-icon green">
          <i className="mdi mdi-lightning-bolt-outline"></i>
        </div>
        <div className="kpi-info">
          <span className="kpi-label">Tỷ Lệ Cache Hit</span>
          <h3 className="kpi-val">{overview?.cache_hit_rate_pct ?? 0}%</h3>
          <span className="kpi-sub">
            {overview?.cache_hits ?? 0} turns trả lời tức thì (&lt;10ms)
          </span>
        </div>
      </div>
    </div>
  )
}
