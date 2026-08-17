import ReactMarkdown from 'react-markdown'
import rehypeSanitize from 'rehype-sanitize'
import SourcesBox from './SourcesBox'
import type { Message } from '../types'

export default function MessageBubble({ msg }: { msg: Message }) {
  if (msg.role === 'user') {
    return <div className="msg user">{msg.content}</div>
  }

  const error = msg.status === 'error'
  // Đang chờ token đầu tiên → KHÔNG render dots ở bubble
  // (StatusBar là nơi duy nhất hiển thị tiến độ — tránh duplicate)
  const pending = (msg.status === 'sending' || msg.status === 'streaming') && !msg.content

  if (error) {
    return (
      <div className="msg assistant">
        <div className="msg-error">
          <div>{msg.error || 'Không có phản hồi.'}</div>
        </div>
      </div>
    )
  }

  if (pending) return null

  return (
    <div className="msg assistant">
      <div className="md">
        <ReactMarkdown rehypePlugins={[rehypeSanitize]}>{msg.content}</ReactMarkdown>
      </div>
      <SourcesBox sources={msg.sources} />
    </div>
  )
}
