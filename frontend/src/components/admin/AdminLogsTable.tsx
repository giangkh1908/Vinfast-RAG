import type { LogItem } from '../../types/admin'

interface Props {
  logs: LogItem[]
}

export default function AdminLogsTable({ logs }: Props) {
  return (
    <div className="admin-table-container">
      <table className="admin-table">
        <thead>
          <tr>
            <th>Thời Gian</th>
            <th>IP Khách</th>
            <th>Câu Hỏi (Query)</th>
            <th>Ý Định</th>
            <th>Quyết Định</th>
            <th>TTFT</th>
            <th>Tổng Độ Trễ</th>
            <th>Cache</th>
            <th>HTTP Status</th>
          </tr>
        </thead>
        <tbody>
          {logs.length === 0 ? (
            <tr>
              <td colSpan={9} className="empty-cell">
                Chưa có dữ liệu log gần đây
              </td>
            </tr>
          ) : (
            logs.map((lg) => (
              <tr key={lg.id}>
                <td className="time-cell">
                  {lg.created_at ? new Date(lg.created_at).toLocaleTimeString('vi-VN') : ''}
                </td>
                <td className="mono">{lg.client_ip}</td>
                <td className="query-cell" title={lg.query_text}>
                  <div className="query-truncate">{lg.query_text || '<trống>'}</div>
                </td>
                <td>
                  <span className="intent-tag">{lg.intent}</span>
                </td>
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
  )
}
