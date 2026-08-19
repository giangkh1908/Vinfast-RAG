import { useEffect, useRef } from 'react'
import MessageBubble from './MessageBubble'
import StatusBar from './StatusBar'
import TypingIndicator from './TypingIndicator'
import WelcomeScreen from './WelcomeScreen'
import type { ChatState } from '../../hooks/useChat'

interface Props extends ChatState {
  onStop: () => void
  onRetry: () => void
  onSelectPrompt: (prompt: string) => void
}

export default function ChatPanel({
  phase,
  messages,
  statusText,
  hasTokens,
  onStop,
  onRetry,
  onSelectPrompt,
}: Props) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const nearBottomRef = useRef(true)

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

  const isEmpty = messages.length === 0

  return (
    <main id="chat_screen" className="cw_body is-visible" role="region" aria-label="Nội dung cuộc hội thoại">
      {isEmpty ? (
        <WelcomeScreen onSelectPrompt={onSelectPrompt} />
      ) : (
        <div
          id="chat_history"
          className="chat_conversion"
          ref={scrollRef}
          onScroll={onScroll}
          tabIndex={0}
          aria-label="Lịch sử tin nhắn"
        >
          <div id="chat_log" className="chat_log" role="log" aria-live="polite" aria-atomic="false">
            {messages.map((m) => (
              <MessageBubble key={m.id} msg={m} />
            ))}

            {/* Status progress bar khi backend đang chạy tool */}
            {statusText && !hasTokens && (
              <StatusBar text={statusText} onStop={onStop} />
            )}

            {/* Hiệu ứng gõ khi đang sending và chưa có text */}
            {(phase === 'sending' || (phase === 'streaming' && !hasTokens)) && !statusText && (
              <TypingIndicator />
            )}

            {/* Nút Thử lại khi gặp lỗi kết nối */}
            {phase === 'error' && (
              <div className="retry-bar">
                <button
                  type="button"
                  className="retry-btn"
                  onClick={onRetry}
                  aria-label="Thử lại câu trả lời vừa rồi"
                >
                  <i className="mdi mdi-refresh" aria-hidden="true"></i> Thử lại
                </button>
              </div>
            )}
          </div>
        </div>
      )}
    </main>
  )
}
