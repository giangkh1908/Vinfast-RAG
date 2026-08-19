interface Props {
  isOpen: boolean
  onToggle: () => void
  unreadCount?: number
}

export default function ChatLauncher({ isOpen, onToggle, unreadCount = 0 }: Props) {
  return (
    <div
      className={`chat-launcher-btn ${isOpen ? 'is-active' : ''}`}
      onClick={onToggle}
      title={isOpen ? 'Đóng cửa sổ tư vấn' : 'Tư vấn xe VinFast'}
    >
      {isOpen ? (
        <i className="mdi mdi-close launcher-icon"></i>
      ) : (
        <div className="launcher-content">
          <img
            src="./images/vivi-avatar.png"
            onError={(e) => {
              e.currentTarget.src = 'https://cdn-media.vinbase.ai/avatar/20250313024710_4.png'
            }}
            alt="VinFast Vivi"
            className="launcher-avatar"
          />
          {unreadCount > 0 && <span className="launcher-badge">{unreadCount}</span>}
        </div>
      )}
    </div>
  )
}
