import ReactMarkdown from 'react-markdown'
import rehypeSanitize, { defaultSchema } from 'rehype-sanitize'
import SourcesBox from './SourcesBox'
import type { Message } from '../types'

// Mở rộng schema sanitize để cho phép a[target] + a[rel]
// (mặc định rehype-sanitize chặn target → link không mở tab mới)
const _schema = {
  ...defaultSchema,
  protocols: {
    ...defaultSchema.protocols,
    href: ['http', 'https', 'mailto'],
  },
  attributes: {
    ...defaultSchema.attributes,
    a: [
      ...(defaultSchema.attributes?.a ?? []),
      ['target', 'rel'],
    ],
  },
}

function SafeLink(props: React.AnchorHTMLAttributes<HTMLAnchorElement>) {
  const { children, href, ...rest } = props
  return (
    <a href={href} target="_blank" rel="noopener noreferrer" {...rest}>
      {children}
    </a>
  )
}

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
        <ReactMarkdown
          rehypePlugins={[[rehypeSanitize, _schema]]}
          components={{ a: SafeLink }}
        >
          {msg.content}
        </ReactMarkdown>
      </div>
      <SourcesBox sources={msg.sources} />
    </div>
  )
}