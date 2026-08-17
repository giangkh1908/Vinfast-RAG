import TypingIndicator from './TypingIndicator'

/** StatusBar: tiến độ thân thiện — "Đang tra cứu giá xe…".
 *  Chỉ hiện khi đang xử lý (sending/streaming chưa có token). */
export default function StatusBar({
  text,
  onStop,
}: {
  text: string
  onStop: () => void
}) {
  return (
    <div className="statusbar">
      <TypingIndicator />
      <span className="statusbar-text">🔍 {text}</span>
      <button className="stop-btn" onClick={onStop} title="Dừng trả lời">
        ⏹
      </button>
    </div>
  )
}
