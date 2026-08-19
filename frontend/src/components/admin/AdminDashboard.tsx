import { useState, useEffect, useCallback } from 'react'
import type {
  OverviewData,
  TimeseriesPoint,
  IntentPoint,
  TopIP,
  SessionItem,
  LogItem,
  AlertItem,
} from '../../types/admin'
import AdminKpiCards from './AdminKpiCards'
import AdminCharts from './AdminCharts'
import AdminTopIpsTable from './AdminTopIpsTable'
import AdminSessionsTable from './AdminSessionsTable'
import AdminLogsTable from './AdminLogsTable'
import AdminAlertsTable from './AdminAlertsTable'

export default function AdminDashboard() {
  const [hours, setHours] = useState<number>(24)
  const [autoRefresh, setAutoRefresh] = useState<number>(10)
  const [loading, setLoading] = useState<boolean>(true)
  const [activeTab, setActiveTab] = useState<'overview' | 'ips' | 'sessions' | 'logs' | 'alerts'>('overview')

  const [overview, setOverview] = useState<OverviewData | null>(null)
  const [timeseries, setTimeseries] = useState<TimeseriesPoint[]>([])
  const [intents, setIntents] = useState<IntentPoint[]>([])
  const [topIps, setTopIps] = useState<TopIP[]>([])
  const [sessions, setSessions] = useState<SessionItem[]>([])
  const [logs, setLogs] = useState<LogItem[]>([])
  const [alerts, setAlerts] = useState<AlertItem[]>([])

  const fetchData = useCallback(async () => {
    try {
      setLoading(true)
      const [ovRes, tsRes, inRes, ipRes, seRes, lgRes, alRes] = await Promise.all([
        fetch('/api/admin/metrics/overview?hours=' + hours).then((r) => r.json()).catch(() => null),
        fetch('/api/admin/metrics/timeseries?hours=' + hours).then((r) => r.json()).catch(() => null),
        fetch('/api/admin/metrics/intents?hours=' + hours).then((r) => r.json()).catch(() => null),
        fetch('/api/admin/metrics/top-ips?hours=' + hours).then((r) => r.json()).catch(() => null),
        fetch('/api/admin/metrics/sessions?hours=' + hours).then((r) => r.json()).catch(() => null),
        fetch('/api/admin/metrics/logs?limit=50').then((r) => r.json()).catch(() => null),
        fetch('/api/admin/metrics/alerts?limit=50').then((r) => r.json()).catch(() => null),
      ])

      if (ovRes?.data) setOverview(ovRes.data)
      if (tsRes?.data) setTimeseries(tsRes.data)
      if (inRes?.data) setIntents(inRes.data)
      if (ipRes?.data) setTopIps(ipRes.data)
      if (seRes?.data) setSessions(seRes.data)
      if (lgRes?.data?.logs) setLogs(lgRes.data.logs)
      if (alRes?.alerts) setAlerts(alRes.alerts)
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

  return (
    <div className="admin-page-container">
      {/* ── Top Header Bar ── */}
      <div className="admin-header">
        <div className="admin-header-title">
          <div className="admin-badge">ADMIN TELEMETRY</div>
          <h2>VinFast Chatbot Analytics &amp; Monitoring</h2>
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
        </div>
      </div>

      {/* ── Tabs Navigation ── */}
      <div className="admin-tabs">
        <button
          className={'admin-tab-btn ' + (activeTab === 'overview' ? 'active' : '')}
          onClick={() => setActiveTab('overview')}
        >
          <i className="mdi mdi-view-dashboard-outline"></i> Tổng quan &amp; Biểu đồ
        </button>
        <button
          className={'admin-tab-btn ' + (activeTab === 'ips' ? 'active' : '')}
          onClick={() => setActiveTab('ips')}
        >
          <i className="mdi mdi-shield-account-outline"></i> Top IP &amp; Chống Spam ({topIps.length})
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
        <button
          className={'admin-tab-btn ' + (activeTab === 'alerts' ? 'active' : '')}
          onClick={() => setActiveTab('alerts')}
        >
          <i className="mdi mdi-bell-ring-outline"></i> Cảnh Báo Hệ Thống ({alerts.length})
        </button>
      </div>

      {/* ── Body Content by Tab ── */}
      <div className="admin-body">
        {activeTab === 'overview' && (
          <>
            <AdminKpiCards overview={overview} />
            <AdminCharts timeseries={timeseries} intents={intents} />
          </>
        )}

        {activeTab === 'ips' && <AdminTopIpsTable topIps={topIps} />}

        {activeTab === 'sessions' && <AdminSessionsTable sessions={sessions} />}

        {activeTab === 'logs' && <AdminLogsTable logs={logs} />}

        {activeTab === 'alerts' && <AdminAlertsTable alerts={alerts} onRefresh={fetchData} />}
      </div>
    </div>
  )
}
