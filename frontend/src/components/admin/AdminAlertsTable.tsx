import { useState } from 'react'
import type { AlertItem } from '../../types/admin'

interface Props {
  alerts: AlertItem[]
  onRefresh: () => Promise<void>
}

export default function AdminAlertsTable({ alerts, onRefresh }: Props) {
  const [filter, setFilter] = useState<'ALL' | 'CRITICAL' | 'WARNING'>('ALL')
  const [testing, setTesting] = useState<boolean>(false)

  const handleTestAlert = async (severity: 'WARNING' | 'CRITICAL') => {
    try {
      setTesting(true)
      await fetch(`/api/admin/metrics/alerts/test?severity=${severity}`, { method: 'POST' })
      await onRefresh()
    } finally {
      setTesting(false)
    }
  }

  const filteredAlerts = alerts.filter((a) => {
    if (filter === 'ALL') return true
    return a.severity.toUpperCase() === filter
  })

  return (
    <div className="admin-table-container">
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: 16,
          flexWrap: 'wrap',
          gap: 12,
        }}
      >
        <div style={{ display: 'flex', gap: 8 }}>
          <button
            className={`filter-pill ${filter === 'ALL' ? 'active' : ''}`}
            onClick={() => setFilter('ALL')}
          >
            Tất cả ({alerts.length})
          </button>
          <button
            className={`filter-pill danger ${filter === 'CRITICAL' ? 'active' : ''}`}
            onClick={() => setFilter('CRITICAL')}
          >
            🚨 Khẩn cấp / Critical ({alerts.filter((a) => a.severity === 'CRITICAL').length})
          </button>
          <button
            className={`filter-pill warning ${filter === 'WARNING' ? 'active' : ''}`}
            onClick={() => setFilter('WARNING')}
          >
            ⚠️ Cảnh báo / Warning ({alerts.filter((a) => a.severity === 'WARNING').length})
          </button>
        </div>

        <div style={{ display: 'flex', gap: 8 }}>
          <button
            className="admin-action-btn"
            disabled={testing}
            onClick={() => handleTestAlert('WARNING')}
            title="Gửi sự kiện Warning giả lập vào Kafka"
          >
            <i className="mdi mdi-bell-alert-outline"></i> Test Warning Event
          </button>
          <button
            className="admin-action-btn danger"
            disabled={testing}
            onClick={() => handleTestAlert('CRITICAL')}
            title="Bắn sự kiện Critical qua Kafka và kích hoạt gửi Email"
          >
            <i className="mdi mdi-email-alert-outline"></i> {testing ? 'Đang gửi...' : 'Test Gửi Email Critical'}
          </button>
        </div>
      </div>

      <table className="admin-table">
        <thead>
          <tr>
            <th>ID</th>
            <th>Thời Gian</th>
            <th>Mức Độ</th>
            <th>Loại Sự Cố</th>
            <th>Tiêu Đề &amp; Thông Báo</th>
            <th>Gửi Email?</th>
            <th>Chi Tiết</th>
          </tr>
        </thead>
        <tbody>
          {filteredAlerts.length === 0 ? (
            <tr>
              <td colSpan={7} className="empty-cell">
                Chưa ghi nhận sự cố nào trong danh sách cảnh báo
              </td>
            </tr>
          ) : (
            filteredAlerts.map((al) => (
              <tr key={al.id}>
                <td className="mono">#{al.id}</td>
                <td className="time-cell">
                  {al.created_at ? new Date(al.created_at).toLocaleString('vi-VN') : ''}
                </td>
                <td>
                  {al.severity === 'CRITICAL' ? (
                    <span className="status-pill danger">🚨 CRITICAL</span>
                  ) : (
                    <span className="status-pill warning">⚠️ WARNING</span>
                  )}
                </td>
                <td>
                  <span className="intent-tag">{al.alert_type}</span>
                </td>
                <td>
                  <strong style={{ display: 'block', color: '#f8fafc', marginBottom: 2 }}>
                    {al.title}
                  </strong>
                  <span style={{ fontSize: 12, color: '#94a3b8' }}>{al.message}</span>
                </td>
                <td>
                  {al.email_sent ? (
                    <span className="status-pill success">
                      <i className="mdi mdi-check"></i> Đã gửi Mail
                    </span>
                  ) : al.severity === 'CRITICAL' ? (
                    <span className="status-pill neutral">Chưa gửi</span>
                  ) : (
                    <span className="status-pill neutral">Chỉ lưu Log</span>
                  )}
                </td>
                <td>
                  <pre
                    style={{
                      fontSize: 11,
                      background: '#0b1329',
                      padding: '4px 8px',
                      borderRadius: 4,
                      margin: 0,
                      maxHeight: 60,
                      overflow: 'auto',
                      color: '#38bdf8',
                    }}
                  >
                    {JSON.stringify(al.details, null, 2)}
                  </pre>
                </td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  )
}
