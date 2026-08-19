import type { TimeseriesPoint, IntentPoint } from '../../types/admin'

interface Props {
  timeseries: TimeseriesPoint[]
  intents: IntentPoint[]
}

export default function AdminCharts({ timeseries, intents }: Props) {
  const maxReq = Math.max(...timeseries.map((t) => t.requests), 1)
  const maxIntent = Math.max(...intents.map((it) => it.count), 1)

  return (
    <div className="admin-charts-grid">
      {/* ── Hourly Traffic Bar Chart ── */}
      <div className="admin-chart-card">
        <div className="chart-card-header">
          <h4>
            <i className="mdi mdi-chart-bar"></i> Lưu lượng Request theo giờ
          </h4>
          <span className="chart-sub">Số lượng truy vấn &amp; Chi phí ước tính</span>
        </div>
        <div className="chart-bars-container">
          {timeseries.length === 0 ? (
            <div className="chart-empty">Chưa có dữ liệu trong khoảng thời gian này</div>
          ) : (
            timeseries.map((pt, i) => {
              const hPct = maxReq > 0 ? Math.max(6, Math.round((pt.requests / maxReq) * 80)) : 6
              const dateStr = pt.timestamp
                ? new Date(pt.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
                : ''
              return (
                <div
                  key={i}
                  className="bar-column"
                  title={`${dateStr}: ${pt.requests} requests (${pt.cost_vnd.toLocaleString('vi-VN')} đ)`}
                >
                  <span className={`bar-val ${pt.requests > 0 ? 'has-value' : 'zero'}`}>
                    {pt.requests}
                  </span>
                  <div className="bar-fill" style={{ height: `${hPct}%` }}></div>
                  <span className="bar-label">{dateStr}</span>
                </div>
              )
            })
          )}
        </div>
      </div>

      {/* ── Intent Distribution ── */}
      <div className="admin-chart-card">
        <div className="chart-card-header">
          <h4>
            <i className="mdi mdi-pie-chart-outline"></i> Phân loại Ý định (User Intent)
          </h4>
          <span className="chart-sub">Tỷ trọng các chủ đề xe VinFast được hỏi</span>
        </div>
        <div className="intent-list">
          {intents.length === 0 ? (
            <div className="chart-empty">Chưa có dữ liệu ý định</div>
          ) : (
            intents.map((it, i) => {
              const pct = Math.round((it.count / maxIntent) * 100)
              return (
                <div key={i} className="intent-row">
                  <div className="intent-info">
                    <span className="intent-name">{it.intent}</span>
                    <span className="intent-count">
                      {it.count} requests • {it.total_cost_vnd.toLocaleString('vi-VN')} đ
                    </span>
                  </div>
                  <div className="intent-progress">
                    <div className="intent-progress-fill" style={{ width: `${pct}%` }}></div>
                  </div>
                </div>
              )
            })
          )}
        </div>
      </div>
    </div>
  )
}
