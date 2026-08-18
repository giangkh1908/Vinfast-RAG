// ── State machine chat: idle → sending → streaming → done | error ─────────
// Chống spam Enter, nút Stop (AbortController), lỗi hiện rõ + Thử lại.
// Lưu ý: mọi side-effect localStorage đều NẰM NGOÀI setState updater
// (React StrictMode gọi updater 2 lần ở dev → tránh duplicate).

import { useCallback, useRef, useState } from 'react'
import { streamChat } from '../api'
import {
  clearSession,
  getHistory,
  getSessionId,
  getWindow,
  pushMessage,
  removeMessageById,
} from '../session'
import { toolLabel, type Message, type Source } from '../types'

export type Phase = 'idle' | 'sending' | 'streaming' | 'error'

export interface ChatState {
  phase: Phase
  messages: Message[]
  /** Text StatusBar — "Đang tra cứu giá xe…" — ẩn khi stream text đang chảy */
  statusText: string
  /** Đang có token nào rồi không (bỏ status khi có) */
  hasTokens: boolean
}

export function useChat() {
  const [state, setState] = useState<ChatState>(() => ({
    phase: 'idle',
    messages: getHistory().map((m) => ({
      ...m,
      status: 'done',
    })),
    statusText: '',
    hasTokens: false,
  }))

  const abortRef = useRef<AbortController | null>(null)
  /** Text assistant đang stream — dùng để lưu localStorage khi kết thúc */
  const contentRef = useRef('')
  /** Guard đồng bộ chống gửi trùng — closure `busy` bị stale khi Enter+click cùng tick */
  const busyRef = useRef(false)

  // ── Word-boundary smoothing ──────────────────────────────────────
  // Provider stream KHÔNG đều (burst rồi nghỉ). Nhưng KHÔNG xả theo thời gian
  // cố định 40ms (sẽ cắt giữa chừng từ: "đấy l" rồi "à ai").
  // Thay vào đó gom buffer, CHỈ xả khi trọn 1 TỪ (đến dấu cách/xuống dòng)
  // → tiếng Việt hiển thị mượt, không lộ từ dở dang.
  // `force=true` (khi done/stop) thì xả hết cả phần đuôi bất kể chưa trọn từ.
  const flushTimerRef = useRef<number | null>(null)
  const flushRef = useRef<(force?: boolean) => void>(() => {})
  const pendingRef = useRef('')
  const lastReleaseRef = useRef(Date.now())
  const FLUSH_MS = 30 // chu kỳ quét — từ hoàn chỉnh được ưu tiên xả nhanh
  // Nếu từ quá dài (URL/số không dấu cách) mà ứ lâu quá → xả luôn để tiến độ
  const FORCE_PARTIAL_AFTER_MS = 350

  const clearFlushTimer = useCallback(() => {
    if (flushTimerRef.current != null) {
      clearInterval(flushTimerRef.current)
      flushTimerRef.current = null
    }
    // xả nốt buffer còn dở (force) để DOM khớp contentRef (tránh mất chữ cuối)
    flushRef.current(true)
    pendingRef.current = ''
    flushRef.current = () => {}
  }, [])

  const patch = useCallback((p: Partial<ChatState>) => {
    setState((s) => ({ ...s, ...p }))
  }, [])

  const updateMsg = useCallback((id: string, p: Partial<Message>) => {
    setState((s) => ({
      ...s,
      messages: s.messages.map((m) => (m.id === id ? { ...m, ...p } : m)),
    }))
  }, [])

  const busy = state.phase === 'sending' || state.phase === 'streaming'

  const send = useCallback(
    async (text: string) => {
      const msg = text.trim()
      // Guard đồng bộ — KHÔNG dùng closure busy (stale khi 2 lần gọi cùng tick)
      if (!msg || busyRef.current) return
      busyRef.current = true

      const userMsg: Message = { id: crypto.randomUUID(), role: 'user', content: msg, status: 'done' }
      const asstMsg: Message = {
        id: crypto.randomUUID(),
        role: 'assistant',
        content: '',
        status: 'sending',
      }
      contentRef.current = ''

      setState((s) => ({
        ...s,
        phase: 'sending',
        statusText: 'Đang phân tích câu hỏi…',
        hasTokens: false,
        messages: [...s.messages, userMsg, asstMsg],
      }))
      pushMessage('user', msg, userMsg.id) // id khớp state — retry xoá đúng được

      const ac = new AbortController()
      abortRef.current = ac

      const sessionId = getSessionId()
      const window = getWindow() // đã gồm message vừa push (slice -14)

      // Hàm commit 1 cục token lên state (gọi theo chu kỳ, không phải từng token)
      const commitChunk = (chunk: string) => {
        if (!chunk) return
        setState((s) => ({
          ...s,
          phase: 'streaming',
          hasTokens: true,
          messages: s.messages.map((m) =>
            m.id === asstMsg.id
              ? { ...m, content: m.content + chunk, status: 'streaming' }
              : m,
          ),
        }))
      }

      // flushRef: xả buffer theo RANH GIỚI TỪ.
      // Mỗi nhịp chỉ xả tối đa một từ hoàn chỉnh để tránh provider gửi burst
      // lớn làm UI phun ra cả đoạn. Phần từ dở được giữ lại cho token tiếp theo.
      // `force` (done/stop) thì xả hết phần còn lại, kể cả từ chưa có dấu cách.
      flushRef.current = (force = false) => {
        const buf = pendingRef.current
        if (!buf) return

        // Tìm dấu cách/xuống dòng đầu tiên: đó là ranh giới của từ hoàn chỉnh đầu.
        const boundary = buf.search(/\s/)
        if (!force && boundary < 0) {
          // URL hoặc chuỗi không có dấu cách có thể bị giữ mãi; cho phép xả
          // sau một khoảng an toàn. Các từ bình thường vẫn luôn chờ đủ từ.
          if (Date.now() - lastReleaseRef.current <= FORCE_PARTIAL_AFTER_MS) return
          force = true
        }

        const chunk = force ? buf : buf.slice(0, boundary + 1)
        pendingRef.current = force ? '' : buf.slice(boundary + 1)
        lastReleaseRef.current = Date.now()
        commitChunk(chunk)
      }

      // Quét buffer đều; nếu provider gửi burst thì mỗi tick chỉ nhả một từ.
      const ensureFlushing = () => {
        if (flushTimerRef.current == null) {
          // globalThis.setInterval — tránh `window` local (getWindow) shadow biến toàn cục
          flushTimerRef.current = globalThis.setInterval(
            () => flushRef.current(),
            FLUSH_MS,
          )
        }
      }

      let finalAnswerFromEvent = ''
      let finishScheduled = false

      // `done` có thể đến ngay sau token cuối trong cùng một lần đọc SSE.
      // Không force-flush ngay, vì như vậy toàn bộ câu ngắn sẽ xồ ra một lần.
      // Chờ bộ word-buffer xả hết rồi mới chuyển message sang `done`.
      const finishAfterDrain = () => {
        if (finishScheduled) return
        if (pendingRef.current) {
          finishScheduled = true
          globalThis.setTimeout(() => {
            finishScheduled = false
            finishAfterDrain()
          }, FLUSH_MS)
          return
        }

        clearFlushTimer()
        const finalContent = finalAnswerFromEvent || contentRef.current
        if (finalContent) {
          pushMessage('assistant', finalContent, asstMsg.id)
        }
        contentRef.current = ''
        setState((s) => ({
          ...s,
          phase: 'idle',
          statusText: '',
          hasTokens: false,
          messages: s.messages.map((x) =>
            x.id === asstMsg.id
              ? {
                  ...x,
                  status: finalContent ? 'done' : 'error',
                  error: finalContent ? undefined : 'Không có phản hồi.',
                }
              : x,
          ),
        }))
      }

      try {
        await streamChat(
          sessionId,
          msg,
          window,
          ac.signal,
          {
            onStatus: (t) => {
              if (t) patch({ statusText: t })
            },
            onTool: (tool) => {
              // label thân thiện — user chỉ cần tiến độ, không cần tên tool
              patch({ statusText: toolLabel(tool) })
            },
            onToken: (token) => {
              contentRef.current += token
              // Bắt đầu tính timeout từ lúc có phần từ dở mới, không tính từ
              // lần stream trước hoặc từ lúc request bắt đầu (TTFT có thể lâu).
              if (!pendingRef.current) lastReleaseRef.current = Date.now()
              pendingRef.current += token
              ensureFlushing()
            },
            onAnswer: (answer) => {
              // Một số nhánh (clarify/out_of_scope) gửi nguyên câu qua `answer`
              // thay vì token stream. Vẫn đưa vào cùng word-buffer để câu ngắn
              // không xồ ra toàn bộ trong một render.
              finalAnswerFromEvent = answer
              contentRef.current = answer
              pendingRef.current = answer
              lastReleaseRef.current = Date.now()
              patch({ phase: 'streaming', hasTokens: true })
              updateMsg(asstMsg.id, { content: '', status: 'streaming' })
              ensureFlushing()
            },
            onSources: (sources: Source[]) => {
              updateMsg(asstMsg.id, { sources })
            },
            onError: (errMsg) => {
              // không lưu assistant lỗi vào localStorage — retry sẽ gửi lại sạch
              clearFlushTimer()
              pendingRef.current = ''
              flushRef.current = () => {}
              updateMsg(asstMsg.id, { status: 'error', error: errMsg, content: '' })
              contentRef.current = ''
              patch({ phase: 'error', statusText: '' })
            },
            onDone: () => {
              finishAfterDrain()
            },
          },
        )
      } finally {
        busyRef.current = false
        if (abortRef.current === ac) abortRef.current = null
      }
    },
    [patch, updateMsg, clearFlushTimer], // bỏ busy khỏi deps — guard dùng busyRef
  )

  /** Nút ⏹ Stop: hủy request — chốt phần đã stream */
  const stop = useCallback(() => {
    abortRef.current?.abort()
    abortRef.current = null
    busyRef.current = false
    clearFlushTimer()
    const partial = contentRef.current
    contentRef.current = ''
    if (partial) pushMessage('assistant', partial)
    setState((s) => ({
      ...s,
      phase: 'idle',
      statusText: '',
      hasTokens: false,
      messages: s.messages.map((m) =>
        m.role === 'assistant' && (m.status === 'sending' || m.status === 'streaming')
          ? { ...m, content: partial, status: 'done' }
          : m,
      ),
    }))
  }, [])

  /** Thử lại: xoá turn lỗi (user + assistant error) khỏi state & storage, gửi lại */
  const retry = useCallback(() => {
    const lastUser = [...state.messages].reverse().find((m) => m.role === 'user')
    if (!lastUser) return
    // xoá khỏi localStorage message user bị lỗi (sẽ được push lại bởi send)
    removeMessageById(lastUser.id)
    // xoá turn lỗi khỏi state: assistant error cuối + user cuối
    setState((s) => {
      const msgs = [...s.messages]
      while (msgs.length && msgs[msgs.length - 1].role === 'assistant' && msgs[msgs.length - 1].status === 'error') {
        msgs.pop()
      }
      if (msgs.length && msgs[msgs.length - 1].role === 'user') msgs.pop()
      return { ...s, messages: msgs, phase: 'idle', statusText: '', hasTokens: false }
    })
    void send(lastUser.content)
  }, [send, state.messages])

  /** "Chat mới": xoá session + history */
  const clearChat = useCallback(() => {
    abortRef.current?.abort()
    abortRef.current = null
    contentRef.current = ''
    clearFlushTimer()
    pendingRef.current = ''
    flushRef.current = () => {}
    clearSession()
    setState({ phase: 'idle', messages: [], statusText: '', hasTokens: false })
  }, [])

  return { ...state, busy, send, stop, retry, clearChat }
}

