export default function TypingIndicator() {
  return (
    <div className="bot-replying-container" id="botReplying">
      <div className="chat-message bot-message typing-bubble-wrapper">
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
        <div className="chat-message__text typing-bubble">
          <div className="vin-typing-dots">
            <span></span>
            <span></span>
            <span></span>
          </div>
        </div>
      </div>
    </div>
  )
}
