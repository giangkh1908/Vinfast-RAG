import type { SessionItem } from '../../types/admin'

interface Props {
  sessions: SessionItem[]
}

export default function AdminSessionsTable({ sessions }: Props) {
  return (
    <div className="admin-table-container">
      <table className="admin-table">
        <thead>
          <tr>
            <th>Session ID</th>
            <th>Lượt Hỏi (Turns)</th>
            <th>Tổng Tokens</th>
            <th>Chi Phí (VNĐ)</th>
            <th>IP Khách</th>
            <th>Bắt Đầu</th>
            <th>Hoạt Động Cuối</th>
          </tr>
        </thead>
        <tbody>
          {sessions.length === 0 ? (
            <tr>
              <td colSpan={7} className="empty-cell">
                Chưa có phiên chat nào
              </td>
            </tr>
          ) : (
            sessions.map((se, i) => (
              <tr key={i}>
                <td className="mono">{se.session_id}</td>
                <td>
                  <span className="badge-turn">{se.total_turns} turns</span>
                </td>
                <td>{se.total_tokens.toLocaleString()}</td>
                <td>{se.total_cost_vnd.toLocaleString('vi-VN')} đ</td>
                <td className="mono">{se.client_ip || 'unknown'}</td>
                <td className="time-cell">
                  {se.first_seen ? new Date(se.first_seen).toLocaleString('vi-VN') : '-'}
                </td>
                <td className="time-cell">
                  {se.last_seen ? new Date(se.last_seen).toLocaleString('vi-VN') : '-'}
                </td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  )
}
