interface Props {
  text: string
  onStop: () => void
}

export default function StatusBar({ text, onStop }: Props) {
  if (!text) return null

  return (
    <div className="chat-message bot-message">
      <span className="chat-message__avatar-frame">
        <img
          alt="avatar"
          className="chat-message__avatar"
          src="./images/vivi-avatar.png"
          onError={(e) => {
            e.currentTarget.src = 'https://cdn-media.vinbase.ai/avatar/20250313024710_4.png'
          }}
        />
        VinFast
      </span>
      <div className="chat-message__text statusbar-bubble">
        <div className="vin-statusbar-content">
          <div className="vin-spinner"></div>
          <span className="statusbar-text">{text}</span>
          <button className="stop-btn" onClick={onStop} title="Dừng phản hồi">
            <i className="mdi mdi-stop"></i>
          </button>
        </div>
      </div>
    </div>
  )
}
