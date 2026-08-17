import { useChat } from './hooks/useChat'
import ChatPanel from './components/ChatPanel'
import InputBar from './components/InputBar'

export default function App() {
  const chat = useChat()

  return (
    <div className="app">
      <div className="header">
        <span>Vivu</span> — Tư vấn xe VinFast
        <button className="clear-btn" onClick={chat.clearChat} title="Bắt đầu hội thoại mới">
          Chat mới
        </button>
      </div>
      <ChatPanel
        phase={chat.phase}
        messages={chat.messages}
        statusText={chat.statusText}
        hasTokens={chat.hasTokens}
        onStop={chat.stop}
        onRetry={chat.retry}
      />
      <InputBar busy={chat.busy} onSend={chat.send} />
    </div>
  )
}
