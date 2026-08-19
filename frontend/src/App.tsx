import { lazy, Suspense, useState, useEffect } from 'react'
import { useChat } from './hooks/useChat'
import { useTheme } from './hooks/useTheme'
import ChatHeader from './components/chat/ChatHeader'
import ChatPanel from './components/chat/ChatPanel'
import InputBar from './components/chat/InputBar'
import ChatFooter from './components/chat/ChatFooter'
import ChatLauncher from './components/chat/ChatLauncher'
import LandingPage from './components/landing/LandingPage'

// Code-split admin: khách hàng không cần tải bundle admin (charts/tables/telemetry)
// khi mở widget chat. Vite tách AdminDashboard thành chunk riêng, nạp khi có hash/path /admin.
const AdminDashboard = lazy(() => import('./components/admin/AdminDashboard'))

export default function App() {
  const chat = useChat()
  const theme = useTheme()
  const [isOpen, setIsOpen] = useState(true)
  const [isAdminRoute, setIsAdminRoute] = useState(false)

  // Router listener
  useEffect(() => {
    const checkAdminRoute = () => {
      const isAdm =
        window.location.pathname.includes('/admin') ||
        window.location.hash.toLowerCase().includes('admin')
      setIsAdminRoute(isAdm)
    }

    checkAdminRoute()
    window.addEventListener('hashchange', checkAdminRoute)
    window.addEventListener('popstate', checkAdminRoute)

    return () => {
      window.removeEventListener('hashchange', checkAdminRoute)
      window.removeEventListener('popstate', checkAdminRoute)
    }
  }, [])

  // Global keyboard shortcuts: Ctrl+K / Cmd+K to open/focus chat, Escape to close
  useEffect(() => {
    const handleGlobalKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setIsOpen(true)
        setTimeout(() => {
          document.getElementById('chatInput')?.focus()
        }, 100)
      } else if (e.key === 'Escape' && isOpen) {
        setIsOpen(false)
      }
    }

    window.addEventListener('keydown', handleGlobalKeyDown)
    return () => window.removeEventListener('keydown', handleGlobalKeyDown)
  }, [isOpen])

  const handleOpenWithPrompt = (initialPrompt?: string) => {
    setIsOpen(true)
    if (initialPrompt) {
      chat.send(initialPrompt)
    }
  }

  // CỔNG QUẢN TRỊ ADMIN ĐỘC LẬP (Không render landing hay chat widget)
  if (isAdminRoute) {
    return (
      <Suspense fallback={<div className="admin-loading">Đang tải…</div>}>
        <AdminDashboard />
      </Suspense>
    )
  }

  // TRANG KHÁCH HÀNG (Landing Page + Chatbot)
  return (
    <div className="vin-app-container mode-widget">
      <LandingPage onOpenChat={handleOpenWithPrompt} />

      {/* Main Chat Widget Window */}
      {isOpen && (
        <div
          className="chat is-visible is-floating"
          id="aip-chat-window"
          data-theme={theme.resolvedTheme}
          role="region"
          aria-label="Cửa sổ trò chuyện trợ lý VinFast"
          style={{ zIndex: 1000 }}
        >
          {/* VinFast Livechat Header */}
          <ChatHeader
            onClear={chat.clearChat}
            onMinimize={() => setIsOpen(false)}
            isWidget={true}
            theme={theme.resolvedTheme}
            onToggleTheme={theme.toggleTheme}
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
