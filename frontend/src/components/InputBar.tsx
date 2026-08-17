import { useRef } from 'react'

interface Props {
  busy: boolean
  onSend: (text: string) => void
}

export default function InputBar({ busy, onSend }: Props) {
  const inputRef = useRef<HTMLInputElement>(null)

  const submit = () => {
    const el = inputRef.current
    if (!el) return
    const text = el.value
    if (!text.trim() || busy) return // chống spam Enter khi đang xử lý
    el.value = ''
    onSend(text)
  }

  return (
    <div className="input-area">
      <input
        ref={inputRef}
        id="input"
        type="text"
        placeholder="Hỏi về xe VF: giá, thông số, tính năng..."
        autoComplete="off"
        disabled={busy}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault()
            submit()
          }
        }}
      />
      <button id="btn" onClick={submit} disabled={busy}>
        Gửi
      </button>
    </div>
  )
}
