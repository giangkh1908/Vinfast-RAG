import type { TopIP } from '../../types/admin'

interface Props {
  topIps: TopIP[]
}

export default function AdminTopIpsTable({ topIps }: Props) {
  return (
    <div className="admin-table-container">
      <table className="admin-table">
        <thead>
          <tr>
            <th>Địa Chỉ IP Khách</th>
            <th>Tổng Requests</th>
            <th>Bị Chặn 429 (Spam)</th>
            <th>Lỗi Khác</th>
            <th>Chi Phí (VNĐ)</th>
            <th>Truy Vấn Cuối</th>
            <th>Trạng Thái</th>
          </tr>
        </thead>
        <tbody>
          {topIps.length === 0 ? (
            <tr>
              <td colSpan={7} className="empty-cell">
                Chưa có dữ liệu IP trong khoảng thời gian này
              </td>
            </tr>
          ) : (
            topIps.map((ip, i) => (
              <tr key={i}>
                <td className="mono">{ip.client_ip}</td>
                <td>{ip.total_requests.toLocaleString()}</td>
                <td>
                  {ip.blocked_429 > 0 ? (
                    <span className="status-pill danger">{ip.blocked_429} blocked</span>
                  ) : (
                    <span className="status-pill neutral">0</span>
                  )}
                </td>
                <td>{ip.error_requests}</td>
                <td>{ip.total_cost_vnd.toLocaleString('vi-VN')} đ</td>
                <td className="time-cell">
                  {ip.last_request ? new Date(ip.last_request).toLocaleString('vi-VN') : '-'}
                </td>
                <td>
                  {ip.blocked_429 > 5 ? (
                    <span className="status-pill danger">Spam Warning</span>
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
  )
}
