import { useRef, useState, useEffect, useCallback } from 'react'
import { useSpeechToText } from '../../hooks/useSpeechToText'

interface Props {
  busy: boolean
  onSend: (text: string) => void
  onNewTopic: () => void
}

const COMMON_EMOJIS = ['😊', '🚗', '⚡', '👍', '❤️', '🔥', '✨', '👋', '💯', '🙏', '🇻🇳', '💡']

const QUICK_SUGGESTIONS = [
  'Bảng giá VF 3',
  'Thông số VF 7',
  'Giá lăn bánh VF 8',
  'Chính sách pin',
]

export default function InputBar({ busy, onSend, onNewTopic }: Props) {
  const [inputValue, setInputValue] = useState('')
  const [showEmoji, setShowEmoji] = useState(false)
  const [historyQueries, setHistoryQueries] = useState<string[]>([])
  const [voiceToast, setVoiceToast] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  // Real Web Speech API Hook
  const { isListening, isSupported, stopListening, toggleListening } =
    useSpeechToText({
      onTranscript: (transcript) => {
        setInputValue(transcript)
      },
      onError: (errMsg) => {
        setVoiceToast(errMsg)
        setTimeout(() => setVoiceToast(null), 4000)
      },
    })

  const handleSubmit = useCallback(() => {
    const text = inputValue.trim()
    if (!text || busy) return

    setHistoryQueries((prev) => [...prev, text])
    setInputValue('')
    setShowEmoji(false)
    if (isListening) {
      stopListening()
    }
    onSend(text)
  }, [busy, inputValue, isListening, onSend, stopListening])

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit()
    } else if (e.key === 'ArrowUp' && !inputValue.trim() && historyQueries.length > 0) {
      // Recall last sent message
      e.preventDefault()
      const lastQuery = historyQueries[historyQueries.length - 1]
      setInputValue(lastQuery)
    } else if (e.key === 'Escape') {
      if (showEmoji) setShowEmoji(false)
      if (isListening) stopListening()
    }
  }

  const handleAddEmoji = (emoji: string) => {
    setInputValue((prev) => prev + emoji)
    setShowEmoji(false)
    inputRef.current?.focus()
  }

  useEffect(() => {
    if (!busy && !isListening) {
      inputRef.current?.focus()
    }
  }, [busy, isListening])

  return (
    <div id="chat_input" className="fab_field" role="form" aria-label="Khu vực soạn tin nhắn">
      {/* Quick suggestions */}
      <div className="sample_suggestion" id="sample_suggestion" role="toolbar" aria-label="Gợi ý câu hỏi nhanh">
        {QUICK_SUGGESTIONS.map((chip, index) => (
          <button
            key={index}
            type="button"
            className="suggestion-chip"
            disabled={busy}
            onClick={() => onSend(chip)}
            aria-label={`Gợi ý: ${chip}`}
          >
            {chip}
          </button>
        ))}
      </div>

      {/* Emoji Picker */}
      {showEmoji && (
        <div className="emoji_list_picker__wrapper" role="dialog" aria-label="Chọn biểu tượng cảm xúc">
          <div id="emoji_list_picker" className="emoji_list_picker">
            {COMMON_EMOJIS.map((em, idx) => (
              <button
                key={idx}
                type="button"
                className="emoji-item"
                onClick={() => handleAddEmoji(em)}
                aria-label={`Chèn biểu tượng ${em}`}
              >
                {em}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Voice feedback toast */}
      {voiceToast && (
        <div className="voice-toast-alert" role="alert">
          <i className="mdi mdi-information-outline" aria-hidden="true"></i>
          <span>{voiceToast}</span>
        </div>
      )}

      {/* Realtime voice recording overlay */}
      {isListening && (
        <div id="voice_recording" className="voice-recording-overlay" role="region" aria-live="assertive">
          <div id="asr_content" className="asr_content">
            {inputValue ? `"${inputValue}"` : 'Đang lắng nghe tiếng Việt (nói vào microphone)...'}
          </div>
          <div id="btn_voice_recording" className="voice-waves">
            <div className="rectangle-1"></div>
            <div className="rectangle-2"></div>
            <div className="rectangle-3"></div>
            <div className="rectangle-4"></div>
            <button
              type="button"
              className="rectangle-5"
              onClick={toggleListening}
              aria-label="Dừng nhận diện giọng nói"
              title="Dừng ghi âm"
            >
              <i className="mdi mdi-microphone-off" style={{ fontSize: 24 }} aria-hidden="true"></i>
            </button>
          </div>
        </div>
      )}

      {/* Input controls row */}
      <div className="input-controls-row">
        {/* New topic button */}
        <button
          type="button"
          id="btn_new_topic"
          className="btn_new_topic"
          onClick={onNewTopic}
          title="Tạo chủ đề mới"
          aria-label="Tạo chủ đề mới"
          disabled={busy}
        >
          <i className="mdi mdi-square-edit-outline" style={{ fontSize: 22 }} aria-hidden="true"></i>
          <span className="tooltip">Đoạn chat mới</span>
        </button>

        {/* Emoji trigger */}
        <button
          type="button"
          className={`btn_emoji ${showEmoji ? 'active' : ''}`}
          onClick={() => setShowEmoji(!showEmoji)}
          title="Biểu tượng cảm xúc"
          aria-label="Mở bảng biểu tượng cảm xúc"
          aria-expanded={showEmoji}
          disabled={busy}
        >
          <i className="mdi mdi-emoticon-outline" style={{ fontSize: 22 }} aria-hidden="true"></i>
        </button>

        {/* Text Input Field */}
        <input
          ref={inputRef}
          id="chatInput"
          name="chat_message"
          placeholder={isListening ? 'Đang nhận diện giọng nói...' : 'Nhập tin nhắn hỏi về xe VinFast...'}
          className="chat_field chat_message"
          autoComplete="off"
          value={inputValue}
          onChange={(e) => setInputValue(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={busy}
          aria-label="Nội dung câu hỏi về xe VinFast"
        />

        {/* Voice Recognition Button */}
        <button
          type="button"
          id="btn_voice"
          className={`btn_send btn_voice ${isListening ? 'recording' : ''}`}
          onClick={toggleListening}
          title={isSupported ? 'Nhập bằng giọng nói tiếng Việt (Chrome Voice)' : 'Trình duyệt không hỗ trợ Web Speech'}
          aria-label={isListening ? 'Dừng nhận diện giọng nói' : 'Bật nhận diện giọng nói tiếng Việt'}
          aria-pressed={isListening}
          disabled={busy}
        >
          <i className={`mdi ${isListening ? 'mdi-microphone' : 'mdi-microphone-outline'}`} style={{ fontSize: 22 }} aria-hidden="true"></i>
        </button>

        {/* Send Button */}
        <button
          type="button"
          id="btn_send"
          className={`btn_send ${inputValue.trim() && !busy ? 'can-send' : 'disabled'}`}
          onClick={handleSubmit}
          title="Gửi tin nhắn"
          aria-label="Gửi tin nhắn"
          disabled={!inputValue.trim() || busy}
        >
          <svg width="18" height="16" viewBox="0 0 18 16" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
            <path
              d="M0.258942 15.7539C0.142983 15.643 0.0615673 15.5035 0.0237862 15.351C-0.0139949 15.1985 -0.00665356 15.0389 0.0449898 14.8901L1.89964 9.57778C1.9499 9.43427 2.03948 9.30625 2.15906 9.20702C2.27865 9.10778 2.42387 9.04097 2.57964 9.01352L9.62398 8.00002L2.58083 6.98537C2.42517 6.95804 2.28004 6.89133 2.16054 6.79218C2.04105 6.69304 1.95157 6.5651 1.90143 6.42168L0.0455848 1.10819C-0.00823961 0.952267 -0.0132867 0.784728 0.0310624 0.626105C0.0754115 0.467481 0.16723 0.324662 0.295267 0.21515C0.423304 0.105637 0.581998 0.0341855 0.751903 0.00955245C0.921808 -0.0150806 1.09555 0.00817347 1.25182 0.076466L17.4866 7.23306C17.6398 7.30046 17.7696 7.40842 17.8606 7.54415C17.9516 7.67988 18 7.83769 18 7.99888C18 8.16006 17.9516 8.31787 17.8606 8.4536C17.9516 8.58933 17.6398 8.69729 17.4866 8.7647L1.25182 15.9224C1.09546 15.9914 0.921378 16.0151 0.751072 15.9906C0.580767 15.9661 0.421696 15.8945 0.293509 15.7846L0.258942 15.7539Z"
              fill="currentColor"
            />
          </svg>
        </button>
      </div>
    </div>
  )
}
