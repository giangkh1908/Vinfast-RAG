import { useState, useMemo } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeSanitize, { defaultSchema } from 'rehype-sanitize'
import SourcesBox from './SourcesBox'
import type { Message } from '../../types'

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
    th: [...(defaultSchema.attributes?.th ?? []), ['align']],
    td: [...(defaultSchema.attributes?.td ?? []), ['align']],
  },
  tagNames: [
    ...(defaultSchema.tagNames ?? []),
    'table', 'thead', 'tbody', 'tr', 'th', 'td',
  ],
}

function SafeLink(props: React.AnchorHTMLAttributes<HTMLAnchorElement>) {
  const { children, href, ...rest } = props
  return (
    <a href={href} target="_blank" rel="noopener noreferrer" {...rest}>
      {children}
    </a>
  )
}

function CodeBlock(props: React.HTMLAttributes<HTMLElement> & { inline?: boolean }) {
  const [copied, setCopied] = useState(false)
  const { children, className, inline } = props

  if (inline) {
    return <code className={`inline-code ${className || ''}`}>{children}</code>
  }

  const codeText = String(children).replace(/\n$/, '')

  const handleCopy = () => {
    navigator.clipboard.writeText(codeText)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div className="code-block-wrapper">
      <div className="code-block-header">
        <span className="code-lang">{className?.replace('language-', '') || 'text'}</span>
        <button
          type="button"
          className="btn-copy-code"
          onClick={handleCopy}
          aria-label="Sao chép khối mã"
          title="Sao chép"
        >
          <i className={`mdi ${copied ? 'mdi-check' : 'mdi-content-copy'}`} aria-hidden="true"></i>
          <span>{copied ? 'Đã chép' : 'Sao chép'}</span>
        </button>
      </div>
      <pre className="code-pre">
        <code>{children}</code>
      </pre>
    </div>
  )
}

function ResponsiveTable(props: React.TableHTMLAttributes<HTMLTableElement>) {
  return (
    <div className="table-responsive" role="region" aria-label="Bảng số liệu" tabIndex={0}>
      <table {...props}>{props.children}</table>
    </div>
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
      <article
        className="chat-message--right chat-message"
        data-time={timeStr}
        role="article"
        aria-label="Tin nhắn của bạn"
      >
        <span className="chat-message__avatar-frame chat-message__username">
          <i className="mdi mdi-account-circle" style={{ fontSize: 18, marginRight: 4 }} aria-hidden="true"></i>
          Bạn
        </span>
        <div className="chat-message__text" title={timeStr}>
          <div className="chat-message_text_content chat-user-message">
            {msg.content}
          </div>
        </div>
        <div className="cb-time-sent">{timeStr}</div>
      </article>
    )
  }

  const error = msg.status === 'error'
  const pending = (msg.status === 'sending' || msg.status === 'streaming') && !msg.content

  if (error) {
    return (
      <article
        className="chat-message bot-message"
        role="article"
        aria-label="Lỗi từ hệ thống trợ lý VinFast"
      >
        <span className="chat-message__avatar-frame">
          <img
            alt="VinFast Vivi Avatar"
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
            <i className="mdi mdi-alert-circle-outline" style={{ marginRight: 6 }} aria-hidden="true"></i>
            {msg.error || 'Đã có lỗi xảy ra khi xử lý phản hồi. Quý khách vui lòng thử lại.'}
          </div>
        </div>
      </article>
    )
  }

  if (pending) return null

  const streaming = msg.status === 'streaming' && !msg.content
  const isLong = !streaming && msg.content.length > SHOW_MORE_THRESHOLD
  const shouldTruncate = isLong && !expanded

  const displayContent = shouldTruncate
    ? msg.content.slice(0, SHOW_MORE_THRESHOLD) + '...'
    : msg.content

  return (
    <article
      className="chat-message bot-message"
      data-time={timeStr}
      role="article"
      aria-label="Phản hồi từ trợ lý VinFast"
    >
      <span className="chat-message__avatar-frame">
        <img
          alt="VinFast Vivi Avatar"
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
          {msg.status === 'streaming' ? (
            <div className="raw-text">{msg.content}</div>
          ) : (
            <div className="md">
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                rehypePlugins={[[rehypeSanitize, _schema]]}
                components={{
                  a: SafeLink,
                  table: ResponsiveTable,
                  code: CodeBlock as any,
                }}
              >
                {displayContent}
              </ReactMarkdown>
            </div>
          )}
        </div>

        {isLong && (
          <button
            type="button"
            className="chat-message__show_more_btn"
            onClick={() => setExpanded(!expanded)}
            aria-expanded={expanded}
            aria-label={expanded ? 'Thu gọn nội dung' : 'Xem thêm toàn bộ câu trả lời'}
          >
            {expanded ? 'Thu gọn ▲' : 'Xem thêm ▼'}
          </button>
        )}

        <SourcesBox sources={msg.sources} />
      </div>
      <div className="cb-time-sent">{timeStr}</div>
    </article>
  )
}