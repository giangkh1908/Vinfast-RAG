import { useState, useEffect, useCallback } from 'react'

interface Props {
  onClose: () => void
}

interface OverviewData {
  time_range_hours: number
  total_requests: number
  total_tokens: number
  total_prompt_tokens: number
  total_completion_tokens: number
  total_cost_usd: number
  total_cost_vnd: number
  avg_latency_ms: number
  p50_latency_ms: number
  p95_latency_ms: number
  avg_ttft_ms: number
  p50_ttft_ms: number
  p95_ttft_ms: number
  cache_hits: number
  cache_hit_rate_pct: number
  total_errors: number
  error_rate_pct: number
}

interface TimeseriesPoint {
  timestamp: string
  requests: number
  avg_latency_ms: number
  avg_ttft_ms: number
  total_tokens: number
  cost_usd: number
  cost_vnd: number
  cache_hits: number
}

interface IntentPoint {
  intent: string
  count: number
  avg_latency_ms: number
  total_tokens: number
  total_cost_vnd: number
}

interface TopIP {
  client_ip: string
  total_requests: number
  blocked_429: number
  error_requests: number
  total_cost_vnd: number
  last_request: string
}

interface SessionItem {
  session_id: string
  total_turns: number
  total_tokens: number
  total_cost_vnd: number
  total_cost_usd: number
  first_seen: string
  last_seen: string
  client_ip: string
}

interface LogItem {
  id: number
  request_id: string
  session_id: string | null
  client_ip: string
  created_at: string
  query_text: string
  intent: string
  decision: string
  model_used: string
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  cost_usd: number
  cost_vnd: number
  ttft_ms: number
  total_latency_ms: number
  cache_hit: boolean
  cache_type: string
  status_code: number
  error_message: string | null
}

export default function AdminDashboard({ onClose }: Props) {
  const [hours, setHours] = useState<number>(24)
  const [autoRefresh, setAutoRefresh] = useState<number>(10)
  const [loading, setLoading] = useState<boolean>(true)
  const [activeTab, setActiveTab] = useState<'overview' | 'ips' | 'sessions' | 'logs'>('overview')

  const [overview, setOverview] = useState<OverviewData | null>(null)
  const [timeseries, setTimeseries] = useState<TimeseriesPoint[]>([])
  const [intents, setIntents] = useState<IntentPoint[]>([])
  const [topIps, setTopIps] = useState<TopIP[]>([])
  const [sessions, setSessions] = useState<SessionItem[]>([])
  const [logs, setLogs] = useState<LogItem[]>([])

  const fetchData = useCallback(async () => {
    try {
      setLoading(true)
      const [ovRes, tsRes, inRes, ipRes, seRes, lgRes] = await Promise.all([
        fetch('/api/admin/metrics/overview?hours=' + hours).then((r) => r.json()).catch(() => null),
        fetch('/api/admin/metrics/timeseries?hours=' + hours).then((r) => r.json()).catch(() => null),
        fetch('/api/admin/metrics/intents?hours=' + hours).then((r) => r.json()).catch(() => null),
        fetch('/api/admin/metrics/top-ips?hours=' + hours).then((r) => r.json()).catch(() => null),
        fetch('/api/admin/metrics/sessions?hours=' + hours).then((r) => r.json()).catch(() => null),
        fetch('/api/admin/metrics/logs?limit=50').then((r) => r.json()).catch(() => null),
      ])

      if (ovRes?.data) setOverview(ovRes.data)
      if (tsRes?.data) setTimeseries(tsRes.data)
      if (inRes?.data) setIntents(inRes.data)
      if (ipRes?.data) setTopIps(ipRes.data)
      if (seRes?.data) setSessions(seRes.data)
      if (lgRes?.data?.logs) setLogs(lgRes.data.logs)
    } finally {
      setLoading(false)
    }
  }, [hours])

  useEffect(() => {
    void fetchData()
  }, [fetchData])

  useEffect(() => {
    if (autoRefresh <= 0) return
    const timer = setInterval(() => {
      void fetchData()
    }, autoRefresh * 1000)
    return () => clearInterval(timer)
  }, [autoRefresh, fetchData])

  const maxReq = Math.max(...timeseries.map((t) => t.requests), 1)

  return (
    <div className="admin-modal-overlay">
      <div className="admin-modal-container">
        <div className="admin-header">
          <div className="admin-header-title">
            <div className="admin-badge">ADMIN TELEMETRY</div>
            <h2>VinFast Chatbot Analytics & Monitoring</h2>
            <p>Hệ thống giám sát vận hành, chi phí LLM, phát hiện Spam và Audit Log</p>
          </div>

          <div className="admin-header-controls">
            <div className="admin-btn-group">
              <button
                className={'admin-btn ' + (hours === 24 ? 'active' : '')}
                onClick={() => setHours(24)}
              >
                24 Giờ
              </button>
              <button
                className={'admin-btn ' + (hours === 168 ? 'active' : '')}
                onClick={() => setHours(168)}
              >
                7 Ngày
              </button>
              <button
                className={'admin-btn ' + (hours === 720 ? 'active' : '')}
                onClick={() => setHours(720)}
              >
                30 Ngày
              </button>
            </div>

            <select
              className="admin-select"
              value={autoRefresh}
              onChange={(e) => setAutoRefresh(Number(e.target.value))}
            >
              <option value={0}>Tự làm mới: Tắt</option>
              <option value={5}>Tự làm mới: 5s</option>
              <option value={10}>Tự làm mới: 10s</option>
              <option value={30}>Tự làm mới: 30s</option>
            </select>

            <button className="admin-icon-btn" onClick={fetchData} title="Tải lại dữ liệu">
              <i className={'mdi mdi-refresh ' + (loading ? 'mdi-spin' : '')}></i>
            </button>

            <button className="admin-close-btn" onClick={onClose} title="Đóng">
              <i className="mdi mdi-close"></i>
            </button>
          </div>
        </div>

        <div className="admin-tabs">
          <button
            className={'admin-tab-btn ' + (activeTab === 'overview' ? 'active' : '')}
            onClick={() => setActiveTab('overview')}
          >
            <i className="mdi mdi-view-dashboard-outline"></i> Tổng quan & Biểu đồ
          </button>
          <button
            className={'admin-tab-btn ' + (activeTab === 'ips' ? 'active' : '')}
            onClick={() => setActiveTab('ips')}
          >
            <i className="mdi mdi-shield-account-outline"></i> Top IP & Chống Spam ({topIps.length})
          </button>
          <button
            className={'admin-tab-btn ' + (activeTab === 'sessions' ? 'active' : '')}
            onClick={() => setActiveTab('sessions')}
          >
            <i className="mdi mdi-account-multiple-outline"></i> Phiên Chat ({sessions.length})
          </button>
          <button
            className={'admin-tab-btn ' + (activeTab === 'logs' ? 'active' : '')}
            onClick={() => setActiveTab('logs')}
          >
            <i className="mdi mdi-format-list-bulleted"></i> Audit Request Logs ({logs.length})
          </button>
        </div>

        <div className="admin-body">
          {activeTab === 'overview' && (
            <>
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
                  <div className="kpi-icon green">
                    <i className="mdi mdi-currency-usd"></i>
                  </div>
                  <div className="kpi-info">
                    <span className="kpi-label">Chi Phí LLM</span>
                    <h3 className="kpi-val text-green">
                      {(overview?.total_cost_vnd ?? 0).toLocaleString('vi-VN')} đ
                    </h3>
                    <span className="kpi-sub">
                      ${(overview?.total_cost_usd ?? 0).toFixed(4)} USD •{' '}
                      {(overview?.total_tokens ?? 0).toLocaleString()} tokens
                    </span>
                  </div>
                </div>

                <div className="admin-kpi-card">
                  <div className="kpi-icon purple">
                    <i className="mdi mdi-lightning-bolt-outline"></i>
                  </div>
                  <div className="kpi-info">
                    <span className="kpi-label">Độ Trễ P95 & TTFT</span>
                    <h3 className="kpi-val">{typeof overview?.p95_latency_ms === 'number' ? overview.p95_latency_ms.toFixed(1) : 0} ms</h3>
                    <span className="kpi-sub">
                      TTFT Avg: {typeof overview?.avg_ttft_ms === 'number' ? overview.avg_ttft_ms.toFixed(1) : 0} ms • P50: {typeof overview?.p50_latency_ms === 'number' ? overview.p50_latency_ms.toFixed(1) : 0} ms
                    </span>
                  </div>
                </div>

                <div className="admin-kpi-card">
                  <div className="kpi-icon orange">
                    <i className="mdi mdi-database-check-outline"></i>
                  </div>
                  <div className="kpi-info">
                    <span className="kpi-label">Tỷ Lệ Cache Hit</span>
                    <h3 className="kpi-val text-orange">{typeof overview?.cache_hit_rate_pct === 'number' ? overview.cache_hit_rate_pct.toFixed(1) : 0}%</h3>
                    <span className="kpi-sub">
                      {overview?.cache_hits ?? 0} lượt trả lời tức thì (&lt;10ms)
                    </span>
                  </div>
                </div>
              </div>

              <div className="admin-charts-grid">
                <div className="admin-chart-box">
                  <div className="chart-box-header">
                    <h4>Lưu lượng Request theo giờ</h4>
                    <span className="badge">{timeseries.length} mốc giờ</span>
                  </div>
                  <div className="chart-bars-container">
                    {timeseries.length === 0 ? (
                      <div className="chart-empty">Chưa có dữ liệu trong khoảng thời gian này</div>
                    ) : (
                      timeseries.map((pt, i) => {
                        const hPct = maxReq > 0 ? Math.max(6, Math.round((pt.requests / maxReq) * 80)) : 6
                        const dateStr = pt.timestamp ? new Date(pt.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : ''
                        return (
                          <div key={i} className="bar-column" title={`${dateStr}: ${pt.requests} requests (${pt.cost_vnd.toLocaleString('vi-VN')} đ)`}>
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

                <div className="admin-chart-box">
                  <div className="chart-box-header">
                    <h4>Phân bổ Intent (Câu hỏi xe)</h4>
                    <span className="badge">{intents.length} loại</span>
                  </div>
                  <div className="intent-list-container">
                    {intents.length === 0 ? (
                      <div className="chart-empty">Chưa có dữ liệu phân loại</div>
                    ) : (
                      intents.map((it, i) => {
                        const totIntents = intents.reduce((s, x) => s + x.count, 0)
                        const pct = totIntents > 0 ? Math.round((it.count / totIntents) * 100) : 0
                        return (
                          <div key={i} className="intent-row">
                            <div className="intent-row-label">
                              <span className="intent-tag">{it.intent}</span>
                              <span className="intent-count">{it.count} lượt ({pct}%)</span>
                            </div>
                            <div className="intent-progress">
                              <div className="intent-progress-fill" style={{ width: pct + '%' }}></div>
                            </div>
                          </div>
                        )
                      })
                    )}
                  </div>
                </div>
              </div>
            </>
          )}

          {activeTab === 'ips' && (
            <div className="admin-table-wrapper">
              <table className="admin-data-table">
                <thead>
                  <tr>
                    <th>Client IP</th>
                    <th>Tổng Lượt Gọi</th>
                    <th>Bị Chặn Spam (429)</th>
                    <th>Lỗi Khác</th>
                    <th>Chi Phí (VNĐ)</th>
                    <th>Lần Cuối Gọi</th>
                    <th>Trạng Thái</th>
                  </tr>
                </thead>
                <tbody>
                  {topIps.length === 0 ? (
                    <tr><td colSpan={7} className="text-center py-6">Chưa có lịch sử IP</td></tr>
                  ) : (
                    topIps.map((ip, idx) => (
                      <tr key={idx}>
                        <td className="font-mono text-bold">{ip.client_ip}</td>
                        <td>{ip.total_requests.toLocaleString()}</td>
                        <td className={ip.blocked_429 > 0 ? 'text-red font-bold' : ''}>
                          {ip.blocked_429}
                        </td>
                        <td>{ip.error_requests}</td>
                        <td>{ip.total_cost_vnd.toLocaleString('vi-VN')} đ</td>
                        <td className="text-muted">{ip.last_request ? new Date(ip.last_request).toLocaleString('vi-VN') : '-'}</td>
                        <td>
                          {ip.blocked_429 > 5 ? (
                            <span className="status-pill danger">Cảnh báo Spam</span>
                          ) : (
                            <span className="status-pill success">Bình thường</span>
                          )}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          )}

          {activeTab === 'sessions' && (
            <div className="admin-table-wrapper">
              <table className="admin-data-table">
                <thead>
                  <tr>
                    <th>Session ID</th>
                    <th>Số Turn Chat</th>
                    <th>Tổng Tokens</th>
                    <th>Chi Phí (VNĐ)</th>
                    <th>Chi Phí ($ USD)</th>
                    <th>Bắt Đầu</th>
                    <th>Lần Cuối</th>
                  </tr>
                </thead>
                <tbody>
                  {sessions.length === 0 ? (
                    <tr><td colSpan={7} className="text-center py-6">Chưa có session nào</td></tr>
                  ) : (
                    sessions.map((ss, idx) => (
                      <tr key={idx}>
                        <td className="font-mono text-bold">{ss.session_id.slice(0, 8)}...{ss.session_id.slice(-4)}</td>
                        <td><span className="badge-turn">{ss.total_turns} turns</span></td>
                        <td>{ss.total_tokens.toLocaleString()}</td>
                        <td className="text-green font-bold">{ss.total_cost_vnd.toLocaleString('vi-VN')} đ</td>
                        <td className="text-muted">${ss.total_cost_usd.toFixed(4)}</td>
                        <td className="text-muted">{ss.first_seen ? new Date(ss.first_seen).toLocaleTimeString('vi-VN') : '-'}</td>
                        <td className="text-muted">{ss.last_seen ? new Date(ss.last_seen).toLocaleTimeString('vi-VN') : '-'}</td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          )}

          {activeTab === 'logs' && (
            <div className="admin-table-wrapper">
              <table className="admin-data-table">
                <thead>
                  <tr>
                    <th>Thời Gian</th>
                    <th>Client IP</th>
                    <th>Câu Hỏi (Query)</th>
                    <th>Intent</th>
                    <th>Decision</th>
                    <th>TTFT</th>
                    <th>Latency</th>
                    <th>Cache</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {logs.length === 0 ? (
                    <tr><td colSpan={9} className="text-center py-6">Chưa có log ghi nhận</td></tr>
                  ) : (
                    logs.map((lg) => (
                      <tr key={lg.id}>
                        <td className="text-muted font-mono" style={{ fontSize: '11px' }}>
                          {lg.created_at ? new Date(lg.created_at).toLocaleTimeString('vi-VN') : '-'}
                        </td>
                        <td className="font-mono" style={{ fontSize: '12px' }}>{lg.client_ip}</td>
                        <td className="query-col" title={lg.query_text}>
                          <div className="query-truncate">{lg.query_text || '<trống>'}</div>
                        </td>
                        <td><span className="intent-tag">{lg.intent}</span></td>
                        <td>{lg.decision}</td>
                        <td>{lg.ttft_ms} ms</td>
                        <td>{lg.total_latency_ms} ms</td>
                        <td>
                          {lg.cache_hit ? (
                            <span className="status-pill success">HIT ({lg.cache_type})</span>
                          ) : (
                            <span className="status-pill neutral">MISS</span>
                          )}
                        </td>
                        <td>
                          {lg.status_code === 200 ? (
                            <span className="status-pill success">200</span>
                          ) : lg.status_code === 429 ? (
                            <span className="status-pill danger">429 Block</span>
                          ) : (
                            <span className="status-pill danger">{lg.status_code}</span>
                          )}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
