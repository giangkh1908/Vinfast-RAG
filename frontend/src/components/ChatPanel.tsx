import { useEffect, useRef } from 'react'
import MessageBubble from './MessageBubble'
import StatusBar from './StatusBar'
import type { ChatState } from '../hooks/useChat'

interface Props extends ChatState {
  onStop: () => void
  onRetry: () => void
}

export default function ChatPanel({ phase, messages, statusText, hasTokens, onStop, onRetry }: Props) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const nearBottomRef = useRef(true)

  // Theo dõi user có đang ở gần đáy không — chỉ auto-scroll khi ở đáy
  const onScroll = () => {
    const el = scrollRef.current
    if (!el) return
    nearBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 120
  }

  useEffect(() => {
    const el = scrollRef.current
    if (el && nearBottomRef.current) {
      el.scrollTop = el.scrollHeight
    }
  }, [messages, statusText, phase])

  return (
    <div className="chat" id="chat" ref={scrollRef} onScroll={onScroll}>
      {messages.map((m) => (
        <MessageBubble key={m.id} msg={m} />
      ))}

      {/* Tiến độ khi đang xử lý — bỏ khi token đã chảy */}
      {(phase === 'sending' || (phase === 'streaming' && !hasTokens)) && (
        <StatusBar text={statusText} onStop={onStop} />
      )}

      {phase === 'error' && (
        <div className="retry-bar">
          <button className="retry-btn" onClick={onRetry}>
            ↻ Thử lại
          </button>
        </div>
      )}
    </div>
  )
}
