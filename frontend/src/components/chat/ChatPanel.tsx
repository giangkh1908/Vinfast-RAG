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
    <div id="chat_screen" className="cw_body is-visible">
      {isEmpty ? (
        <WelcomeScreen onSelectPrompt={onSelectPrompt} />
      ) : (
        <div id="chat_history" className="chat_conversion" ref={scrollRef} onScroll={onScroll}>
          <div id="chat_log" className="chat_log">
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
                <button className="retry-btn" onClick={onRetry}>
                  <i className="mdi mdi-refresh"></i> Thử lại
                </button>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
