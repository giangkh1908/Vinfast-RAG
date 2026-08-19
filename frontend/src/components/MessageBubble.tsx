import { useState, useMemo } from 'react'
import ReactMarkdown from 'react-markdown'
import rehypeSanitize, { defaultSchema } from 'rehype-sanitize'
import SourcesBox from './SourcesBox'
import type { Message } from '../types'

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

function formatTime(timestamp?: number): string {
  const date = timestamp ? new Date(timestamp) : new Date()
  return date.toLocaleTimeString('en-US', {
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
  })
}

const SHOW_MORE_THRESHOLD = 500

export default function MessageBubble({ msg }: { msg: Message }) {
  const [expanded, setExpanded] = useState(false)
  const timeStr = useMemo(() => formatTime(), [])

  if (msg.role === 'user') {
    return (
      <div className="chat-message--right chat-message" data-time={timeStr}>
        <span className="chat-message__avatar-frame chat-message__username">
          <i className="mdi mdi-account-circle" style={{ fontSize: 18, marginRight: 4 }}></i>
          Bạn
        </span>
        <div className="chat-message__text" title={timeStr}>
          <div className="chat-message_text_content chat-user-message">
            {msg.content}
          </div>
        </div>
        <div className="cb-time-sent">{timeStr}</div>
      </div>
    )
  }

  const error = msg.status === 'error'
  const pending = (msg.status === 'sending' || msg.status === 'streaming') && !msg.content

  if (error) {
    return (
      <div className="chat-message bot-message">
        <span className="chat-message__avatar-frame">
          <img
            alt="avatar"
            className="chat-message__avatar"
            src="./images/vivi-avatar.png"
            onError={(e) => {
              e.currentTarget.src = 'https://cdn-media.vinbase.ai/avatar/20250313024710_4.png'
            }}
          />
          VinFast
        </span>
        <div className="chat-message__text error-text">
          <div className="chat-message_text_content">
            <i className="mdi mdi-alert-circle-outline" style={{ marginRight: 6 }}></i>
            {msg.error || 'Đã có lỗi xảy ra khi xử lý phản hồi. Quý khách vui lòng thử lại.'}
          </div>
        </div>
      </div>
    )
  }

  if (pending) return null

  const streaming = msg.status === 'streaming' && !!msg.content
  const isLong = !streaming && msg.content.length > SHOW_MORE_THRESHOLD
  const shouldTruncate = isLong && !expanded

  const displayContent = shouldTruncate
    ? msg.content.slice(0, SHOW_MORE_THRESHOLD) + '...'
    : msg.content

  return (
    <div className="chat-message bot-message" data-time={timeStr}>
      <span className="chat-message__avatar-frame">
        <img
          alt="avatar"
          className="chat-message__avatar markdown-zoomable-image"
          src="./images/vivi-avatar.png"
          onError={(e) => {
            e.currentTarget.src = 'https://cdn-media.vinbase.ai/avatar/20250313024710_4.png'
          }}
        />
        VinFast
      </span>
      <div className="chat-message__text" title={timeStr}>
        <div className="chat-message_text_content">
          {streaming ? (
            <div className="raw-text">{msg.content}</div>
          ) : (
            <div className="md">
              <ReactMarkdown
                rehypePlugins={[[rehypeSanitize, _schema]]}
                components={{ a: SafeLink }}
              >
                {displayContent}
              </ReactMarkdown>
            </div>
          )}
        </div>

        {isLong && (
          <div
            className="chat-message__show_more_btn"
            onClick={() => setExpanded(!expanded)}
          >
            {expanded ? 'Thu gọn ▲' : 'Xem thêm ▼'}
          </div>
        )}

        <SourcesBox sources={msg.sources} />
      </div>
      <div className="cb-time-sent">{timeStr}</div>
    </div>
  )
}