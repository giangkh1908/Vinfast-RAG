import { useState, useEffect } from 'react'
import { useChat } from './hooks/useChat'
import ChatHeader from './components/ChatHeader'
import ChatPanel from './components/ChatPanel'
import InputBar from './components/InputBar'
import ChatFooter from './components/ChatFooter'
import ChatLauncher from './components/ChatLauncher'
import LandingPage from './components/LandingPage'
import AdminDashboard from './components/AdminDashboard'

export default function App() {
  const chat = useChat()
  const [isOpen, setIsOpen] = useState(true)
  const [isAdminOpen, setIsAdminOpen] = useState(false)

  useEffect(() => {
    const checkAdminRoute = () => {
      if (
        window.location.pathname.includes('/admin') ||
        window.location.hash.toLowerCase().includes('admin')
      ) {
        setIsAdminOpen(true)
      } else {
        setIsAdminOpen(false)
      }
    }

    checkAdminRoute()
    window.addEventListener('hashchange', checkAdminRoute)
    window.addEventListener('popstate', checkAdminRoute)

    return () => {
      window.removeEventListener('hashchange', checkAdminRoute)
      window.removeEventListener('popstate', checkAdminRoute)
    }
  }, [])

  const handleCloseAdmin = () => {
    setIsAdminOpen(false)
    if (window.location.hash.toLowerCase().includes('admin')) {
      window.history.replaceState(null, '', window.location.pathname)
    }
  }

  const handleOpenWithPrompt = (initialPrompt?: string) => {
    setIsOpen(true)
    if (initialPrompt) {
      chat.send(initialPrompt)
    }
  }

  return (
    <div className="vin-app-container mode-widget">
      {/* VinFast Official Look Landing Page */}
      <LandingPage onOpenChat={handleOpenWithPrompt} />

      {/* Admin Telemetry & Observability Modal (Chỉ mở qua URL: /admin hoặc #admin) */}
      {isAdminOpen && <AdminDashboard onClose={handleCloseAdmin} />}

      {/* Main Chat Widget Window */}
      {isOpen && (
        <div
          className="chat is-visible is-floating"
          id="aip-chat-window"
          style={{ zIndex: 1000 }}
        >
          {/* VinFast Livechat Header */}
          <ChatHeader
            onClear={chat.clearChat}
            onMinimize={() => setIsOpen(false)}
            isWidget={true}
          />

          {/* Chat Body & Screen */}
          <ChatPanel
            phase={chat.phase}
            messages={chat.messages}
            statusText={chat.statusText}
            hasTokens={chat.hasTokens}
            onStop={chat.stop}
            onRetry={chat.retry}
            onSelectPrompt={chat.send}
          />

          {/* Input Field & Toolbar */}
          <InputBar
            busy={chat.busy}
            onSend={chat.send}
            onNewTopic={chat.clearChat}
          />

          {/* VinBigdata Footer */}
          <ChatFooter />
        </div>
      )}

      {/* Floating launcher trigger - chỉ hiển thị khi khung chat đóng */}
      {!isOpen && (
        <ChatLauncher
          isOpen={isOpen}
          onToggle={() => setIsOpen(true)}
          unreadCount={chat.messages.length > 0 ? 1 : 0}
        />
      )}
    </div>
  )
}
