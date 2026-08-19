import { useState } from 'react'

interface Props {
  onClear: () => void
  onMinimize?: () => void
  isWidget?: boolean
}

export default function ChatHeader({ onClear, onMinimize, isWidget }: Props) {
  const [showActionMenu, setShowActionMenu] = useState(false)

  return (
    <div id="chat_header" className="chat_header">
      <div className="chat_option">
        <div className="header_img">
          <img
            id="header_avatar"
            src="./images/vivi-avatar.png"
            onError={(e) => {
              e.currentTarget.src = 'https://cdn-media.vinbase.ai/avatar/20250313024710_4.png'
            }}
            alt="VinFast Vivi"
          />
        </div>
        <div className="header_info">
          <span id="chat_agent" className="chat_agent">VinFast</span>
          <span className="chat_status_badge">Trực tuyến</span>
        </div>



        {/* Action Menu (3 dots) */}
        <span
          id="chat_action_header"
          className="chat_fullscreen_loader"
          onClick={() => setShowActionMenu(!showActionMenu)}
          title="Tùy chọn"
        >
          <i className="mdi mdi-dots-horizontal" aria-hidden="true"></i>
        </span>

        {showActionMenu && (
          <div id="menu_header_action" className="menu_header_action is-open">
            <div
              className="menu_item"
              onClick={() => {
                onClear()
                setShowActionMenu(false)
              }}
            >
              <i className="mdi mdi-refresh"></i> Làm mới hội thoại
            </div>
            <a
              href="https://vinfastauto.com/vn_vi"
              target="_blank"
              rel="noopener noreferrer"
              className="menu_item"
              onClick={() => setShowActionMenu(false)}
            >
              <i className="mdi mdi-open-in-new"></i> Trang chủ VinFast
            </a>
          </div>
        )}

        {/* Close/Minimize button */}
        {isWidget && onMinimize && (
          <span
            id="chat_minimize"
            className="chat_fullscreen_loader"
            onClick={onMinimize}
            title="Đóng cửa sổ chat"
          >
            <i className="mdi mdi-close" aria-hidden="true"></i>
          </span>
        )}
      </div>
    </div>
  )
}
