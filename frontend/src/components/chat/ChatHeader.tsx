import { useState, useEffect, useRef } from 'react'

interface Props {
  onClear: () => void
  onMinimize?: () => void
  isWidget?: boolean
  theme?: 'light' | 'dark'
  onToggleTheme?: () => void
}

export default function ChatHeader({
  onClear,
  onMinimize,
  isWidget,
  theme = 'light',
  onToggleTheme,
}: Props) {
  const [showActionMenu, setShowActionMenu] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)

  // Close menu on Escape key or outside click
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && showActionMenu) {
        setShowActionMenu(false)
      }
    }

    const handleClickOutside = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setShowActionMenu(false)
      }
    }

    if (showActionMenu) {
      document.addEventListener('keydown', handleKeyDown)
      document.addEventListener('mousedown', handleClickOutside)
    }

    return () => {
      document.removeEventListener('keydown', handleKeyDown)
      document.removeEventListener('mousedown', handleClickOutside)
    }
  }, [showActionMenu])

  return (
    <header id="chat_header" className="chat_header" role="banner">
      <div className="chat_option">
        <div className="header_img">
          <img
            id="header_avatar"
            src="./images/vivi-avatar.png"
            onError={(e) => {
              e.currentTarget.src = 'https://cdn-media.vinbase.ai/avatar/20250313024710_4.png'
            }}
            alt="VinFast Vivi Avatar"
          />
        </div>
        <div className="header_info">
          <span id="chat_agent" className="chat_agent">
            VinFast
          </span>
          <span className="chat_status_badge" aria-label="Trạng thái: Trực tuyến">
            Trực tuyến
          </span>
        </div>

        {/* Theme Toggle Button */}
        {onToggleTheme && (
          <button
            type="button"
            className="chat_fullscreen_loader theme-toggle-btn"
            onClick={onToggleTheme}
            title={theme === 'dark' ? 'Chuyển sang giao diện sáng' : 'Chuyển sang giao diện tối'}
            aria-label={theme === 'dark' ? 'Chuyển sang giao diện sáng' : 'Chuyển sang giao diện tối'}
          >
            <i
              className={`mdi ${theme === 'dark' ? 'mdi-weather-sunny' : 'mdi-weather-night'}`}
              aria-hidden="true"
            ></i>
          </button>
        )}

        {/* Action Menu (3 dots) */}
        <div ref={menuRef} style={{ position: 'relative' }}>
          <button
            type="button"
            id="chat_action_header"
            className="chat_fullscreen_loader"
            onClick={() => setShowActionMenu(!showActionMenu)}
            title="Tùy chọn đoạn chat"
            aria-label="Tùy chọn đoạn chat"
            aria-haspopup="true"
            aria-expanded={showActionMenu}
          >
            <i className="mdi mdi-dots-horizontal" aria-hidden="true"></i>
          </button>

          {showActionMenu && (
            <div
              id="menu_header_action"
              className="menu_header_action is-open"
              role="menu"
              aria-label="Menu tùy chọn"
            >
              <button
                type="button"
                className="menu_item"
                role="menuitem"
                onClick={() => {
                  onClear()
                  setShowActionMenu(false)
                }}
              >
                <i className="mdi mdi-refresh" aria-hidden="true"></i> Làm mới hội thoại
              </button>
              <a
                href="https://vinfastauto.com/vn_vi"
                target="_blank"
                rel="noopener noreferrer"
                className="menu_item"
                role="menuitem"
                onClick={() => setShowActionMenu(false)}
              >
                <i className="mdi mdi-open-in-new" aria-hidden="true"></i> Trang chủ VinFast
              </a>
            </div>
          )}
        </div>

        {/* Close/Minimize button */}
        {isWidget && onMinimize && (
          <button
            type="button"
            id="chat_minimize"
            className="chat_fullscreen_loader"
            onClick={onMinimize}
            title="Đóng cửa sổ chat (Escape)"
            aria-label="Đóng cửa sổ chat"
          >
            <i className="mdi mdi-close" aria-hidden="true"></i>
          </button>
        )}
      </div>
    </header>
  )
}
